"""Unit tests for `pysdp._resolve` resolvers.

Ports rSDP's `tests/testthat/test-internal_resolve.R`. Uses in-memory
synthetic cat_line dicts — no network, no raster I/O.
"""

from __future__ import annotations

import datetime
from typing import Any

import pandas as pd
import pytest

from pysdp._resolve import (
    resolve_daily,
    resolve_monthly,
    resolve_single,
    resolve_time_slices,
    resolve_yearly,
)
from pysdp.constants import VSICURL_PREFIX


def fake_cat_line(
    ts_type: str,
    *,
    data_url: str = "https://test.example/data/{year}.tif",
    min_date: datetime.date = datetime.date(2003, 1, 1),
    max_date: datetime.date = datetime.date(2005, 12, 31),
    min_year: int = 2003,
    max_year: int = 2005,
    scale_factor: float = 1.0,
    offset: float = 0.0,
) -> dict[str, Any]:
    """Python analog of rSDP's `.fake_cat_line()` testthat helper."""
    return {
        "CatalogID": "FAKE01",
        "TimeSeriesType": ts_type,
        "Data.URL": data_url,
        "MinDate": pd.Timestamp(min_date),
        "MaxDate": pd.Timestamp(max_date),
        "MinYear": min_year,
        "MaxYear": max_year,
        "DataScaleFactor": scale_factor,
        "DataOffset": offset,
    }


# ---------------------------------------------------------------------------
# resolve_single
# ---------------------------------------------------------------------------


class TestResolveSingle:
    def test_returns_one_path_and_basename_minus_tif(self) -> None:
        cl = fake_cat_line("Single", data_url="https://test.example/dem_1m_v1.tif")
        result = resolve_single(cl, verbose=False)
        assert len(result.paths) == 1
        assert result.names == ["dem_1m_v1"]
        assert result.paths == [VSICURL_PREFIX + "https://test.example/dem_1m_v1.tif"]


# ---------------------------------------------------------------------------
# resolve_yearly
# ---------------------------------------------------------------------------


class TestResolveYearly:
    def test_explicit_years_returns_character_names(self) -> None:
        cl = fake_cat_line("Yearly", min_year=2003, max_year=2005)
        result = resolve_yearly(cl, [2003, 2004], None, None, verbose=False)
        assert result.names == ["2003", "2004"]
        assert len(result.paths) == 2
        assert all(isinstance(n, str) for n in result.names)

    def test_no_time_args_returns_all_catalog_years(self) -> None:
        cl = fake_cat_line("Yearly", min_year=2003, max_year=2005)
        result = resolve_yearly(cl, None, None, None, verbose=False)
        assert result.names == ["2003", "2004", "2005"]

    def test_errors_when_requested_years_entirely_outside_range(self) -> None:
        cl = fake_cat_line("Yearly", min_year=2003, max_year=2005)
        with pytest.raises(ValueError, match="No dataset available for any specified years"):
            resolve_yearly(cl, [1999, 2001], None, None, verbose=False)

    def test_warns_when_some_years_outside_range(self) -> None:
        cl = fake_cat_line("Yearly", min_year=2003, max_year=2005)
        with pytest.warns(UserWarning, match="No dataset available for some specified years"):
            result = resolve_yearly(cl, [2001, 2003, 2004], None, None, verbose=False)
        assert result.names == ["2003", "2004"]

    def test_date_range_preserves_anchor_day_semantics(self) -> None:
        """Jun 15 2003 - Jun 10 2005: anchor step lands on 2003-06-15, 2004-06-15;
        2005-06-15 is *after* the requested end of 2005-06-10 and is excluded."""
        cl = fake_cat_line(
            "Yearly",
            min_date=datetime.date(2003, 1, 1),
            max_date=datetime.date(2005, 12, 31),
            min_year=2003,
            max_year=2005,
        )
        result = resolve_yearly(
            cl,
            None,
            datetime.date(2003, 6, 15),
            datetime.date(2005, 6, 10),
            verbose=False,
        )
        assert result.names == ["2003", "2004"]

    def test_date_range_covering_full_years(self) -> None:
        cl = fake_cat_line(
            "Yearly",
            min_date=datetime.date(2003, 1, 1),
            max_date=datetime.date(2005, 12, 31),
            min_year=2003,
            max_year=2005,
        )
        result = resolve_yearly(
            cl,
            None,
            datetime.date(2003, 1, 1),
            datetime.date(2005, 12, 31),
            verbose=False,
        )
        assert result.names == ["2003", "2004", "2005"]


# ---------------------------------------------------------------------------
# resolve_monthly
# ---------------------------------------------------------------------------


class TestResolveMonthly:
    def test_years_and_months_returns_cross_product(self) -> None:
        cl = fake_cat_line(
            "Monthly",
            min_date=datetime.date(2003, 1, 1),
            max_date=datetime.date(2005, 12, 1),
            data_url="https://test.example/{year}_{month}.tif",
        )
        result = resolve_monthly(cl, [2003, 2004], ["06", "07"], None, None, verbose=False)
        assert result.names == ["2003-06", "2003-07", "2004-06", "2004-07"]

    def test_months_only_returns_matching_across_all_years(self) -> None:
        cl = fake_cat_line(
            "Monthly",
            min_date=datetime.date(2003, 1, 1),
            max_date=datetime.date(2004, 12, 1),
            data_url="https://test.example/{year}_{month}.tif",
        )
        result = resolve_monthly(cl, None, ["07"], None, None, verbose=False)
        assert result.names == ["2003-07", "2004-07"]

    def test_no_time_args_returns_all_monthly_layers(self) -> None:
        cl = fake_cat_line(
            "Monthly",
            min_date=datetime.date(2003, 1, 1),
            max_date=datetime.date(2003, 3, 1),
            data_url="https://test.example/{year}_{month}.tif",
        )
        result = resolve_monthly(cl, None, None, None, None, verbose=False)
        assert result.names == ["2003-01", "2003-02", "2003-03"]

    def test_errors_on_empty_overlap(self) -> None:
        cl = fake_cat_line(
            "Monthly",
            min_date=datetime.date(2003, 1, 1),
            max_date=datetime.date(2003, 12, 1),
            data_url="https://test.example/{year}_{month}.tif",
        )
        with pytest.raises(ValueError, match="No monthly data"):
            resolve_monthly(cl, [1999], ["06"], None, None, verbose=False)

    def test_date_range(self) -> None:
        cl = fake_cat_line(
            "Monthly",
            min_date=datetime.date(2003, 1, 1),
            max_date=datetime.date(2005, 12, 1),
            data_url="https://test.example/{year}_{month}.tif",
        )
        result = resolve_monthly(
            cl,
            None,
            None,
            datetime.date(2003, 6, 15),
            datetime.date(2003, 11, 15),
            verbose=False,
        )
        # Anchor-day: step month from 2003-06-15 → 6, 7, 8, 9, 10, 11.
        assert result.names == ["2003-06", "2003-07", "2003-08", "2003-09", "2003-10", "2003-11"]


# ---------------------------------------------------------------------------
# resolve_daily
# ---------------------------------------------------------------------------


class TestResolveDaily:
    def test_no_time_args_clips_to_first_30_layers(self) -> None:
        cl = fake_cat_line(
            "Daily",
            min_date=datetime.date(2003, 1, 1),
            max_date=datetime.date(2005, 12, 31),
            data_url="https://test.example/{year}_{day}.tif",
        )
        result = resolve_daily(cl, None, None, verbose=False)
        assert len(result.paths) == 30
        assert len(result.names) == 30
        assert result.names[0] == "2003-01-01"
        assert result.names[29] == "2003-01-30"

    def test_date_range_returns_exactly_overlap(self) -> None:
        cl = fake_cat_line(
            "Daily",
            min_date=datetime.date(2003, 1, 1),
            max_date=datetime.date(2005, 12, 31),
            data_url="https://test.example/{year}_{day}.tif",
        )
        result = resolve_daily(
            cl,
            datetime.date(2003, 1, 5),
            datetime.date(2003, 1, 7),
            verbose=False,
        )
        assert result.names == ["2003-01-05", "2003-01-06", "2003-01-07"]
        assert len(result.paths) == 3

    def test_errors_when_entirely_outside_range(self) -> None:
        cl = fake_cat_line(
            "Daily",
            min_date=datetime.date(2003, 1, 1),
            max_date=datetime.date(2005, 12, 31),
        )
        with pytest.raises(ValueError, match="No data available for any requested days"):
            resolve_daily(
                cl,
                datetime.date(1999, 1, 1),
                datetime.date(1999, 12, 31),
                verbose=False,
            )

    def test_uses_doy_in_path_substitution(self) -> None:
        cl = fake_cat_line(
            "Daily",
            min_date=datetime.date(2003, 1, 1),
            max_date=datetime.date(2005, 12, 31),
            data_url="https://test.example/{year}_{day}.tif",
        )
        result = resolve_daily(
            cl,
            datetime.date(2003, 1, 5),
            datetime.date(2003, 1, 5),
            verbose=False,
        )
        # DOY=005 for 2003-01-05.
        assert result.paths[0].endswith("2003_005.tif")


# ---------------------------------------------------------------------------
# resolve_time_slices dispatch
# ---------------------------------------------------------------------------


class TestResolveTimeSlices:
    def test_dispatches_correctly(self) -> None:
        cl_single = fake_cat_line("Single", data_url="https://test.example/x.tif")
        result = resolve_time_slices(cl_single, None, None, None, None, verbose=False)
        assert result.names == ["x"]

        cl_yearly = fake_cat_line("Yearly")
        result_y = resolve_time_slices(
            cl_yearly,
            [2003, 2004],
            None,
            None,
            None,
            verbose=False,
        )
        assert result_y.names == ["2003", "2004"]

    def test_errors_on_unsupported_type(self) -> None:
        cl_bad = fake_cat_line("UnknownType")
        with pytest.raises(ValueError, match="Unsupported TimeSeriesType"):
            resolve_time_slices(cl_bad, None, None, None, None, verbose=False)
