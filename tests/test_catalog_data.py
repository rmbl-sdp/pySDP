"""Unit tests for `pysdp._catalog_data` (packaged-CSV loading, date parsing, staleness)."""

from __future__ import annotations

import datetime
import warnings

import pandas as pd
import pytest

from pysdp._catalog_data import (
    STALENESS_MONTHS_DEFAULT,
    STALENESS_MONTHS_ENV,
    _emit_staleness_warning_if_needed,
    _parse_sdp_dates,
    _staleness_months_threshold,
    load_packaged_catalog,
    snapshot_date,
)


class TestSnapshotDate:
    def test_parses_valid_filename(self) -> None:
        assert snapshot_date("SDP_product_table_04_14_2026.csv") == datetime.date(2026, 4, 14)

    def test_parses_january_with_leading_zero(self) -> None:
        assert snapshot_date("SDP_product_table_01_01_2020.csv") == datetime.date(2020, 1, 1)

    def test_returns_none_for_non_matching(self) -> None:
        assert snapshot_date("something_else.csv") is None
        assert snapshot_date("SDP_product_table_nodate.csv") is None
        assert snapshot_date("SDP_product_table_4_14_26.csv") is None  # wrong digit count


class TestParseSdpDates:
    def test_parses_4_digit_year(self) -> None:
        out = _parse_sdp_dates(pd.Series(["7/16/2018", "12/31/2022"]))
        assert list(out) == [pd.Timestamp("2018-07-16"), pd.Timestamp("2022-12-31")]

    def test_parses_2_digit_year(self) -> None:
        out = _parse_sdp_dates(pd.Series(["7/16/18", "12/31/22"]))
        assert list(out) == [pd.Timestamp("2018-07-16"), pd.Timestamp("2022-12-31")]

    def test_mixed_series(self) -> None:
        """Real SDP CSVs have both formats across rows."""
        out = _parse_sdp_dates(pd.Series(["7/16/18", "7/16/2018"]))
        assert list(out) == [pd.Timestamp("2018-07-16"), pd.Timestamp("2018-07-16")]

    def test_handles_na(self) -> None:
        out = _parse_sdp_dates(pd.Series(["7/16/18", None, "12/31/2022"]))
        assert out.iloc[0] == pd.Timestamp("2018-07-16")
        assert pd.isna(out.iloc[1])
        assert out.iloc[2] == pd.Timestamp("2022-12-31")

    def test_does_not_coerce_2_digit_into_year_18_ad(self) -> None:
        """Guards against the rSDP bug that motivated explicit format detection."""
        out = _parse_sdp_dates(pd.Series(["7/16/18"]))
        assert out.iloc[0].year == 2018  # not year 18 AD


class TestStalenessThreshold:
    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(STALENESS_MONTHS_ENV, raising=False)
        assert _staleness_months_threshold() == STALENESS_MONTHS_DEFAULT

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(STALENESS_MONTHS_ENV, "12")
        assert _staleness_months_threshold() == 12

    def test_invalid_env_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(STALENESS_MONTHS_ENV, "not-an-int")
        assert _staleness_months_threshold() == STALENESS_MONTHS_DEFAULT


class TestStalenessWarning:
    def test_warns_when_old(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(STALENESS_MONTHS_ENV, "6")
        old = datetime.date(2025, 1, 1)
        today = datetime.date(2026, 4, 16)  # ~15 months later
        with pytest.warns(UserWarning, match="months old"):
            _emit_staleness_warning_if_needed(old, today=today)

    def test_silent_when_recent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(STALENESS_MONTHS_ENV, "6")
        recent = datetime.date(2026, 3, 1)
        today = datetime.date(2026, 4, 16)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _emit_staleness_warning_if_needed(recent, today=today)

    def test_silent_when_date_is_none(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _emit_staleness_warning_if_needed(None)


class TestLoadPackagedCatalog:
    def test_shape(self) -> None:
        df = load_packaged_catalog(emit_warning=False)
        assert len(df) > 100  # 156 as of 2026-04-14; test is non-fragile
        assert df["Deprecated"].dtype == bool

    def test_expected_columns(self) -> None:
        df = load_packaged_catalog(emit_warning=False)
        expected = {
            "CatalogID",
            "Release",
            "Type",
            "Product",
            "Domain",
            "Resolution",
            "Deprecated",
            "MinDate",
            "MaxDate",
            "MinYear",
            "MaxYear",
            "TimeSeriesType",
            "DataType",
            "DataUnit",
            "DataScaleFactor",
            "DataOffset",
            "Data.URL",
            "Metadata.URL",
        }
        assert expected.issubset(set(df.columns))

    def test_dates_parsed(self) -> None:
        df = load_packaged_catalog(emit_warning=False)
        assert df["MinDate"].dtype == "datetime64[ns]"
        assert df["MaxDate"].dtype == "datetime64[ns]"

    def test_snapshot_attrs(self) -> None:
        df = load_packaged_catalog(emit_warning=False)
        assert df.attrs["snapshot_date"] is not None
        assert df.attrs["snapshot_filename"].startswith("SDP_product_table_")
