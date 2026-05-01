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
    # Match `_year_{year}`, `_month_{month}`, `_day_0{day}`,
    # `_calendarday_{calendarday}` (and variants with extra underscores
    # or 0-prefix), which the SDP catalog uses as labeled placeholders
    # in URL templates.
    "year": re.compile(r"_+year_+\{year\}"),
    "month": re.compile(r"_+month_+\{month\}"),
    "day": re.compile(r"_+day_+0?\{day\}"),
    "calendarday": re.compile(r"_+\{calendarday\}"),
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
    for ph in ("year", "month", "day", "calendarday"):
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
    dates: Sequence[str | datetime.date] | None = None,
    bands: Sequence[int] | None = None,
    chunks: dict[str, int] | Literal["auto"] | None = "auto",
    download: bool = False,
    download_path: str | os.PathLike[str] | None = None,
    overwrite: bool = False,
    verbose: bool = True,
) -> xr.Dataset | dict[str, xr.Dataset]:
    """Open an SDP raster as a lazy ``xarray.Dataset``.

    Reads cloud-optimized GeoTIFFs from S3 via GDAL's VSICURL, without
    downloading. Returns a Dataset with one data variable named after the
    product's canonical short name (e.g. ``"UG_dem_3m_v1"``). CRS is always
    set to ``EPSG:32613`` (UTM 13N). For time-series products, the Dataset
    gains a uniform ``pandas.DatetimeIndex`` on the ``time`` coordinate —
    Daily → actual date, Monthly → first-of-month, Yearly → Jan 1.

    Parameters
    ----------
    catalog_id : str, optional
        Six-character SDP catalog ID (e.g., ``"R3D009"``). Mutually
        exclusive with ``url``. When given, scale/offset metadata from the
        catalog are attached as CF attrs on the data variable.
    url : str, optional
        Direct HTTPS URL to an SDP COG. Mutually exclusive with
        ``catalog_id``. No catalog lookup, so scale/offset attrs come from
        the COG header only.
    years : sequence of int, optional
        For Yearly products, which years to load. Alternative to
        ``date_start``/``date_end``.
    months : sequence of int, optional
        For Monthly products, which months (1–12) to load. Must be combined
        with ``years`` or used alone (all years × months requested).
    date_start, date_end : str or datetime.date, optional
        Date range to load (inclusive). For Daily, defines the time slice;
        for Monthly/Yearly, uses rSDP's anchor-day stepping semantics. When
        neither is given on a Daily product, the first 30 days from
        ``MinDate`` are loaded to avoid accidental 10-year VSICURL handle
        explosions (matches rSDP).
    chunks : dict, "auto", or None, default "auto"
        Dask chunking. ``"auto"`` uses xarray's chunk inference (requires
        ``pysdp[dask]``; falls back to eager reads with a warning if dask
        isn't installed). ``None`` eager-loads. Pass a dict for manual
        control (e.g., ``{"x": 1024, "y": 1024}``).
    download : bool, default False
        **Not yet implemented (Phase 5).** For now, raises
        ``NotImplementedError``. Use ``pysdp.download()`` to bulk-fetch
        COGs to disk, then open them with ``rioxarray.open_rasterio``.
    download_path : str or PathLike, optional
        Directory for downloaded files (only used when ``download=True``).
    overwrite : bool, default False
        Reserved for the download path (not yet implemented).
    verbose : bool, default True
        If ``True``, print progress messages (layer count etc.) to stderr.

    Returns
    -------
    xarray.Dataset
        Dataset with one data variable. Dimensions depend on the product:

        - ``(y, x)`` for single-band ``Single`` products
        - ``(band, y, x)`` for multi-band ``Single`` products
        - ``(time, y, x)`` for ``Yearly``/``Monthly``/``Daily`` time-series
          (where ``time`` is a ``pandas.DatetimeIndex``)

        CRS is ``EPSG:32613`` written via ``rio.write_crs``. Catalog-derived
        scale/offset metadata is attached to the variable as CF
        ``scale_factor`` and ``add_offset`` attrs; call
        ``ds.decode_cf()`` or open with ``mask_and_scale=True`` to
        materialize real values.

    Raises
    ------
    ValueError
        On invalid ``catalog_id`` / ``url`` combinations, time-arg
        combinations inconsistent with the product's ``TimeSeriesType``, or
        a ``url`` that doesn't start with ``https://``.
    KeyError
        If ``catalog_id`` isn't in the packaged catalog.
    NotImplementedError
        If ``download=True`` (Phase 5 stub).

    Examples
    --------
    Open the UG 3 m bare-earth DEM (``Single`` product):

    >>> import pysdp
    >>> dem = pysdp.open_raster("R3D009")  # doctest: +SKIP
    >>> dem.rio.crs.to_epsg()  # doctest: +SKIP
    32613

    Open three days of daily Tmax:

    >>> tmax = pysdp.open_raster(
    ...     "R4D004",
    ...     date_start="2021-11-02",
    ...     date_end="2021-11-04",
    ... )  # doctest: +SKIP
    >>> tmax.sizes["time"]  # doctest: +SKIP
    3

    Open a single year of annual snow persistence:

    >>> snow = pysdp.open_raster("R4D001", years=[2019])  # doctest: +SKIP

    See Also
    --------
    open_stack : Load multiple products as variables in one Dataset.
    extract_points : Sample an opened raster at point locations.
    extract_polygons : Summarize an opened raster over polygons.
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
            dates=dates,
            verbose=verbose,
        )

        # Irregular imagery: varying extents per date → dict of Datasets.
        if slices.is_imagery:
            result_dict: dict[str, xr.Dataset] = {}
            for path, name in zip(slices.paths, slices.names, strict=True):
                da = _open_one(path, chunks=chunks)
                if bands is not None:
                    da = da.isel(band=list(bands)) if "band" in da.dims else da
                ds = da.to_dataset(
                    name=_canonical_variable_name(
                        str(cat_line["Data.URL"]), str(cat_line["CatalogID"])
                    )
                )
                result_dict[name] = _apply_metadata(
                    ds,
                    var_name=str(next(iter(ds.data_vars))),
                    scale_factor=float(cat_line.get("DataScaleFactor", 1)),
                    offset=float(cat_line.get("DataOffset", 0)),
                )
            if verbose:
                _emit_msg = (
                    f"Returning a dict of {len(result_dict)} Datasets (one per "
                    f"date). Irregular imagery has varying extents and cannot be "
                    f"stacked into a single Dataset."
                )
                import sys

                print(_emit_msg, file=sys.stderr)
            return result_dict

        ds = _build_dataset(slices, cat_line=cat_line, url=None, chunks=chunks)
        if bands is not None and "band" in next(iter(ds.data_vars.values())).dims:
            var_name = next(iter(ds.data_vars))
            ds[var_name] = ds[var_name].isel(band=list(bands))
        return ds

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
    """Load multiple SDP products into a single ``xarray.Dataset``.

    Each product becomes one data variable. ``x``/``y`` (and ``time`` where
    applicable) coordinates are shared across variables, so downstream
    analysis can treat the stack as a single object (``ds["dem"] -
    ds["snow_persistence"].mean("time")`` etc.). Use this when you want to
    compose products that are already on the same grid — for example an
    elevation model and a slope raster both derived from the same LiDAR
    campaign.

    Parameters
    ----------
    catalog_ids : sequence of str
        Non-empty sequence of SDP catalog IDs.
    years, months, date_start, date_end : optional
        Shared time-slicing args. Applied to every time-series product in
        the stack; ignored for ``Single`` products.
    chunks : dict, "auto", or None, default "auto"
        Dask chunking, passed through to each ``open_raster`` call.
    align : {"exact", "reproject"}, default "exact"
        ``"exact"`` requires all products to share CRS + transform +
        shape; raises ``ValueError`` on mismatch with a descriptive list of
        which products diverged. ``"reproject"`` reprojects to the first
        product's grid via ``odc-stac`` (planned for Phase 7 of the
        ROADMAP; currently raises ``NotImplementedError``).
    verbose : bool, default True
        Forwarded to ``open_raster`` for per-product progress messages.

    Returns
    -------
    xarray.Dataset
        One data variable per catalog_id. See
        :func:`open_raster` for per-variable shape and CRS.

    Raises
    ------
    ValueError
        If ``catalog_ids`` is empty, if ``align`` isn't one of the two
        valid values, or (with ``align="exact"``) if the products don't
        share a common grid.
    NotImplementedError
        If ``align="reproject"`` (Phase 7 future work).

    Examples
    --------
    Stack the UG 3 m DEM with the matching slope and aspect rasters:

    >>> import pysdp
    >>> topo = pysdp.open_stack(["R3D009", "R3D012", "R3D010"])  # doctest: +SKIP
    >>> sorted(topo.data_vars)  # doctest: +SKIP
    ['UG_dem_3m_v1', 'UG_dem_slope_1m_v1', 'UG_topographic_aspect_southness_1m_v1']

    See Also
    --------
    open_raster : Single-product load.
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

    results = [
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
    # Imagery products return dict[str, Dataset]; can't stack those.
    datasets: list[xr.Dataset] = []
    for cid, r in zip(catalog_ids, results, strict=True):
        if isinstance(r, dict):
            raise TypeError(
                f"open_stack cannot include imagery product {cid!r} (varying "
                f"extents per date). Open it separately via open_raster()."
            )
        datasets.append(r)
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
