"""Lazy cloud raster access.

Ports rSDP's `sdp_get_raster()` and its internal loader helpers. Adds
`open_stack()` for multi-product loads. Returns `xarray.Dataset` with
one data variable per product (SPEC §4.2).
"""

from __future__ import annotations

import os
import re
import warnings
from typing import TYPE_CHECKING, Any, Literal, cast

# Module-level rioxarray import registers the `.rio` accessor on xarray
# DataArray / Dataset, which other functions in this module and downstream
# callers rely on. Without this, `ds.rio.write_crs(...)` raises AttributeError.
import rioxarray  # noqa: F401
import xarray as xr

from pysdp._catalog_data import lookup_catalog_row
from pysdp._resolve import TimeSlices, resolve_time_slices
from pysdp._validate import validate_args_vs_type, validate_user_args
from pysdp.constants import SDP_CRS, VSICURL_PREFIX
from pysdp.io.vsicurl import ensure_gdal_defaults

if TYPE_CHECKING:
    import datetime
    from collections.abc import Mapping, Sequence

    import pandas as pd


# ---------------------------------------------------------------------------
# Canonical variable naming
# ---------------------------------------------------------------------------


_PLACEHOLDER_PATTERNS = {
    # Match `_year_{year}`, `_month_{month}`, `_day_0{day}` (and variants
    # with extra underscores or 0-prefix), which the SDP catalog uses as
    # labeled placeholders in URL templates.
    "year": re.compile(r"_+year_+\{year\}"),
    "month": re.compile(r"_+month_+\{month\}"),
    "day": re.compile(r"_+day_+0?\{day\}"),
}


def _canonical_variable_name(data_url: str, catalog_id: str) -> str:
    """Derive a clean data-variable name from a COG URL (template).

    Strips `.tif`, removes labeled placeholder segments
    (`_year_{year}`, `_month_{month}`, `_day_0{day}`), then removes any
    bare remaining placeholders. Collapses repeated underscores. Falls back
    to the catalog_id if the result would be empty.
    """
    name = os.path.basename(data_url)
    # rSDP strips `.tif` with an unanchored regex; match that (preserves any
    # subtle edge-case behavior from the R side).
    name = re.sub(r".tif", "", name)
    for pattern in _PLACEHOLDER_PATTERNS.values():
        name = pattern.sub("", name)
    # Any remaining bare placeholders (unlabeled templates).
    for ph in ("year", "month", "day"):
        name = re.sub(rf"_?\{{{ph}\}}_?", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name if name else catalog_id


# ---------------------------------------------------------------------------
# Time coordinate construction
# ---------------------------------------------------------------------------


def _time_coord(names: Sequence[str], ts_type: str) -> pd.DatetimeIndex:
    """Build a uniform `pd.DatetimeIndex` for a time-series Dataset.

    Per SPEC §4.2: Daily → actual date, Monthly → first-of-month,
    Yearly → Jan 1. Uniform dtype lets `ds.sel(time="2019")` /
    `.resample(...)` / `groupby("time.year")` work across all types.
    """
    import pandas as pd

    if ts_type == "Daily":
        return pd.to_datetime(list(names), format="%Y-%m-%d")
    if ts_type == "Monthly":
        return pd.to_datetime([f"{n}-01" for n in names], format="%Y-%m-%d")
    if ts_type == "Yearly":
        return pd.to_datetime([f"{n}-01-01" for n in names], format="%Y-%m-%d")
    raise ValueError(f"Unsupported TimeSeriesType for time coord: {ts_type!r}")


# ---------------------------------------------------------------------------
# Raster loading
# ---------------------------------------------------------------------------


def _resolve_chunks(chunks: Any) -> Any:
    """Translate `chunks="auto"` to None when dask is unavailable, with a warning.

    Users who install `pysdp[dask]` get lazy, chunked reads. Users without
    dask get an eager load (still functional, just uses more memory for big
    rasters). Keeps default `chunks="auto"` from erroring on a vanilla install.
    """
    if chunks != "auto":
        return chunks
    try:
        import dask  # noqa: F401
    except ImportError:
        warnings.warn(
            "chunks='auto' requires dask. Install `pysdp[dask]` for lazy "
            "reads of large/time-series COGs. Falling back to eager load.",
            UserWarning,
            stacklevel=3,
        )
        return None
    return chunks


def _open_one(path: str, *, chunks: Any) -> xr.DataArray:
    """Open a single COG via rioxarray and squeeze single-band to (y, x).

    SDP COGs always return a single `DataArray` (not a `Dataset` or list),
    so the cast here is safe — it just narrows rioxarray's broad return type.
    """
    da = cast(xr.DataArray, rioxarray.open_rasterio(path, chunks=_resolve_chunks(chunks)))
    if da.sizes.get("band", 1) == 1:
        da = da.squeeze("band", drop=True)
    return da


def _apply_metadata(
    ds: xr.Dataset,
    *,
    var_name: str,
    scale_factor: float | None,
    offset: float | None,
) -> xr.Dataset:
    """Write CRS to the Dataset and attach CF scale/offset attrs to the variable.

    The catalog's ``DataScaleFactor`` is "divide by this to get real value"
    (rSDP's convention — see R/internal_load.R `cbind(1/scale_factor, offset)`).
    The CF interpretation is ``real = encoded * scale + offset``, so we
    record ``scale_factor = 1 / DataScaleFactor`` and ``add_offset = DataOffset``.
    Downstream ``xarray.decode_cf()`` or ``mask_and_scale=True`` materialize
    the real values.
    """
    ds = ds.rio.write_crs(SDP_CRS)
    if scale_factor is not None and offset is not None and scale_factor != 0:
        ds[var_name].attrs["scale_factor"] = 1.0 / float(scale_factor)
        ds[var_name].attrs["add_offset"] = float(offset)
    return ds


def _build_dataset(
    slices: TimeSlices,
    *,
    cat_line: Mapping[str, Any] | None,
    url: str | None,
    chunks: Any,
) -> xr.Dataset:
    """Open one or more COG slices and assemble into a single-variable Dataset."""
    if cat_line is not None:
        var_name = _canonical_variable_name(str(cat_line["Data.URL"]), str(cat_line["CatalogID"]))
        ts_type = str(cat_line["TimeSeriesType"])
        scale_factor = cat_line.get("DataScaleFactor")
        offset = cat_line.get("DataOffset")
    else:
        # url= branch: no catalog entry, so no scale/offset.
        assert url is not None
        var_name = _canonical_variable_name(url, catalog_id="url")
        ts_type = "Single"
        scale_factor = None
        offset = None

    if ts_type == "Single":
        da = _open_one(slices.paths[0], chunks=chunks)
        ds = da.to_dataset(name=var_name)
    else:
        arrays = [_open_one(p, chunks=chunks) for p in slices.paths]
        import pandas as pd

        time_idx = pd.Index(_time_coord(slices.names, ts_type), name="time")
        combined = xr.concat(arrays, dim=time_idx)
        ds = combined.to_dataset(name=var_name)

    return _apply_metadata(
        ds,
        var_name=var_name,
        scale_factor=float(scale_factor) if scale_factor is not None else None,
        offset=float(offset) if offset is not None else None,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def open_raster(
    catalog_id: str | None = None,
    url: str | None = None,
    *,
    years: Sequence[int] | None = None,
    months: Sequence[int] | None = None,
    date_start: str | datetime.date | None = None,
    date_end: str | datetime.date | None = None,
    chunks: dict[str, int] | Literal["auto"] | None = "auto",
    download: bool = False,
    download_path: str | os.PathLike[str] | None = None,
    overwrite: bool = False,
    verbose: bool = True,
) -> xr.Dataset:
    """Open an SDP raster as a lazy `xarray.Dataset`.

    See SPEC.md §4.2 for the full contract. Returns a Dataset with one data
    variable named after the product's canonical short name, dims
    ``(y, x)`` / ``(band, y, x)`` for single-layer, ``(time, y, x)`` for
    time-series.
    """
    ensure_gdal_defaults()
    normalized = validate_user_args(
        catalog_id=catalog_id,
        url=url,
        years=years,
        months=months,
        date_start=date_start,
        date_end=date_end,
        download_files=download,
        download_path=download_path,
    )
    months_pad = normalized["months_pad"]

    if download:
        raise NotImplementedError(
            "download=True is implemented in Phase 5; see `pysdp.download()` "
            "for the bulk-download path. Phase 3 supports lazy cloud reads only."
        )

    if catalog_id is not None:
        # `pd.Series` quacks as `Mapping[str, Any]` for our purposes; convert
        # so the resolver + dataset builder can be typed against a simple
        # Mapping and also accept plain-dict fixtures in unit tests.
        cat_line: dict[str, Any] = dict(lookup_catalog_row(catalog_id))
        ts_type = str(cat_line["TimeSeriesType"])
        validate_args_vs_type(
            ts_type,
            years=years,
            months=months,
            date_start=date_start,
            date_end=date_end,
        )
        slices = resolve_time_slices(
            cat_line,
            years=years,
            months_pad=months_pad,
            date_start=date_start,
            date_end=date_end,
            verbose=verbose,
        )
        return _build_dataset(slices, cat_line=cat_line, url=None, chunks=chunks)

    # url= branch: single-layer only. Scale/offset are skipped (no catalog row).
    assert url is not None
    if not url.startswith("https://"):
        raise ValueError("A valid URL must start with 'https://'.")
    slices = TimeSlices(paths=[VSICURL_PREFIX + url], names=[])
    return _build_dataset(slices, cat_line=None, url=url, chunks=chunks)


def open_stack(
    catalog_ids: Sequence[str],
    *,
    years: Sequence[int] | None = None,
    months: Sequence[int] | None = None,
    date_start: str | datetime.date | None = None,
    date_end: str | datetime.date | None = None,
    chunks: dict[str, int] | Literal["auto"] | None = "auto",
    align: Literal["exact", "reproject"] = "exact",
    verbose: bool = True,
) -> xr.Dataset:
    """Load multiple SDP products into a single `xarray.Dataset`.

    One data variable per product; shared ``x``/``y`` (and ``time`` where
    applicable). See SPEC.md §4.2.

    ``align="exact"`` (default) requires all products to share CRS, transform,
    and shape; raises a descriptive error otherwise with a pointer to
    ``align="reproject"``.

    ``align="reproject"`` is planned for Phase 7 (requires `odc-stac` from the
    ``[stac]`` extra to do efficient Dask-aware reprojection). Today it raises
    `NotImplementedError`.
    """
    if not catalog_ids:
        raise ValueError("catalog_ids must be a non-empty sequence.")
    if align == "reproject":
        raise NotImplementedError(
            "align='reproject' is implemented in Phase 7 (requires `pip install "
            "pysdp[stac]`). For now, pass `align='exact'` and load products "
            "that share a grid, or reproject explicitly with rioxarray."
        )
    if align != "exact":
        raise ValueError(f"Unknown align: {align!r}. Must be 'exact' or 'reproject'.")

    datasets = [
        open_raster(
            cid,
            years=years,
            months=months,
            date_start=date_start,
            date_end=date_end,
            chunks=chunks,
            verbose=verbose,
        )
        for cid in catalog_ids
    ]
    _verify_exact_alignment(datasets, catalog_ids=list(catalog_ids))
    return xr.merge(datasets, compat="equals", join="exact")


def _verify_exact_alignment(datasets: Sequence[xr.Dataset], *, catalog_ids: Sequence[str]) -> None:
    """Raise a descriptive ValueError if the grids of all datasets don't match."""
    first = datasets[0]
    first_transform = first.rio.transform()
    first_crs = first.rio.crs
    first_shape = (first.sizes.get("y"), first.sizes.get("x"))

    mismatches: list[str] = []
    for cid, ds in zip(catalog_ids[1:], datasets[1:], strict=True):
        ds_transform = ds.rio.transform()
        ds_crs = ds.rio.crs
        ds_shape = (ds.sizes.get("y"), ds.sizes.get("x"))
        if ds_crs != first_crs:
            mismatches.append(f"  {cid}: CRS {ds_crs} != {first_crs}")
        if ds_transform != first_transform:
            mismatches.append(f"  {cid}: transform mismatch")
        if ds_shape != first_shape:
            mismatches.append(f"  {cid}: shape (y,x)={ds_shape} != {first_shape}")

    if mismatches:
        raise ValueError(
            "open_stack(align='exact') requires all products to share grid "
            "(CRS + transform + shape). Mismatches:\n"
            + "\n".join(mismatches)
            + "\n\nPass `align='reproject'` (Phase 7) to reproject to the first "
            "product's grid, or open each product individually and handle "
            "alignment yourself with rioxarray."
        )


__all__ = [
    "open_raster",
    "open_stack",
]
