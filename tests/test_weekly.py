"""Tests for Weekly/irregular time-series support (rSDP v0.3 port)."""

from __future__ import annotations

import datetime

import pytest

import pysdp
from pysdp._catalog_data import load_manifests
from pysdp._resolve import resolve_weekly
from pysdp._validate import validate_args_vs_type
from pysdp.dates import get_dates
from pysdp.io.template import substitute_template

# ---------------------------------------------------------------------------
# {calendarday} template substitution
# ---------------------------------------------------------------------------


class TestCalendardayTemplate:
    def test_substitutes_calendarday(self) -> None:
        result = substitute_template(
            "a/{year}/{month}/{calendarday}.tif",
            year="2022",
            month="03",
            calendarday="01",
        )
        assert result == ["a/2022/03/01.tif"]

    def test_vector_calendarday(self) -> None:
        result = substitute_template(
            "a/{year}_{month}_{calendarday}.tif",
            year=["2022", "2022"],
            month=["03", "04"],
            calendarday=["01", "08"],
        )
        assert result == ["a/2022_03_01.tif", "a/2022_04_08.tif"]

    def test_recycles_year_with_calendarday(self) -> None:
        result = substitute_template(
            "a/{year}_{month}_{calendarday}.tif",
            year="2022",
            month=["03", "04"],
            calendarday=["01", "08"],
        )
        assert result == ["a/2022_03_01.tif", "a/2022_04_08.tif"]


# ---------------------------------------------------------------------------
# Weekly validation
# ---------------------------------------------------------------------------


class TestWeeklyValidation:
    def test_rejects_years(self) -> None:
        with pytest.raises(ValueError, match="Weekly"):
            validate_args_vs_type(
                "Weekly", years=[2022], months=None, date_start=None, date_end=None
            )

    def test_rejects_months(self) -> None:
        with pytest.raises(ValueError, match="Weekly"):
            validate_args_vs_type("Weekly", years=None, months=[3], date_start=None, date_end=None)

    def test_accepts_date_range(self) -> None:
        validate_args_vs_type(
            "Weekly",
            years=None,
            months=None,
            date_start=datetime.date(2022, 3, 1),
            date_end=datetime.date(2022, 6, 1),
        )

    def test_accepts_no_args(self) -> None:
        validate_args_vs_type("Weekly", years=None, months=None, date_start=None, date_end=None)


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------


class TestManifests:
    def test_load_manifests_returns_dict(self) -> None:
        m = load_manifests()
        assert isinstance(m, dict)
        assert "R6D001" in m
        assert "R6D002" in m

    def test_r6d001_has_dates(self) -> None:
        m = load_manifests()
        dates = m["R6D001"]
        assert len(dates) > 50
        assert all(isinstance(d, datetime.date) for d in dates)
        assert dates == sorted(dates)

    def test_r6d002_dates_are_subset(self) -> None:
        m = load_manifests()
        assert len(m["R6D002"]) < len(m["R6D001"])


# ---------------------------------------------------------------------------
# resolve_weekly
# ---------------------------------------------------------------------------


def _weekly_cat_line() -> dict:
    return {
        "CatalogID": "R6D001",
        "TimeSeriesType": "Weekly",
        "Type": "Imagery",
        "Data.URL": "https://test.example/{year}/file_{year}_{month}_{calendarday}.tif",
        "MinDate": datetime.date(2022, 3, 1),
        "MaxDate": datetime.date(2025, 11, 13),
    }


class TestResolveWeekly:
    def test_returns_all_dates_when_no_filters(self) -> None:
        result = resolve_weekly(
            _weekly_cat_line(), dates=None, date_start=None, date_end=None, verbose=False
        )
        assert len(result.paths) > 50
        assert result.is_imagery

    def test_date_range_filters(self) -> None:
        result = resolve_weekly(
            _weekly_cat_line(),
            dates=None,
            date_start="2023-01-01",
            date_end="2023-12-31",
            verbose=False,
        )
        for name in result.names:
            assert name.startswith("2023-")

    def test_explicit_dates(self) -> None:
        m = load_manifests()
        two_dates = m["R6D001"][:2]
        result = resolve_weekly(
            _weekly_cat_line(), dates=two_dates, date_start=None, date_end=None, verbose=False
        )
        assert len(result.paths) == 2

    def test_errors_on_empty_overlap(self) -> None:
        with pytest.raises(ValueError, match="None of the requested dates"):
            resolve_weekly(
                _weekly_cat_line(),
                dates=[datetime.date(1999, 1, 1)],
                date_start=None,
                date_end=None,
                verbose=False,
            )

    def test_is_imagery_true_for_imagery_type(self) -> None:
        cat = _weekly_cat_line()
        cat["Type"] = "Imagery"
        result = resolve_weekly(cat, dates=None, date_start=None, date_end=None, verbose=False)
        assert result.is_imagery is True

    def test_is_imagery_false_for_non_imagery(self) -> None:
        cat = _weekly_cat_line()
        cat["Type"] = "Snow"
        result = resolve_weekly(cat, dates=None, date_start=None, date_end=None, verbose=False)
        assert result.is_imagery is False


# ---------------------------------------------------------------------------
# get_dates
# ---------------------------------------------------------------------------


class TestGetDates:
    def test_yearly_product(self) -> None:
        dates = get_dates("R4D001")
        assert all(isinstance(d, datetime.date) for d in dates)
        assert len(dates) > 5

    def test_weekly_product(self) -> None:
        dates = get_dates("R6D001")
        assert len(dates) > 50
        assert dates == sorted(dates)

    def test_unknown_id_raises(self) -> None:
        with pytest.raises(KeyError, match="not found"):
            get_dates("ZZZZZZ")


# ---------------------------------------------------------------------------
# Constants updated
# ---------------------------------------------------------------------------


class TestUpdatedConstants:
    def test_weekly_in_timeseries_types(self) -> None:
        assert "Weekly" in pysdp.TIMESERIES_TYPES

    def test_release6_in_releases(self) -> None:
        assert "Release6" in pysdp.RELEASES

    def test_get_dates_exported(self) -> None:
        assert hasattr(pysdp, "get_dates")

    def test_catalog_has_weekly_products(self) -> None:
        df = pysdp.get_catalog(timeseries_types=["Weekly"])
        assert len(df) > 0
        assert all(df["TimeSeriesType"] == "Weekly")

    def test_catalog_has_release6(self) -> None:
        df = pysdp.get_catalog(releases=["Release6"])
        assert len(df) > 0
