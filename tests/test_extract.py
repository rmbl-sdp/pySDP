"""Unit + integration tests for `pysdp.extract` (extract_points, extract_polygons)."""

from __future__ import annotations

import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rioxarray  # noqa: F401  # registers .rio accessor
import xarray as xr
import xvec  # noqa: F401  # registers .xvec accessor
from shapely.geometry import Point, Polygon

import pysdp
from pysdp.constants import SDP_CRS
from pysdp.extract import (
    _align_to_raster_crs,
    _filter_by_time,
    _to_geodataframe,
)

# ---------------------------------------------------------------------------
# Synthetic raster fixtures
# ---------------------------------------------------------------------------


def _make_single_layer(value_start: float = 0.0, *, nrows: int = 8, ncols: int = 8) -> xr.Dataset:
    """Tiny single-layer Dataset in EPSG:32613, 250 m cells."""
    x = np.arange(326125.0, 326125.0 + 250.0 * ncols, 250.0)  # cell centers
    y = np.arange(4311875.0, 4311875.0 - 250.0 * nrows, -250.0)
    data = np.arange(nrows * ncols, dtype="float32").reshape(nrows, ncols) + value_start
    da = xr.DataArray(data, dims=("y", "x"), coords={"x": x, "y": y}).rio.write_crs(SDP_CRS)
    return da.to_dataset(name="elev")


def _make_time_series(n_times: int = 3, *, nrows: int = 8, ncols: int = 8) -> xr.Dataset:
    """Tiny 3-layer time-series Dataset with Daily DatetimeIndex."""
    base = _make_single_layer(nrows=nrows, ncols=ncols)["elev"]
    times = pd.date_range("2003-01-01", periods=n_times)
    arrays = [base + float(i) for i in range(n_times)]
    combined = xr.concat(arrays, dim=pd.Index(times, name="time"))
    return combined.to_dataset(name="tmax").rio.write_crs(SDP_CRS)


@pytest.fixture
def single_raster() -> xr.Dataset:
    return _make_single_layer()


@pytest.fixture
def daily_raster() -> xr.Dataset:
    return _make_time_series(n_times=3)


@pytest.fixture
def points_utm() -> gpd.GeoDataFrame:
    """3 points inside the synthetic raster extent, in EPSG:32613."""
    return gpd.GeoDataFrame(
        {"site": ["A", "B", "C"]},
        geometry=[
            Point(326250.0, 4311750.0),
            Point(326875.0, 4311000.0),
            Point(327500.0, 4310250.0),
        ],
        crs=SDP_CRS,
    )


@pytest.fixture
def polygons_utm() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"plot": ["P1", "P2"]},
        geometry=[
            Polygon([(326100, 4311900), (326700, 4311900), (326700, 4311400), (326100, 4311400)]),
            Polygon([(327100, 4310900), (327700, 4310900), (327700, 4310400), (327100, 4310400)]),
        ],
        crs=SDP_CRS,
    )


# ---------------------------------------------------------------------------
# _filter_by_time
# ---------------------------------------------------------------------------


class TestFilterByTime:
    def test_no_args_returns_raster_unchanged(self, single_raster: xr.Dataset) -> None:
        out = _filter_by_time(
            single_raster, years=None, date_start=None, date_end=None, verbose=False
        )
        assert out is single_raster

    def test_years_filter(self, daily_raster: xr.Dataset) -> None:
        # daily_raster has 2003-01-01, 02, 03 — all year 2003. Filter by 2003.
        out = _filter_by_time(
            daily_raster, years=[2003], date_start=None, date_end=None, verbose=False
        )
        assert out.sizes["time"] == 3

    def test_years_error_on_empty_match(self, daily_raster: xr.Dataset) -> None:
        with pytest.raises(ValueError, match="No raster layers match any of years"):
            _filter_by_time(
                daily_raster, years=[1999], date_start=None, date_end=None, verbose=False
            )

    def test_date_range_filter(self, daily_raster: xr.Dataset) -> None:
        out = _filter_by_time(
            daily_raster,
            years=None,
            date_start="2003-01-01",
            date_end="2003-01-02",
            verbose=False,
        )
        assert out.sizes["time"] == 2

    def test_date_range_error_on_empty(self, daily_raster: xr.Dataset) -> None:
        with pytest.raises(ValueError, match="No raster layers match"):
            _filter_by_time(
                daily_raster,
                years=None,
                date_start="1999-01-01",
                date_end="1999-12-31",
                verbose=False,
            )

    def test_error_when_raster_has_no_time_but_years_given(self, single_raster: xr.Dataset) -> None:
        with pytest.raises(ValueError, match="require a time-indexed raster"):
            _filter_by_time(
                single_raster, years=[2003], date_start=None, date_end=None, verbose=False
            )


# ---------------------------------------------------------------------------
# _to_geodataframe
# ---------------------------------------------------------------------------


class TestToGeoDataFrame:
    def test_geodataframe_passthrough(self, points_utm: gpd.GeoDataFrame) -> None:
        out = _to_geodataframe(points_utm, x="x", y="y", crs=None)
        assert out is points_utm

    def test_geodataframe_without_crs_errors(self) -> None:
        gdf = gpd.GeoDataFrame(geometry=[Point(0, 0)], crs=None)
        with pytest.raises(ValueError, match="without a CRS"):
            _to_geodataframe(gdf, x="x", y="y", crs=None)

    def test_dataframe_with_xy_and_crs(self) -> None:
        df = pd.DataFrame({"site": ["A", "B"], "lon": [-106.9, -106.8], "lat": [38.9, 38.8]})
        out = _to_geodataframe(df, x="lon", y="lat", crs="EPSG:4326")
        assert isinstance(out, gpd.GeoDataFrame)
        assert str(out.crs) == "EPSG:4326"
        assert len(out) == 2

    def test_dataframe_without_crs_errors(self) -> None:
        df = pd.DataFrame({"x": [0.0], "y": [0.0]})
        with pytest.raises(ValueError, match="`crs` is required"):
            _to_geodataframe(df, x="x", y="y", crs=None)

    def test_dataframe_missing_columns_errors(self) -> None:
        df = pd.DataFrame({"lon": [0.0]})
        with pytest.raises(ValueError, match="missing column"):
            _to_geodataframe(df, x="lon", y="lat", crs="EPSG:4326")

    def test_non_dataframe_input_errors(self) -> None:
        with pytest.raises(TypeError, match="must be a GeoDataFrame"):
            _to_geodataframe([1, 2, 3], x="x", y="y", crs="EPSG:4326")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _align_to_raster_crs
# ---------------------------------------------------------------------------


class TestAlignToRasterCrs:
    def test_passthrough_when_crs_matches(
        self, single_raster: xr.Dataset, points_utm: gpd.GeoDataFrame
    ) -> None:
        out = _align_to_raster_crs(points_utm, single_raster, verbose=False)
        assert out is points_utm

    def test_reprojects_when_crs_differs(self, single_raster: xr.Dataset) -> None:
        # Create points in WGS84 and ensure they get reprojected to EPSG:32613.
        pts = gpd.GeoDataFrame(geometry=[Point(-106.85, 38.95)], crs="EPSG:4326")
        out = _align_to_raster_crs(pts, single_raster, verbose=False)
        assert out.crs.to_epsg() == 32613


# ---------------------------------------------------------------------------
# extract_points (synthetic raster)
# ---------------------------------------------------------------------------


class TestExtractPoints:
    def test_single_layer_returns_geodataframe(
        self, single_raster: xr.Dataset, points_utm: gpd.GeoDataFrame
    ) -> None:
        out = pysdp.extract_points(single_raster, points_utm, verbose=False)
        assert isinstance(out, gpd.GeoDataFrame)
        assert len(out) == 3
        assert "elev" in out.columns

    def test_bind_true_attaches_input_columns(
        self, single_raster: xr.Dataset, points_utm: gpd.GeoDataFrame
    ) -> None:
        out = pysdp.extract_points(single_raster, points_utm, bind=True, verbose=False)
        assert "site" in out.columns
        assert sorted(out["site"].tolist()) == ["A", "B", "C"]

    def test_bind_false_omits_input_columns(
        self, single_raster: xr.Dataset, points_utm: gpd.GeoDataFrame
    ) -> None:
        out = pysdp.extract_points(single_raster, points_utm, bind=False, verbose=False)
        assert "site" not in out.columns

    def test_method_nearest(self, single_raster: xr.Dataset, points_utm: gpd.GeoDataFrame) -> None:
        out = pysdp.extract_points(single_raster, points_utm, method="nearest", verbose=False)
        assert isinstance(out, gpd.GeoDataFrame)

    def test_time_series_long_format(
        self, daily_raster: xr.Dataset, points_utm: gpd.GeoDataFrame
    ) -> None:
        out = pysdp.extract_points(daily_raster, points_utm, verbose=False)
        # 3 points × 3 time slices = 9 rows
        assert len(out) == 9
        assert "time" in out.columns
        assert "tmax" in out.columns

    def test_reprojects_from_wgs84(self, single_raster: xr.Dataset) -> None:
        pts = gpd.GeoDataFrame(
            {"site": ["G"]},
            geometry=[Point(-106.85, 38.95)],
            crs="EPSG:4326",
        )
        out = pysdp.extract_points(single_raster, pts, verbose=False)
        assert isinstance(out, gpd.GeoDataFrame)

    def test_dataframe_input_with_lon_lat(self, single_raster: xr.Dataset) -> None:
        # Build a plain DataFrame in UTM coords (same CRS as raster).
        df = pd.DataFrame({"site": ["X"], "easting": [326250.0], "northing": [4311750.0]})
        out = pysdp.extract_points(
            single_raster, df, x="easting", y="northing", crs=SDP_CRS, verbose=False
        )
        assert isinstance(out, gpd.GeoDataFrame)

    def test_invalid_method_errors(
        self, single_raster: xr.Dataset, points_utm: gpd.GeoDataFrame
    ) -> None:
        with pytest.raises(ValueError, match="method must be"):
            pysdp.extract_points(
                single_raster,
                points_utm,
                method="bogus",
                verbose=False,  # type: ignore[arg-type]
            )

    def test_years_on_non_time_raster_errors(
        self, single_raster: xr.Dataset, points_utm: gpd.GeoDataFrame
    ) -> None:
        with pytest.raises(ValueError, match="require a time-indexed raster"):
            pysdp.extract_points(single_raster, points_utm, years=[2003], verbose=False)


# ---------------------------------------------------------------------------
# extract_polygons (synthetic raster)
# ---------------------------------------------------------------------------


class TestExtractPolygons:
    def test_mean_on_single_layer(
        self, single_raster: xr.Dataset, polygons_utm: gpd.GeoDataFrame
    ) -> None:
        out = pysdp.extract_polygons(single_raster, polygons_utm, stats="mean", verbose=False)
        assert isinstance(out, gpd.GeoDataFrame)
        assert len(out) == 2
        assert "elev" in out.columns

    def test_bind_true_attaches_input_columns(
        self, single_raster: xr.Dataset, polygons_utm: gpd.GeoDataFrame
    ) -> None:
        out = pysdp.extract_polygons(
            single_raster, polygons_utm, stats="mean", bind=True, verbose=False
        )
        assert "plot" in out.columns
        assert sorted(out["plot"].tolist()) == ["P1", "P2"]

    def test_rejects_non_geodataframe(self, single_raster: xr.Dataset) -> None:
        df = pd.DataFrame({"x": [0], "y": [0]})
        with pytest.raises(TypeError, match="requires a GeoDataFrame"):
            pysdp.extract_polygons(single_raster, df, verbose=False)  # type: ignore[arg-type]

    def test_exact_true_not_yet_implemented(
        self, single_raster: xr.Dataset, polygons_utm: gpd.GeoDataFrame
    ) -> None:
        with pytest.raises(NotImplementedError, match="exact=True"):
            pysdp.extract_polygons(single_raster, polygons_utm, exact=True, verbose=False)

    def test_all_cells_not_yet_implemented(
        self, single_raster: xr.Dataset, polygons_utm: gpd.GeoDataFrame
    ) -> None:
        with pytest.raises(NotImplementedError, match="all_cells=True"):
            pysdp.extract_polygons(single_raster, polygons_utm, all_cells=True, verbose=False)

    def test_time_series_zonal(
        self, daily_raster: xr.Dataset, polygons_utm: gpd.GeoDataFrame
    ) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            out = pysdp.extract_polygons(daily_raster, polygons_utm, stats="mean", verbose=False)
        # 2 polygons × 3 time slices = 6 rows (long format)
        assert len(out) == 6


# ---------------------------------------------------------------------------
# Network-gated integration tests
# ---------------------------------------------------------------------------


@pytest.mark.network
class TestNetwork:
    def test_extract_points_from_real_dem(self) -> None:
        """Extract elevation at three real field sites from the UG 3m DEM."""
        dem = pysdp.open_raster("R3D009", verbose=False)  # UG 3m DEM
        sites = gpd.GeoDataFrame(
            {"site": ["Roaring Judy", "Gothic", "Galena Lake"]},
            geometry=[
                Point(-106.853186, 38.716995),
                Point(-106.988934, 38.958446),
                Point(-107.072569, 39.021644),
            ],
            crs="EPSG:4326",
        )
        out = pysdp.extract_points(dem, sites, verbose=False)
        assert len(out) == 3
        elev_col = [c for c in out.columns if "dem" in c.lower() or "elev" in c.lower()]
        assert elev_col, f"no elevation column found in {list(out.columns)}"
        elevations = out[elev_col[0]].dropna()
        # All three sites should be 2000-4000 m in the Gunnison area.
        assert (elevations > 2000).all()
        assert (elevations < 4500).all()
