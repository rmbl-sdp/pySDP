"""Tests for dataset version-control: Deprecated + NewVersionID propagation.

Mirrors rSDP's ``tests/testthat/test-internal_validate.R`` plus the new
checks added in ``tests/testthat/test-sdp_catalog_functions.R``. Covers:

- ``NewVersionID`` parsing in the catalog loader
- ``_validate_required_url_fields`` guardrail
- ``warn_if_deprecated`` semantics (with and without a replacement)
- ``get_catalog`` ``include_deprecated`` / soft-deprecated ``deprecated=``
- ``get_metadata`` / ``open_raster`` / ``get_dates`` fire the warning
- ``browse()`` renders a deprecation badge + tinted card
"""

from __future__ import annotations

import io

import pandas as pd
import pytest
import responses

import pysdp
from pysdp._catalog_data import (
    _read_catalog_csv,
    _validate_required_url_fields,
    load_packaged_catalog,
)
from pysdp._validate import warn_if_deprecated

# ---------------------------------------------------------------------------
# Catalog loader: NewVersionID and URL-field guardrail
# ---------------------------------------------------------------------------


class TestNewVersionIDParsing:
    def test_present_in_packaged_catalog(self) -> None:
        df = load_packaged_catalog(emit_warning=False)
        assert "NewVersionID" in df.columns

    def test_deprecated_rows_have_a_replacement(self) -> None:
        df = load_packaged_catalog(emit_warning=False)
        depr = df[df["Deprecated"]]
        # At least one deprecated row in the 05/15/2026 snapshot points at a
        # successor; this asserts the column is being parsed, not just present.
        assert depr["NewVersionID"].notna().any()

    def test_current_rows_have_na_new_version_id(self) -> None:
        df = load_packaged_catalog(emit_warning=False)
        current = df[~df["Deprecated"]]
        assert current["NewVersionID"].isna().all()


_MINI_HEADER = (
    "CatalogID,Release,Type,Product,Domain,Resolution,Deprecated,NewVersionID,"
    "MinDate,MaxDate,MinYear,MaxYear,TimeSeriesType,TimeSeriesRegularity,"
    "DataType,DataUnit,DataScaleFactor,DataOffset,Data.URL,Metadata.URL,"
    "ColorRampDefault\n"
)


def _csv_buffer(body: str) -> io.BytesIO:
    return io.BytesIO((_MINI_HEADER + body).encode())


class TestRequiredUrlGuardrail:
    def test_empty_data_url_raises(self) -> None:
        body = (
            "BAD001,Release1,Topo,Foo,UG,1m,FALSE,,7/16/18,7/16/18,2018,2018,"
            "Single,Regular,numeric,m,1,0,,https://example.com/foo.xml,continuous\n"
        )
        with pytest.raises(ValueError, match="Data.URL"):
            _read_catalog_csv(_csv_buffer(body))

    def test_empty_metadata_url_raises(self) -> None:
        body = (
            "BAD002,Release1,Topo,Foo,UG,1m,FALSE,,7/16/18,7/16/18,2018,2018,"
            "Single,Regular,numeric,m,1,0,https://example.com/foo.tif,,continuous\n"
        )
        with pytest.raises(ValueError, match="Metadata.URL"):
            _read_catalog_csv(_csv_buffer(body))

    def test_aggregates_multiple_missing(self) -> None:
        body = (
            "BAD003,Release1,Topo,Foo,UG,1m,FALSE,,7/16/18,7/16/18,2018,2018,"
            "Single,Regular,numeric,m,1,0,,,continuous\n"
        )
        with pytest.raises(ValueError) as exc:
            _read_catalog_csv(_csv_buffer(body))
        msg = str(exc.value)
        assert "Data.URL" in msg
        assert "Metadata.URL" in msg
        assert "BAD003" in msg

    def test_validator_on_dataframe(self) -> None:
        df = pd.DataFrame(
            {
                "CatalogID": ["X1"],
                "Data.URL": [""],
                "Metadata.URL": ["https://example.com/x.xml"],
            }
        )
        with pytest.raises(ValueError, match="Data.URL"):
            _validate_required_url_fields(df)


# ---------------------------------------------------------------------------
# warn_if_deprecated helper
# ---------------------------------------------------------------------------


class TestWarnIfDeprecated:
    def test_silent_for_current(self) -> None:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            warn_if_deprecated({"Deprecated": False, "CatalogID": "X", "NewVersionID": None})

    def test_warns_with_replacement(self) -> None:
        with pytest.warns(UserWarning, match=r"deprecated; use 'R6D007' instead"):
            warn_if_deprecated(
                {"Deprecated": True, "CatalogID": "R4D001", "NewVersionID": "R6D007"}
            )

    def test_warns_without_replacement(self) -> None:
        with pytest.warns(UserWarning, match="has no recorded replacement"):
            warn_if_deprecated({"Deprecated": True, "CatalogID": "OLD001", "NewVersionID": None})

    def test_treats_na_replacement_as_missing(self) -> None:
        with pytest.warns(UserWarning, match="has no recorded replacement"):
            warn_if_deprecated({"Deprecated": True, "CatalogID": "OLD002", "NewVersionID": pd.NA})


# ---------------------------------------------------------------------------
# get_catalog public API: include_deprecated + legacy deprecated=
# ---------------------------------------------------------------------------


class TestGetCatalogIncludeDeprecated:
    def test_default_hides_deprecated(self) -> None:
        df = pysdp.get_catalog(source="packaged")
        assert not df["Deprecated"].any()

    def test_true_includes_both(self) -> None:
        all_rows = pysdp.get_catalog(source="packaged", include_deprecated=True)
        current_only = pysdp.get_catalog(source="packaged", include_deprecated=False)
        assert len(all_rows) > len(current_only)
        assert all_rows["Deprecated"].any()
        # And every non-deprecated row from the default call is still present.
        assert set(current_only["CatalogID"]).issubset(set(all_rows["CatalogID"]))


class TestGetCatalogLegacyDeprecatedKwarg:
    def test_legacy_false_warns_and_returns_current(self) -> None:
        with pytest.warns(DeprecationWarning, match="`deprecated=` is deprecated"):
            df = pysdp.get_catalog(source="packaged", deprecated=False)
        assert not df["Deprecated"].any()

    def test_legacy_none_warns_and_returns_both(self) -> None:
        with pytest.warns(DeprecationWarning):
            df = pysdp.get_catalog(source="packaged", deprecated=None)
        assert df["Deprecated"].any()
        assert (~df["Deprecated"]).any()

    def test_legacy_true_warns_and_returns_deprecated_only(self) -> None:
        with pytest.warns(DeprecationWarning):
            df = pysdp.get_catalog(source="packaged", deprecated=True)
        assert df["Deprecated"].all()


# ---------------------------------------------------------------------------
# Deprecation warning fires at user-facing entry points
# ---------------------------------------------------------------------------


def _first_deprecated_id() -> str:
    df = load_packaged_catalog(emit_warning=False)
    depr = df[df["Deprecated"]]
    if depr.empty:
        pytest.skip("No deprecated rows in current packaged catalog")
    return str(depr.iloc[0]["CatalogID"])


class TestGetMetadataWarns:
    @responses.activate
    def test_deprecated_id_fires_warning(self) -> None:
        cat_id = _first_deprecated_id()
        df = load_packaged_catalog(emit_warning=False)
        row = df[df["CatalogID"] == cat_id].iloc[0]
        responses.add(
            responses.GET,
            row["Metadata.URL"],
            body=b"<?xml version='1.0'?><qgis/>",
            status=200,
        )
        with pytest.warns(UserWarning, match="deprecated"):
            pysdp.get_metadata(cat_id)


class TestGetDatesWarns:
    def test_deprecated_id_fires_warning(self) -> None:
        cat_id = _first_deprecated_id()
        # Even if dates resolution itself fails, the warning should fire first.
        with pytest.warns(UserWarning, match="deprecated"):
            try:
                pysdp.get_dates(cat_id)
            except Exception:  # noqa: BLE001 — we only care about the warning here
                pass


class TestOpenRasterWarns:
    def test_deprecated_id_fires_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cat_id = _first_deprecated_id()
        # Stub out the actual raster open so we don't hit S3; we only care
        # that the warning fires *before* network/IO is attempted.
        import pysdp.raster as raster_mod

        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("stubbed - should not reach open")

        monkeypatch.setattr(raster_mod, "resolve_time_slices", _boom)
        with pytest.warns(UserWarning, match="deprecated"):
            try:
                pysdp.open_raster(cat_id)
            except RuntimeError:
                pass  # expected — warning already fired


# ---------------------------------------------------------------------------
# browse(): deprecated badge + tinted card
# ---------------------------------------------------------------------------


class TestBrowseDeprecation:
    def test_default_hides_deprecated(self) -> None:
        html = str(pysdp.browse())
        # Tinted card color is unique to deprecated rows.
        assert 'bgcolor="#f0e6e6"' not in html
        assert "deprecated" not in html.lower()

    def test_include_deprecated_renders_badge_and_tint(self) -> None:
        html = str(pysdp.browse(include_deprecated=True))
        assert 'bgcolor="#f0e6e6"' in html
        # Badge text uses an arrow plus the replacement ID.
        assert "deprecated →" in html

    def test_legacy_kwarg_warns(self) -> None:
        with pytest.warns(DeprecationWarning, match="`deprecated=` is deprecated"):
            pysdp.browse(deprecated=None, max_products=1)
