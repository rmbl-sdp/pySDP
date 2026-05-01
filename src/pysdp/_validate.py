"""Argument validation for `open_raster` and friends.

Behavior-preserving port of rSDP's ``R/internal_validate.R``. Split into two
stages so the ``url=`` branch of `open_raster` can reuse the pre-catalog-lookup
half, and so the post-catalog-lookup "is this arg combo supported for this
TimeSeriesType?" checks have a single source of truth.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    import os
    from collections.abc import Sequence


class NormalizedUserArgs(TypedDict):
    """Normalized form of user-facing args returned by `validate_user_args`."""

    months_pad: list[str] | None


def validate_user_args(
    *,
    catalog_id: str | None,
    url: str | None,
    years: Sequence[int] | None,
    months: Sequence[int] | None,
    date_start: str | datetime.date | None,
    date_end: str | datetime.date | None,
    download_files: bool,
    download_path: str | os.PathLike[str] | None,
) -> NormalizedUserArgs:
    """Pre-catalog-lookup argument validation.

    Returns a dict of normalized values currently just containing
    zero-padded ``months_pad``.
    """
    if catalog_id is not None and url is not None:
        raise ValueError("Please specify either catalog_id or url, not both.")
    if catalog_id is None and url is None:
        raise ValueError("You must specify either catalog_id or url.")
    if catalog_id is not None and not isinstance(catalog_id, str):
        raise TypeError("catalog_id must be a string.")
    if url is not None and not isinstance(url, str):
        raise TypeError("url must be a string.")

    _both_none = date_start is None and date_end is None
    _both_set = date_start is not None and date_end is not None
    if not (_both_none or _both_set):
        raise ValueError("Specify both `date_start` and `date_end`, or neither.")

    if download_files and download_path is None:
        raise ValueError("You must specify `download_path` if `download_files=True`.")
    if not download_files and download_path is not None:
        raise ValueError("`download_path` is only meaningful when `download_files=True`.")

    months_pad = _normalize_months(months)

    return {"months_pad": months_pad}


def _normalize_months(months: Sequence[int] | None) -> list[str] | None:
    if months is None:
        return None
    try:
        values = [int(m) for m in months]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid months: {months!r} (must be integers 1-12).") from exc
    if any(m < 1 or m > 12 for m in values):
        raise ValueError(f"Invalid months: {months!r} (must be integers 1-12).")
    return [f"{m:02d}" for m in values]


def validate_args_vs_type(
    ts_type: str,
    *,
    years: Sequence[int] | None,
    months: Sequence[int] | None,
    date_start: str | datetime.date | None,
    date_end: str | datetime.date | None,
) -> None:
    """Post-catalog-lookup: is this arg combo valid for the dataset's TimeSeriesType?

    Raises ``ValueError`` with a descriptive message on invalid combinations.
    Silently accepts valid ones. `Seasonal` and unknown types fall through
    without validation, matching rSDP's behavior (no resolver exists yet).
    """
    has_years = years is not None
    has_months = months is not None
    has_dates = date_start is not None and date_end is not None

    if ts_type == "Single":
        if has_years or has_months or has_dates:
            raise ValueError(
                "Time arguments (years/months/date_start/date_end) are not "
                "supported for Single datasets."
            )
    elif ts_type == "Yearly":
        if has_months:
            raise ValueError("`months` is not supported for Yearly datasets.")
        if has_years and has_dates:
            raise ValueError(
                "Specify either `years` or `date_start`/`date_end` for Yearly datasets, not both."
            )
    elif ts_type == "Monthly":
        if has_years and not has_months and not has_dates:
            raise ValueError(
                "For Monthly datasets, `years` must be combined with `months`. "
                "Use `date_start`/`date_end` instead if you want a date-range subset."
            )
        if has_dates and (has_years or has_months):
            raise ValueError(
                "For Monthly datasets, use either `date_start`/`date_end` OR "
                "`years`/`months`, not both."
            )
    elif ts_type == "Daily" and (has_years or has_months):
        raise ValueError(
            "For Daily datasets, use `date_start`/`date_end` instead of `years` or `months`."
        )
    elif ts_type == "Weekly" and (has_years or has_months):
        raise ValueError(
            "For Weekly datasets, use `date_start`/`date_end` or `dates` instead of "
            "`years` or `months`."
        )
    # Seasonal or unknown types fall through (no resolver yet).
