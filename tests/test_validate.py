"""Unit tests for `pysdp._validate`.

Ports rSDP's `tests/testthat/test-internal_validate.R`.
"""

from __future__ import annotations

import datetime

import pytest

from pysdp._validate import validate_args_vs_type, validate_user_args

# ---------------------------------------------------------------------------
# validate_args_vs_type
# ---------------------------------------------------------------------------


class TestValidateArgsVsType:
    def test_single_rejects_years(self) -> None:
        with pytest.raises(ValueError, match="not supported for Single"):
            validate_args_vs_type(
                "Single", years=[2003], months=None, date_start=None, date_end=None
            )

    def test_single_rejects_dates(self) -> None:
        with pytest.raises(ValueError, match="not supported for Single"):
            validate_args_vs_type(
                "Single",
                years=None,
                months=None,
                date_start=datetime.date(2003, 1, 1),
                date_end=datetime.date(2003, 1, 2),
            )

    def test_yearly_rejects_months(self) -> None:
        with pytest.raises(ValueError, match="not supported for Yearly"):
            validate_args_vs_type("Yearly", years=None, months=[6], date_start=None, date_end=None)

    def test_yearly_rejects_years_and_dates(self) -> None:
        with pytest.raises(ValueError, match="either `years` or `date_start`"):
            validate_args_vs_type(
                "Yearly",
                years=[2003],
                months=None,
                date_start=datetime.date(2003, 1, 1),
                date_end=datetime.date(2004, 1, 1),
            )

    def test_monthly_rejects_years_only(self) -> None:
        with pytest.raises(ValueError, match="must be combined with"):
            validate_args_vs_type(
                "Monthly", years=[2003], months=None, date_start=None, date_end=None
            )

    def test_monthly_rejects_mix_of_year_and_dates(self) -> None:
        with pytest.raises(ValueError, match="Monthly datasets"):
            validate_args_vs_type(
                "Monthly",
                years=[2003],
                months=[6],
                date_start=datetime.date(2003, 1, 1),
                date_end=datetime.date(2003, 6, 30),
            )

    def test_daily_rejects_years(self) -> None:
        with pytest.raises(ValueError, match="Daily datasets"):
            validate_args_vs_type(
                "Daily", years=[2003], months=None, date_start=None, date_end=None
            )

    def test_daily_rejects_months(self) -> None:
        with pytest.raises(ValueError, match="Daily datasets"):
            validate_args_vs_type("Daily", years=None, months=[6], date_start=None, date_end=None)

    @pytest.mark.parametrize(
        ("ts_type", "years", "months", "date_start", "date_end"),
        [
            ("Single", None, None, None, None),
            ("Yearly", [2003], None, None, None),
            ("Yearly", None, None, datetime.date(2003, 1, 1), datetime.date(2005, 12, 31)),
            ("Yearly", None, None, None, None),
            ("Monthly", [2003], [6], None, None),
            ("Monthly", None, [6], None, None),
            ("Monthly", None, None, datetime.date(2003, 1, 1), datetime.date(2003, 6, 30)),
            ("Monthly", None, None, None, None),
            ("Daily", None, None, datetime.date(2003, 1, 1), datetime.date(2003, 1, 10)),
            ("Daily", None, None, None, None),
        ],
    )
    def test_accepts_valid_combinations(
        self,
        ts_type: str,
        years: list[int] | None,
        months: list[int] | None,
        date_start: datetime.date | None,
        date_end: datetime.date | None,
    ) -> None:
        # No exception means pass.
        validate_args_vs_type(
            ts_type,
            years=years,
            months=months,
            date_start=date_start,
            date_end=date_end,
        )

    def test_unknown_type_does_not_raise(self) -> None:
        """Seasonal / unknown types fall through without validation (matches rSDP)."""
        validate_args_vs_type(
            "Seasonal",
            years=[2003],
            months=None,
            date_start=None,
            date_end=None,
        )


# ---------------------------------------------------------------------------
# validate_user_args
# ---------------------------------------------------------------------------


class TestValidateUserArgs:
    def test_normalizes_months_to_zero_padded_strings(self) -> None:
        result = validate_user_args(
            catalog_id="R4D008",
            url=None,
            years=None,
            months=[3, 11],
            date_start=None,
            date_end=None,
            download_files=False,
            download_path=None,
        )
        assert result["months_pad"] == ["03", "11"]

    def test_returns_null_months_pad_when_unset(self) -> None:
        result = validate_user_args(
            catalog_id="R4D008",
            url=None,
            years=None,
            months=None,
            date_start=None,
            date_end=None,
            download_files=False,
            download_path=None,
        )
        assert result["months_pad"] is None

    def test_rejects_invalid_month_numbers(self) -> None:
        with pytest.raises(ValueError, match="Invalid months"):
            validate_user_args(
                catalog_id="R4D008",
                url=None,
                years=None,
                months=[0, 13],
                date_start=None,
                date_end=None,
                download_files=False,
                download_path=None,
            )

    def test_rejects_both_catalog_id_and_url(self) -> None:
        with pytest.raises(ValueError, match="either catalog_id or url"):
            validate_user_args(
                catalog_id="R4D008",
                url="https://x/y.tif",
                years=None,
                months=None,
                date_start=None,
                date_end=None,
                download_files=False,
                download_path=None,
            )

    def test_rejects_neither_catalog_id_nor_url(self) -> None:
        with pytest.raises(ValueError, match="must specify either catalog_id or url"):
            validate_user_args(
                catalog_id=None,
                url=None,
                years=None,
                months=None,
                date_start=None,
                date_end=None,
                download_files=False,
                download_path=None,
            )

    def test_rejects_half_specified_date_range(self) -> None:
        with pytest.raises(ValueError, match="both"):
            validate_user_args(
                catalog_id="R4D008",
                url=None,
                years=None,
                months=None,
                date_start=datetime.date(2003, 1, 1),
                date_end=None,
                download_files=False,
                download_path=None,
            )

    def test_rejects_download_files_without_path(self) -> None:
        with pytest.raises(ValueError, match="download_path"):
            validate_user_args(
                catalog_id="R4D008",
                url=None,
                years=None,
                months=None,
                date_start=None,
                date_end=None,
                download_files=True,
                download_path=None,
            )
