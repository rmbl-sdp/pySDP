"""Unit + integration tests for `pysdp.raster` (open_raster, open_stack).

Unit tests use synthetic local COGs generated with rasterio so they never
touch the network; network integration tests against real S3 are gated by
`@pytest.mark.network` per SPEC §9 Phase 3.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
import xarray as xr
from rasterio.transform import from_bounds

import pysdp
from pysdp.constants import SDP_CRS
from pysdp.io.vsicurl import ensure_gdal_defaults, gdal_defaults
from pysdp.raster import (
    _canonical_variable_name,
    _resolve_chunks,
    _time_coord,
    _verify_exact_alignment,
)

# ---------------------------------------------------------------------------
# Fixtures: tiny synthetic COGs on local disk
# ---------------------------------------------------------------------------


def _write_cog(
    path: Path,
    *,
    nrows: int = 16,
    ncols: int = 16,
    bounds: tuple[float, float, float, float] = (326000.0, 4310000.0, 328000.0, 4312000.0),
    value: float = 1.0,
    crs: str = SDP_CRS,
) -> None:
    """Write a tiny single-band COG to `path` for unit tests.

    Uses 16×16 blocks to satisfy TIFF's multiple-of-16 block-size constraint.
    """
    transform = from_bounds(*bounds, width=ncols, height=nrows)
    data = np.full((nrows, ncols), value, dtype=np.float32)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=nrows,
        width=ncols,
        count=1,
        dtype=data.dtype,
        crs=crs,
        transform=transform,
        tiled=True,
        blockxsize=16,
        blockysize=16,
    ) as dst:
        dst.write(data, 1)


@pytest.fixture
def single_cog(tmp_path: Path) -> Path:
    p = tmp_path / "UER_streams_512k_mfd_1m_v2.tif"
    _write_cog(p, value=42.0)
    return p


@pytest.fixture
def daily_cogs(tmp_path: Path) -> tuple[list[Path], list[str]]:
    """Three tiny COGs that form a 3-layer daily time-series."""
    paths = []
    for i, day in enumerate(["001", "002", "003"]):
        p = tmp_path / f"bayes_tmax_year_2003_day_0{day}_est.tif"
        _write_cog(p, value=float(i))
        paths.append(p)
    names = ["2003-01-01", "2003-01-02", "2003-01-03"]
    return paths, names


# ---------------------------------------------------------------------------
# _canonical_variable_name
# ---------------------------------------------------------------------------


class TestCanonicalVariableName:
    def test_single_layer_clean(self) -> None:
        name = _canonical_variable_name(
            "https://rmbl-sdp/.../UER_streams_512k_mfd_1m_v2.tif", "R1D001"
        )
        assert name == "UER_streams_512k_mfd_1m_v2"

    def test_yearly_strips_year_placeholder(self) -> None:
        name = _canonical_variable_name(
            "https://rmbl-sdp/.../UG_snow_persistence_year_{year}_27m_v1.tif", "R4D001"
        )
        assert name == "UG_snow_persistence_27m_v1"

    def test_monthly_strips_year_and_month(self) -> None:
        name = _canonical_variable_name(
            "https://rmbl-sdp/.../UG_airtemp_tavg_mean_year_{year}_month_{month}_81m_v1.tif",
            "R4D006",
        )
        assert name == "UG_airtemp_tavg_mean_81m_v1"

    def test_daily_strips_year_and_day_with_zero_prefix(self) -> None:
        """Real SDP template has `_day_0{day}` — the literal 0 prefix must be stripped."""
        name = _canonical_variable_name(
            "https://rmbl-sdp/.../bayes_tmax_year_{year}_day_0{day}_est.tif", "R4D004"
        )
        assert name == "bayes_tmax_est"

    def test_bare_placeholder_without_label(self) -> None:
        name = _canonical_variable_name("https://test.example/{year}_{day}.tif", "FAKE01")
        # All placeholders stripped; result is empty → fallback to catalog_id.
        assert name == "FAKE01"

    def test_all_placeholders_no_content_falls_back_to_catalog_id(self) -> None:
        name = _canonical_variable_name("{year}.tif", "R4D001")
        assert name == "R4D001"


class TestCanonicalNamesAgainstRealCatalog:
    """Verify canonical-name generation against the packaged catalog."""

    def test_no_empty_names_and_no_braces_leak(self) -> None:
        df = pysdp.get_catalog(deprecated=None)
        for _, row in df.iterrows():
            name = _canonical_variable_name(str(row["Data.URL"]), str(row["CatalogID"]))
            assert name, f"empty name for {row['CatalogID']}"
            assert "{" not in name, f"placeholder leaked in {row['CatalogID']}: {name}"
            assert "}" not in name


# ---------------------------------------------------------------------------
# _time_coord
# ---------------------------------------------------------------------------


class TestTimeCoord:
    def test_daily(self) -> None:
        out = _time_coord(["2003-01-05", "2003-01-06"], "Daily")
        assert list(out) == [pd.Timestamp("2003-01-05"), pd.Timestamp("2003-01-06")]

    def test_monthly_uses_first_of_month(self) -> None:
        out = _time_coord(["2003-06", "2003-07"], "Monthly")
        assert list(out) == [pd.Timestamp("2003-06-01"), pd.Timestamp("2003-07-01")]

    def test_yearly_uses_january_first(self) -> None:
        out = _time_coord(["2003", "2004", "2005"], "Yearly")
        assert list(out) == [
            pd.Timestamp("2003-01-01"),
            pd.Timestamp("2004-01-01"),
            pd.Timestamp("2005-01-01"),
        ]

    def test_rejects_single(self) -> None:
        with pytest.raises(ValueError, match="Unsupported TimeSeriesType"):
            _time_coord(["whatever"], "Single")


# ---------------------------------------------------------------------------
# _resolve_chunks
# ---------------------------------------------------------------------------


class TestResolveChunks:
    def test_none_passthrough(self) -> None:
        assert _resolve_chunks(None) is None

    def test_dict_passthrough(self) -> None:
        assert _resolve_chunks({"x": 512, "y": 512}) == {"x": 512, "y": 512}

    def test_auto_when_dask_available(self) -> None:
        pytest.importorskip("dask")
        assert _resolve_chunks("auto") == "auto"

    def test_auto_falls_back_to_none_without_dask(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        # Simulate dask not installed by hiding it from import system.
        monkeypatch.setitem(sys.modules, "dask", None)
        with pytest.warns(UserWarning, match="chunks='auto' requires dask"):
            assert _resolve_chunks("auto") is None


# ---------------------------------------------------------------------------
# ensure_gdal_defaults
# ---------------------------------------------------------------------------


class TestEnsureGdalDefaults:
    def test_sets_missing_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for k in gdal_defaults():
            monkeypatch.delenv(k, raising=False)
        ensure_gdal_defaults()
        for k, v in gdal_defaults().items():
            assert os.environ[k] == v

    def test_preserves_user_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GDAL_DISABLE_READDIR_ON_OPEN", "NO")
        ensure_gdal_defaults()
        assert os.environ["GDAL_DISABLE_READDIR_ON_OPEN"] == "NO"


# ---------------------------------------------------------------------------
# open_raster — synthetic-COG unit tests
# ---------------------------------------------------------------------------


class TestOpenRasterSingle:
    def test_returns_dataset_with_canonical_var(self, single_cog: Path) -> None:
        # Bypass VSICURL by using file:// path; pass url= to avoid catalog lookup.
        # rioxarray handles local paths directly, and our url= branch only
        # validates `https://`. We need a different path here.
        #
        # Strategy: call the private helper `_build_dataset` directly with a
        # synthetic slices object so we can point at a local file.
        from pysdp._resolve import TimeSlices
        from pysdp.raster import _build_dataset

        slices = TimeSlices(paths=[str(single_cog)], names=[])
        cat_line = {
            "CatalogID": "R1D001",
            "Data.URL": "https://x/UER_streams_512k_mfd_1m_v2.tif",
            "TimeSeriesType": "Single",
            "DataScaleFactor": 1.0,
            "DataOffset": 0.0,
        }
        ds = _build_dataset(slices, cat_line=cat_line, url=None, chunks=None)

        assert isinstance(ds, xr.Dataset)
        assert "UER_streams_512k_mfd_1m_v2" in ds.data_vars
        var = ds["UER_streams_512k_mfd_1m_v2"]
        assert var.dims == ("y", "x")
        assert ds.rio.crs.to_string().endswith("32613")

    def test_scale_offset_attrs_set(self, single_cog: Path) -> None:
        from pysdp._resolve import TimeSlices
        from pysdp.raster import _build_dataset

        slices = TimeSlices(paths=[str(single_cog)], names=[])
        cat_line = {
            "CatalogID": "R4D001",
            "Data.URL": "https://x/UG_snow_persistence_year_{year}_27m_v1.tif",
            "TimeSeriesType": "Single",
            "DataScaleFactor": 100.0,
            "DataOffset": 0.0,
        }
        ds = _build_dataset(slices, cat_line=cat_line, url=None, chunks=None)
        var = ds["UG_snow_persistence_27m_v1"]
        # rSDP convention: DataScaleFactor is "divide by this"; CF is multiply.
        assert var.attrs["scale_factor"] == pytest.approx(0.01)
        assert var.attrs["add_offset"] == 0.0


class TestOpenRasterTimeSeries:
    def test_daily_concats_on_time_dim(self, daily_cogs: tuple[list[Path], list[str]]) -> None:
        from pysdp._resolve import TimeSlices
        from pysdp.raster import _build_dataset

        paths, names = daily_cogs
        slices = TimeSlices(paths=[str(p) for p in paths], names=names)
        cat_line = {
            "CatalogID": "R4D004",
            "Data.URL": "https://x/bayes_tmax_year_{year}_day_0{day}_est.tif",
            "TimeSeriesType": "Daily",
            "DataScaleFactor": 1.0,
            "DataOffset": 0.0,
        }
        ds = _build_dataset(slices, cat_line=cat_line, url=None, chunks=None)

        assert "bayes_tmax_est" in ds.data_vars
        var = ds["bayes_tmax_est"]
        assert var.dims == ("time", "y", "x")
        assert var.sizes["time"] == 3
        assert list(ds.coords["time"].values) == [
            np.datetime64("2003-01-01"),
            np.datetime64("2003-01-02"),
            np.datetime64("2003-01-03"),
        ]


# ---------------------------------------------------------------------------
# open_raster: public-entry-point validation tests
# ---------------------------------------------------------------------------


class TestOpenRasterValidation:
    def test_download_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="Phase 5"):
            pysdp.open_raster("R1D001", download=True, download_path="/tmp")

    def test_url_must_start_with_https(self) -> None:
        with pytest.raises(ValueError, match="https://"):
            pysdp.open_raster(url="ftp://nope/x.tif")

    def test_rejects_both_catalog_id_and_url(self) -> None:
        with pytest.raises(ValueError, match="either catalog_id or url"):
            pysdp.open_raster("R1D001", url="https://x/y.tif")

    def test_rejects_neither(self) -> None:
        with pytest.raises(ValueError, match="must specify either catalog_id or url"):
            pysdp.open_raster()

    def test_unknown_catalog_id_raises_with_snapshot_date(self) -> None:
        with pytest.raises(KeyError, match="not found in packaged catalog"):
            pysdp.open_raster("ZZZZZZ")


# ---------------------------------------------------------------------------
# open_stack
# ---------------------------------------------------------------------------


class TestOpenStackValidation:
    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty sequence"):
            pysdp.open_stack([])

    def test_reproject_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="Phase 7"):
            pysdp.open_stack(["R1D001"], align="reproject")

    def test_bad_align_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown align"):
            pysdp.open_stack(["R1D001"], align="sideways")  # type: ignore[arg-type]


class TestVerifyExactAlignment:
    def _make_ds(
        self,
        value: float,
        *,
        shape: tuple[int, int] = (10, 10),
    ) -> xr.Dataset:
        ny, nx = shape
        bounds = (0.0, 0.0, float(nx), float(ny))
        transform = from_bounds(*bounds, width=nx, height=ny)
        data = np.full((ny, nx), value, dtype=np.float32)
        da = xr.DataArray(
            data,
            dims=("y", "x"),
            coords={
                "x": np.linspace(bounds[0] + 0.5, bounds[2] - 0.5, nx),
                "y": np.linspace(bounds[3] - 0.5, bounds[1] + 0.5, ny),
            },
        )
        ds = da.to_dataset(name="v")
        ds.rio.write_crs(SDP_CRS, inplace=True)
        ds.rio.write_transform(transform, inplace=True)
        return ds

    def test_matching_grids_pass(self) -> None:
        a = self._make_ds(1.0)
        b = self._make_ds(2.0)
        _verify_exact_alignment([a, b], catalog_ids=["A", "B"])  # no exception

    def test_shape_mismatch_raises(self) -> None:
        a = self._make_ds(1.0, shape=(10, 10))
        b = self._make_ds(2.0, shape=(20, 20))
        with pytest.raises(ValueError, match="share grid"):
            _verify_exact_alignment([a, b], catalog_ids=["A", "B"])


# ---------------------------------------------------------------------------
# Network-gated integration tests
# ---------------------------------------------------------------------------


@pytest.mark.network
class TestNetwork:
    def test_open_single(self) -> None:
        ds = pysdp.open_raster("R1D001", verbose=False)
        assert isinstance(ds, xr.Dataset)
        var_name = next(iter(ds.data_vars))
        assert var_name.startswith("UER_streams")
        assert ds.rio.crs.to_string().endswith("32613")

    def test_open_daily_date_range(self) -> None:
        ds = pysdp.open_raster(
            "R4D004",
            date_start="2021-11-02",
            date_end="2021-11-04",
            verbose=False,
        )
        assert "time" in ds.dims
        assert ds.sizes["time"] == 3
        var = next(iter(ds.data_vars.values()))
        assert var.dims == ("time", "y", "x")

    def test_open_url_direct(self) -> None:
        """url= branch: load a known Single SDP COG directly, no catalog lookup."""
        df = pysdp.get_catalog(deprecated=None)
        row = df[df["TimeSeriesType"] == "Single"].iloc[0]
        ds = pysdp.open_raster(url=row["Data.URL"], verbose=False)
        assert isinstance(ds, xr.Dataset)
        assert ds.rio.crs.to_string().endswith("32613")
        # Variable name is derived from URL basename, not CatalogID.
        var_name = next(iter(ds.data_vars))
        assert var_name in row["Data.URL"]
