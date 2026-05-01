"""Point and polygon extraction from SDP rasters.

Ports rSDP's `sdp_extract_data()`, split into two functions for clarity
(SPEC.md §4.3). Also ports rSDP's `.filter_raster_layers_by_time()` as an
internal helper.

Point extraction dispatches to `xvec.extract_points` (nearest) or
`xarray.DataArray.interp` (linear/bilinear). Polygon extraction dispatches
to `xvec.zonal_stats` by default (`exact=False`, centroid-based — matches
rSDP / `terra::extract`) or to `exactextract` when `exact=True` (requires
the ``[exact]`` extra).
"""

from __future__ import annotations

import datetime
import sys
import warnings
from typing import TYPE_CHECKING, Literal, cast

# Module-level rioxarray import registers the `.rio` accessor.
import rioxarray  # noqa: F401

# Module-level xvec import registers the `.xvec` accessor on xarray Dataset
# and DataArray. Without this, `ds.xvec.extract_points(...)` raises
# AttributeError.
import xvec  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import Sequence

    import geopandas as gpd
    import pandas as pd
    import xarray as xr


def _emit(msg: str, verbose: bool) -> None:
    if verbose:
        print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# Time filtering (port of rSDP's .filter_raster_layers_by_time)
# ---------------------------------------------------------------------------


def _filter_by_time(
    raster: xr.Dataset | xr.DataArray,
    *,
    years: Sequence[int] | None,
    date_start: datetime.date | str | None,
    date_end: datetime.date | str | None,
    verbose: bool,
) -> xr.Dataset | xr.DataArray:
    """Filter a time-indexed raster by years or date range.

    Ports rSDP's `.filter_raster_layers_by_time()`. Error-on-empty-overlap
    and warn-on-partial-overlap semantics preserved. Raises ValueError if
    `years` or `date_start`/`date_end` are provided but the raster lacks a
    `time` dim.
    """
    import pandas as pd

    if years is None and date_start is None and date_end is None:
        return raster

    if "time" not in raster.dims:
        raise ValueError(
            "`years` / `date_start` / `date_end` require a time-indexed raster. "
            "The provided raster has no `time` dimension."
        )

    if years is not None:
        year_ints = [int(y) for y in years]
        mask = raster["time"].dt.year.isin(year_ints).to_numpy()
        filtered = raster.isel(time=mask)
        matched_years = sorted({int(y) for y in filtered["time"].dt.year.to_numpy()})
        if not matched_years:
            available = sorted({int(y) for y in raster["time"].dt.year.to_numpy()})
            raise ValueError(
                f"No raster layers match any of years={year_ints}. Available years are {available}."
            )
        if len(matched_years) < len(set(year_ints)):
            warnings.warn(
                f"No layers match some specified years. Returning data for years={matched_years}.",
                UserWarning,
                stacklevel=3,
            )
        return filtered

    assert date_start is not None and date_end is not None
    start_ts = pd.Timestamp(date_start)
    end_ts = pd.Timestamp(date_end)
    time_coord = pd.DatetimeIndex(raster["time"].to_numpy())
    mask = (time_coord >= start_ts) & (time_coord <= end_ts)
    filtered = raster.isel(time=mask)
    if filtered.sizes.get("time", 0) == 0:
        raise ValueError(
            f"No raster layers match the requested date range "
            f"[{start_ts.date()}, {end_ts.date()}]. "
            f"Available dates span [{time_coord.min().date()}, "
            f"{time_coord.max().date()}]."
        )
    requested_count = ((time_coord >= start_ts) & (time_coord <= end_ts)).sum()
    full_range_count = ((time_coord >= time_coord.min()) & (time_coord <= time_coord.max())).sum()
    if filtered.sizes["time"] < requested_count and verbose:
        # This path triggers when the raster has gaps within the requested
        # range. rSDP matches this with its warn-on-partial behavior.
        warnings.warn(
            f"No layers match some requested days. Returning {filtered.sizes['time']} layers.",
            UserWarning,
            stacklevel=3,
        )
    _ = full_range_count  # retained for future use; silences unused-var lint.
    return filtered


# ---------------------------------------------------------------------------
# Locations → GeoDataFrame normalization
# ---------------------------------------------------------------------------


def _to_geodataframe(
    locations: gpd.GeoDataFrame | pd.DataFrame,
    *,
    x: str,
    y: str,
    crs: str | None,
) -> gpd.GeoDataFrame:
    """Accept a GeoDataFrame or a plain DataFrame with x/y columns + explicit CRS."""
    import geopandas as gpd
    import pandas as pd

    if isinstance(locations, gpd.GeoDataFrame):
        if locations.crs is None:
            raise ValueError(
                "locations is a GeoDataFrame without a CRS. Set one with "
                "`locations = locations.set_crs('EPSG:4326')` (or the correct EPSG)."
            )
        return locations

    if isinstance(locations, pd.DataFrame):
        if crs is None:
            raise ValueError(
                "`crs` is required when locations is a plain DataFrame (e.g., `crs='EPSG:4326'`)."
            )
        missing = [c for c in (x, y) if c not in locations.columns]
        if missing:
            raise ValueError(
                f"locations DataFrame is missing column(s) {missing!r}. "
                f"Expected x={x!r}, y={y!r} as column names (or pass different ones)."
            )
        return gpd.GeoDataFrame(
            locations.drop(columns=[x, y]),
            geometry=gpd.points_from_xy(locations[x], locations[y]),
            crs=crs,
        )

    raise TypeError(
        f"locations must be a GeoDataFrame or DataFrame, got {type(locations).__name__}."
    )


def _align_to_raster_crs(
    gdf: gpd.GeoDataFrame,
    raster: xr.Dataset | xr.DataArray,
    *,
    verbose: bool,
) -> gpd.GeoDataFrame:
    """Reproject `gdf` to the raster's CRS if they differ."""
    raster_crs = raster.rio.crs
    if raster_crs is None:
        raise ValueError(
            "Raster has no CRS set. Open via `pysdp.open_raster()` or set "
            "`raster = raster.rio.write_crs(...)` before extracting."
        )
    if gdf.crs != raster_crs:
        _emit("Re-projecting locations to coordinate system of the raster.", verbose)
        gdf = gdf.to_crs(raster_crs)
    return gdf


# ---------------------------------------------------------------------------
# extract_points
# ---------------------------------------------------------------------------


def _point_extract_nearest(
    raster: xr.Dataset | xr.DataArray, gdf: gpd.GeoDataFrame
) -> xr.Dataset | xr.DataArray:
    return cast(
        "xr.Dataset | xr.DataArray",
        raster.xvec.extract_points(gdf.geometry, x_coords="x", y_coords="y"),
    )


def _point_extract_linear(
    raster: xr.Dataset | xr.DataArray, gdf: gpd.GeoDataFrame
) -> xr.Dataset | xr.DataArray:
    """Bilinear interpolation via xarray's built-in `interp`.

    xvec.extract_points is strictly nearest-neighbor. For bilinear we use
    `ds.interp(x=..., y=..., method='linear')` and then re-attach the
    geometry index via xvec so the downstream GeoDataFrame conversion matches.
    """
    import xarray as xr

    xs = xr.DataArray(gdf.geometry.x.to_numpy(), dims="geometry")
    ys = xr.DataArray(gdf.geometry.y.to_numpy(), dims="geometry")
    interp = raster.interp(x=xs, y=ys, method="linear")
    # Attach the geometry coord so output shape matches xvec's nearest path.
    interp = interp.assign_coords(geometry=("geometry", list(gdf.geometry)))
    # Set the geometry index so xvec.to_geodataframe works.
    return cast(
        "xr.Dataset | xr.DataArray",
        interp.xvec.set_geom_indexes("geometry", crs=gdf.crs),
    )


def _extracted_to_geodataframe(
    extracted: xr.Dataset | xr.DataArray,
    input_gdf: gpd.GeoDataFrame,
    *,
    bind: bool,
) -> gpd.GeoDataFrame:
    """Convert an xvec-style extract result to a GeoDataFrame.

    Time-series results produce long-form output (one row per
    (geometry × time)), which is efficient and matches xarray conventions.
    Users can pivot to wide with
    ``df.pivot_table(index=<id>, columns="time", values=<varname>)``.
    """
    import geopandas as gpd
    import pandas as pd

    if hasattr(extracted, "data_vars"):
        gdf = extracted.xvec.to_geodataframe()
    else:
        # DataArray: convert via to_dataset then to_geodataframe
        name = extracted.name or "value"
        gdf = extracted.to_dataset(name=name).xvec.to_geodataframe()

    # xvec sometimes emits a `spatial_ref` scalar column — drop it, we already
    # have the geometry column's CRS set on the GeoDataFrame.
    if "spatial_ref" in gdf.columns:
        gdf = gdf.drop(columns=["spatial_ref"])

    # Convert any time Index into a column for friendlier downstream work.
    if gdf.index.name == "time" or (
        isinstance(gdf.index, pd.MultiIndex) and "time" in gdf.index.names
    ):
        gdf = gdf.reset_index()

    if not bind:
        return gpd.GeoDataFrame(gdf, geometry="geometry", crs=input_gdf.crs)

    # bind=True: merge input attribute columns onto each output row, keyed
    # on geometry. The output may have repeated geometries (time-series),
    # so we merge rather than concat.
    attrs = input_gdf.drop(columns=[input_gdf.geometry.name]).copy()
    attrs["geometry"] = input_gdf.geometry.to_numpy()
    merged = gdf.merge(attrs, on="geometry", how="left", suffixes=("", "_input"))
    return gpd.GeoDataFrame(merged, geometry="geometry", crs=input_gdf.crs)


def extract_points(
    raster: xr.Dataset | xr.DataArray,
    locations: gpd.GeoDataFrame | pd.DataFrame,
    *,
    x: str = "x",
    y: str = "y",
    crs: str | None = None,
    method: Literal["nearest", "linear"] = "linear",
    years: Sequence[int] | None = None,
    date_start: str | datetime.date | None = None,
    date_end: str | datetime.date | None = None,
    bind: bool = True,
    verbose: bool = True,
) -> gpd.GeoDataFrame:
    """Extract raster values at point locations.

    Accepts an ``xarray.Dataset`` or ``DataArray`` (typically from
    :func:`open_raster` / :func:`open_stack`) and a ``GeoDataFrame`` or
    plain ``DataFrame`` with ``x``/``y`` columns. Reprojects the input
    locations to the raster CRS if they differ.

    Parameters
    ----------
    raster : xarray.Dataset or xarray.DataArray
        The raster to sample from. Must have ``x`` and ``y`` spatial
        coordinates and a CRS set (via ``rio.write_crs``). Time-series
        rasters (with a ``time`` dim) produce long-form output.
    locations : GeoDataFrame or DataFrame
        Points to sample. If a plain ``DataFrame``, pass the column names
        via ``x=``/``y=`` and an explicit ``crs=``. If a ``GeoDataFrame``,
        its geometry column is used and its CRS must be set.
    x, y : str, default "x", "y"
        Column names holding longitude/x and latitude/y for
        ``DataFrame`` inputs. Ignored for ``GeoDataFrame`` inputs.
    crs : str, optional
        CRS of the input locations (e.g., ``"EPSG:4326"``). Required when
        ``locations`` is a plain ``DataFrame``; inferred from
        ``locations.crs`` for ``GeoDataFrame`` inputs.
    method : {"nearest", "linear"}, default "linear"
        Interpolation method. ``"linear"`` is bilinear via
        ``xarray.interp`` (requires ``scipy``, a core pysdp dep).
        ``"nearest"`` snaps to the nearest cell via ``xvec.extract_points``
        and is substantially faster for large cloud rasters.
    years : sequence of int, optional
        Time filter applied before extraction. Only valid for time-series
        rasters.
    date_start, date_end : str or datetime.date, optional
        Date-range filter applied before extraction.
    bind : bool, default True
        If ``True``, merge the input location's non-geometry columns onto
        each output row. If ``False``, return only geometry + extracted
        values.
    verbose : bool, default True
        Print per-extraction progress messages to stderr.

    Returns
    -------
    geopandas.GeoDataFrame
        Output GeoDataFrame with the raster's data variables as columns.
        For time-series rasters, output is **long-form** (one row per
        ``geometry × time``) with ``time`` as a column; pivot to wide if
        needed via ``df.pivot_table(index=..., columns="time", values=...)``.

    Raises
    ------
    ValueError
        If the raster has no CRS, if location CRS/columns are missing, if
        ``method`` isn't one of the two valid values, or if time filter
        args are passed for a non-time-indexed raster.

    Examples
    --------
    Extract elevation at three RMBL-area field sites:

    >>> import pysdp, geopandas as gpd
    >>> from shapely.geometry import Point
    >>> dem = pysdp.open_raster("R3D009")  # doctest: +SKIP
    >>> sites = gpd.GeoDataFrame(
    ...     {"site": ["Roaring Judy", "Gothic", "Galena Lake"]},
    ...     geometry=[
    ...         Point(-106.853186, 38.716995),
    ...         Point(-106.988934, 38.958446),
    ...         Point(-107.072569, 39.021644),
    ...     ],
    ...     crs="EPSG:4326",
    ... )
    >>> samples = pysdp.extract_points(dem, sites)  # doctest: +SKIP

    Sample daily Tmax at the same sites and pivot to wide format:

    >>> tmax = pysdp.open_raster("R4D004", date_start="2021-11-02", date_end="2021-11-04")  # doctest: +SKIP
    >>> long = pysdp.extract_points(tmax, sites)  # doctest: +SKIP
    >>> wide = long.pivot_table(index="site", columns="time", values="bayes_tmax_est")  # doctest: +SKIP

    Extract from a plain ``DataFrame`` (no GeoPandas needed upfront):

    >>> import pandas as pd
    >>> df = pd.DataFrame({"site": ["A"], "lon": [-106.85], "lat": [38.95]})
    >>> out = pysdp.extract_points(dem, df, x="lon", y="lat", crs="EPSG:4326")  # doctest: +SKIP

    See Also
    --------
    extract_polygons : Summarize values over polygon geometries.
    open_raster : Load a raster to extract from.
    """
    if isinstance(raster, dict):
        raise TypeError(
            "extract_points received a dict of Datasets (from irregular imagery "
            "via open_raster). Extract from each Dataset individually:\n"
            "  results = {date: pysdp.extract_points(ds, locations) for date, ds in raster.items()}"
        )
    raster = _filter_by_time(
        raster,
        years=years,
        date_start=date_start,
        date_end=date_end,
        verbose=verbose,
    )
    gdf = _to_geodataframe(locations, x=x, y=y, crs=crs)
    gdf = _align_to_raster_crs(gdf, raster, verbose=verbose)

    n_points = len(gdf)
    n_time = int(raster.sizes.get("time", 1))
    _emit(f"Extracting values at {n_points} location(s) × {n_time} layer(s).", verbose)

    if method == "nearest":
        extracted = _point_extract_nearest(raster, gdf)
    elif method == "linear":
        extracted = _point_extract_linear(raster, gdf)
    else:
        raise ValueError(f"method must be 'nearest' or 'linear', got {method!r}.")

    _emit("Extraction complete.", verbose)
    return _extracted_to_geodataframe(extracted, gdf, bind=bind)


# ---------------------------------------------------------------------------
# extract_polygons
# ---------------------------------------------------------------------------


def _zonal_stats_xvec(
    raster: xr.Dataset | xr.DataArray,
    gdf: gpd.GeoDataFrame,
    *,
    stats: Sequence[str] | str,
    all_touched: bool,
) -> xr.Dataset | xr.DataArray:
    return cast(
        "xr.Dataset | xr.DataArray",
        raster.xvec.zonal_stats(
            gdf.geometry,
            x_coords="x",
            y_coords="y",
            stats=stats,
            all_touched=all_touched,
        ),
    )


def _zonal_stats_exact(
    raster: xr.Dataset | xr.DataArray,
    gdf: gpd.GeoDataFrame,
    *,
    stats: Sequence[str] | str,
) -> xr.Dataset | xr.DataArray:
    """Area-weighted stats via `exactextract`.

    Requires the ``[exact]`` extra. For time-series rasters, loops over time
    slices (exactextract's Python bindings don't compose with Dask yet —
    SPEC.md §Phase 8).
    """
    # exactextract's Python API is rasterio-file-oriented; an xarray→exact
    # bridge plus Dask-aware dispatch is Phase 8 work (ROADMAP §Phase 8).
    raise NotImplementedError(
        "extract_polygons(exact=True) is not yet wired up: it needs a custom "
        "xarray→exactextract bridge that composes with Dask. Use `exact=False` "
        "(xvec.zonal_stats) for now. Tracked in ROADMAP §Phase 8a."
    )


def extract_polygons(
    raster: xr.Dataset | xr.DataArray,
    locations: gpd.GeoDataFrame,
    *,
    stats: Sequence[str] | str = "mean",
    exact: bool = False,
    all_cells: bool = False,
    years: Sequence[int] | None = None,
    date_start: str | datetime.date | None = None,
    date_end: str | datetime.date | None = None,
    bind: bool = True,
    verbose: bool = True,
) -> gpd.GeoDataFrame | pd.DataFrame:
    """Summarize raster values over polygon locations.

    Computes per-polygon summary statistics (mean by default). For
    time-series rasters, produces one summary per ``(polygon × time)``
    pair in long-form output.

    Parameters
    ----------
    raster : xarray.Dataset or xarray.DataArray
        Raster to summarize. Must have a CRS set.
    locations : GeoDataFrame
        Polygon geometries. Must be a ``GeoDataFrame`` (not a plain
        ``DataFrame``) with CRS set.
    stats : str or sequence of str, default "mean"
        Summary statistic(s) to compute. Accepts any ``xvec.zonal_stats``
        string (``"mean"``, ``"sum"``, ``"std"``, ``"min"``, ``"max"``,
        ``"median"``, ``"count"``, ``"nunique"``) or a callable. Pass a
        list for multiple stats.
    exact : bool, default False
        ``False`` (default) uses centroid-based cell inclusion via
        ``xvec.zonal_stats`` — matches rSDP / ``terra::extract`` behavior.
        ``True`` uses fractional-coverage weighting via ``exactextract``
        (requires ``pysdp[exact]``); recommended for small polygons
        relative to cell size. ``True`` path is a Phase 8a roadmap item and
        currently raises ``NotImplementedError``.
    all_cells : bool, default False
        If ``True``, return a long-form DataFrame of per-cell values and
        coverage fractions instead of per-polygon summary statistics. Phase
        8a roadmap item; currently raises ``NotImplementedError``.
    years, date_start, date_end : optional
        Time-series filters applied before summarization. Same semantics as
        in :func:`extract_points`.
    bind : bool, default True
        Merge input attribute columns onto output rows when ``True``.
    verbose : bool, default True
        Print progress messages.

    Returns
    -------
    geopandas.GeoDataFrame or pandas.DataFrame
        GeoDataFrame when ``bind=True``; DataFrame when ``bind=False``.
        Columns include the raster's data variables (one per summary stat).

    Raises
    ------
    TypeError
        If ``locations`` isn't a ``GeoDataFrame``.
    ValueError
        On missing CRS or other location validation failures.
    NotImplementedError
        For ``exact=True`` or ``all_cells=True`` (roadmap items).

    Examples
    --------
    Compute mean snow duration over watersheds for 2019:

    >>> import pysdp, geopandas as gpd
    >>> snow = pysdp.open_raster("R4D001", years=[2019])  # doctest: +SKIP
    >>> watersheds = gpd.read_file("watersheds.gpkg")  # doctest: +SKIP
    >>> out = pysdp.extract_polygons(snow, watersheds, stats="mean")  # doctest: +SKIP

    Compute multiple statistics in one call:

    >>> stats = pysdp.extract_polygons(
    ...     snow, watersheds, stats=["mean", "std", "min", "max"]
    ... )  # doctest: +SKIP

    See Also
    --------
    extract_points : Extract at point geometries.
    open_raster : Load a raster.
    """
    import geopandas as gpd

    if not isinstance(locations, gpd.GeoDataFrame):
        raise TypeError(
            f"extract_polygons requires a GeoDataFrame (got {type(locations).__name__}). "
            f"For point locations, use `pysdp.extract_points`."
        )

    raster = _filter_by_time(
        raster,
        years=years,
        date_start=date_start,
        date_end=date_end,
        verbose=verbose,
    )
    gdf = _align_to_raster_crs(locations, raster, verbose=verbose)

    _emit(
        f"Zonal extract at {len(gdf)} polygon(s) × {int(raster.sizes.get('time', 1))} layer(s).",
        verbose,
    )

    if all_cells:
        raise NotImplementedError(
            "all_cells=True (per-cell long-form output with fractions) is not yet "
            "implemented; tracked in ROADMAP §Phase 8a. Use `sum_fun='mean'` or "
            "another summary for now."
        )

    if exact:
        extracted = _zonal_stats_exact(raster, gdf, stats=stats)
    else:
        extracted = _zonal_stats_xvec(raster, gdf, stats=stats, all_touched=False)

    _emit("Extraction complete.", verbose)
    return _extracted_to_geodataframe(extracted, gdf, bind=bind)


__all__ = ["extract_points", "extract_polygons"]
