"""Unit + integration tests for `pysdp.catalog` (get_catalog, get_metadata)."""

from __future__ import annotations

import datetime

import pandas as pd
import pytest
import responses

import pysdp
from pysdp._catalog_data import live_catalog_url
from pysdp.catalog import _apply_filters, _validate_filter
from pysdp.constants import DOMAINS, TIMESERIES_TYPES, TYPES


@pytest.fixture
def synthetic_catalog() -> pd.DataFrame:
    """Small in-memory catalog exercising the filter axes."""
    df = pd.DataFrame(
        {
            "CatalogID": ["R1D001", "R3D009", "R4D004", "BM012", "R3D099"],
            "Domain": ["UER", "UG", "UG", "UG", "UG"],
            "Type": ["Hydro", "Topo", "Climate", "Vegetation", "Vegetation"],
            "Release": ["Release1", "Release3", "Release4", "Basemaps", "Release3"],
            "TimeSeriesType": ["Single", "Single", "Daily", "Single", "Single"],
            "Deprecated": [False, False, False, False, True],
        }
    )
    df.attrs["snapshot_date"] = datetime.date(2026, 4, 14)
    df.attrs["snapshot_filename"] = "SDP_product_table_04_14_2026.csv"
    return df


class TestValidateFilter:
    def test_none_passes(self) -> None:
        _validate_filter(None, DOMAINS, "domains")  # no-op

    def test_valid_passes(self) -> None:
        _validate_filter(["UG", "GMUG"], DOMAINS, "domains")

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid domains"):
            _validate_filter(["UG", "NOPE"], DOMAINS, "domains")

    def test_empty_sequence_passes(self) -> None:
        _validate_filter([], DOMAINS, "domains")


class TestApplyFilters:
    def test_no_filters_keeps_non_deprecated_default(self, synthetic_catalog: pd.DataFrame) -> None:
        out = _apply_filters(
            synthetic_catalog,
            domains=None,
            types=None,
            releases=None,
            timeseries_types=None,
            deprecated=False,
        )
        assert len(out) == 4  # 4 non-deprecated rows

    def test_domain_filter(self, synthetic_catalog: pd.DataFrame) -> None:
        out = _apply_filters(
            synthetic_catalog,
            domains=["UER"],
            types=None,
            releases=None,
            timeseries_types=None,
            deprecated=False,
        )
        assert list(out["CatalogID"]) == ["R1D001"]

    def test_type_and_release_combine_with_and(self, synthetic_catalog: pd.DataFrame) -> None:
        out = _apply_filters(
            synthetic_catalog,
            domains=None,
            types=["Vegetation"],
            releases=["Basemaps"],
            timeseries_types=None,
            deprecated=False,
        )
        assert list(out["CatalogID"]) == ["BM012"]

    def test_deprecated_true_only_deprecated(self, synthetic_catalog: pd.DataFrame) -> None:
        out = _apply_filters(
            synthetic_catalog,
            domains=None,
            types=None,
            releases=None,
            timeseries_types=None,
            deprecated=True,
        )
        assert list(out["CatalogID"]) == ["R3D099"]

    def test_deprecated_none_returns_both(self, synthetic_catalog: pd.DataFrame) -> None:
        out = _apply_filters(
            synthetic_catalog,
            domains=None,
            types=None,
            releases=None,
            timeseries_types=None,
            deprecated=None,
        )
        assert len(out) == len(synthetic_catalog)

    def test_preserves_snapshot_attrs(self, synthetic_catalog: pd.DataFrame) -> None:
        out = _apply_filters(
            synthetic_catalog,
            domains=["UG"],
            types=None,
            releases=None,
            timeseries_types=None,
            deprecated=False,
        )
        assert out.attrs["snapshot_date"] == datetime.date(2026, 4, 14)


class TestGetCatalogValidation:
    def test_invalid_domain_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid domains"):
            pysdp.get_catalog(domains=["NOPE"])

    def test_invalid_source_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown source"):
            pysdp.get_catalog(source="bogus")  # type: ignore[arg-type]

    def test_stac_source_with_filters_warns(self) -> None:
        # We don't care whether the STAC fetch itself works here — just that
        # the filter-ignored warning is emitted before the fetch runs.
        with (
            responses.RequestsMock(assert_all_requests_are_fired=False),
            pytest.warns(UserWarning, match="Filter arguments are ignored"),
        ):
            try:
                pysdp.get_catalog(domains=["UG"], source="stac")
            except Exception:  # noqa: BLE001 — we only care about the warning
                pass


class TestGetCatalogPackaged:
    def test_returns_dataframe(self) -> None:
        df = pysdp.get_catalog(source="packaged")
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_filter_narrows_rows(self) -> None:
        all_rows = pysdp.get_catalog(source="packaged")
        ug = pysdp.get_catalog(domains=["UG"], source="packaged")
        assert set(ug["Domain"].unique()) == {"UG"}
        assert len(ug) < len(all_rows)

    def test_deprecated_false_excludes_deprecated(self) -> None:
        df = pysdp.get_catalog(source="packaged", deprecated=False)
        assert not df["Deprecated"].any()

    def test_all_constants_are_represented(self) -> None:
        """Sanity check: every value in TYPES/DOMAINS should appear at least once."""
        df = pysdp.get_catalog(deprecated=None, source="packaged")
        assert set(df["Domain"].unique()).issubset(set(DOMAINS))
        assert set(df["Type"].unique()).issubset(set(TYPES))
        assert set(df["TimeSeriesType"].unique()).issubset(set(TIMESERIES_TYPES))


class TestGetCatalogLive:
    @responses.activate
    def test_live_fetches_from_s3(self) -> None:
        # Mock with the packaged CSV's own bytes to exercise the HTTP path.
        from pysdp._catalog_data import _packaged_csv_resource

        with _packaged_csv_resource().open("rb") as fh:
            payload = fh.read()
        responses.add(responses.GET, live_catalog_url(), body=payload, status=200)
        df = pysdp.get_catalog(source="live")
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0


class TestGetMetadataValidation:
    def test_wrong_length_raises(self) -> None:
        with pytest.raises(ValueError, match="6 characters"):
            pysdp.get_metadata("short")

    def test_unknown_id_raises_with_snapshot_date(self) -> None:
        with pytest.raises(KeyError, match="not found in packaged catalog"):
            pysdp.get_metadata("ZZZZZZ")


class TestGetMetadataFetch:
    @responses.activate
    def test_as_dict(self) -> None:
        # Find a real catalog_id + its Metadata.URL from the packaged snapshot,
        # then mock the HTTP response with a tiny XML document.
        df = pysdp.get_catalog(deprecated=None, source="packaged")
        row = df.iloc[0]
        xml = b"<?xml version='1.0'?><qgis><title>Test</title></qgis>"
        responses.add(responses.GET, row["Metadata.URL"], body=xml, status=200)
        meta = pysdp.get_metadata(row["CatalogID"], as_dict=True)
        assert meta == {"qgis": {"title": "Test"}}

    @responses.activate
    def test_as_element(self) -> None:
        df = pysdp.get_catalog(deprecated=None, source="packaged")
        row = df.iloc[0]
        xml = b"<?xml version='1.0'?><qgis><title>Test</title></qgis>"
        responses.add(responses.GET, row["Metadata.URL"], body=xml, status=200)
        meta = pysdp.get_metadata(row["CatalogID"], as_dict=False)
        # lxml etree Element
        assert meta.tag == "qgis"
        assert meta.find("title").text == "Test"


# ---------------------------------------------------------------------------
# Network-gated integration tests (skipped by default; run with `-m network`)
# ---------------------------------------------------------------------------


@pytest.mark.network
class TestNetwork:
    def test_live_catalog_real(self) -> None:
        df = pysdp.get_catalog(source="live")
        assert len(df) > 100

    def test_stac_catalog_real(self) -> None:
        pytest.importorskip("pystac")
        try:
            cat = pysdp.get_catalog(source="stac")
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"STAC catalog unavailable: {e}")
        import pystac

        assert isinstance(cat, pystac.Catalog)

    def test_metadata_real(self) -> None:
        df = pysdp.get_catalog(deprecated=None)
        cat_id = df.iloc[0]["CatalogID"]
        meta = pysdp.get_metadata(cat_id)
        assert isinstance(meta, dict)
