"""Point and polygon extraction.

Corresponds to rSDP's `sdp_extract_data()`, split into two functions
for clarity. Implementation lands in Phase 4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import datetime
    from collections.abc import Sequence

    import geopandas as gpd
    import pandas as pd
    import xarray as xr


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

    See SPEC.md §4.3.
    """
    raise NotImplementedError("Phase 4: point extraction")


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

    See SPEC.md §4.3.
    """
    raise NotImplementedError("Phase 4: polygon extraction")
