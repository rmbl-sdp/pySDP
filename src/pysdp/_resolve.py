"""Time-slice resolvers for Single / Yearly / Monthly / Daily SDP datasets.

Behavior-preserving port of rSDP's ``R/internal_resolve.R``. Given a one-row
catalog "cat_line" (a ``pd.Series`` or any ``Mapping[str, Any]``) and user
time arguments, each resolver returns a ``TimeSlices`` named tuple with the
concrete list of VSICURL paths and matching layer names.

Resolvers are PURE functions: no network, no raster I/O. They are unit-tested
with synthetic in-memory fixtures.

Anchor-day seq semantics
------------------------
The Yearly and Monthly date-range branches preserve rSDP's
``seq(by="year"/"month")`` semantics: the step is anchored on the *first* day
of the overlap window, not on calendar boundaries. A request
``date_start=2003-06-15, date_end=2005-06-10`` against a catalog covering
2003-2005 yields years ``[2003, 2004]`` (NOT 2005), because stepping one
calendar year from 2003-06-15 gives 2004-06-15, 2005-06-15, and 2005-06-15
is after the requested end date 2005-06-10. This off-by-one is load-bearing;
callers relied on it pre-port. See tests in `test_resolve.py`.

Daily-default clipping
----------------------
A Daily dataset opened with no date bounds clips to the first 30 days of
the catalog's MinDate, matching rSDP's behavior. This prevents naive users
from building a 10-year VSICURL handle graph by accident.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, NamedTuple

from pysdp.constants import VSICURL_PREFIX
from pysdp.io.template import substitute_template

if TYPE_CHECKING:
    import datetime

    import pandas as pd


class TimeSlices(NamedTuple):
    """Resolved concrete paths + matching layer names for one catalog entry."""

    paths: list[str]
    names: list[str]


def _emit(msg: str, verbose: bool) -> None:
    if verbose:
        print(msg, file=sys.stderr)


def _as_timestamp(value: datetime.date | str | pd.Timestamp | Any) -> pd.Timestamp:
    import pandas as pd

    return pd.Timestamp(value)


def _seq_by_offset(start: pd.Timestamp, end: pd.Timestamp, offset: Any) -> list[pd.Timestamp]:
    """Generate dates from `start` to `end` (inclusive) stepping by `offset`.

    Preserves anchor-day semantics: the step is relative to `start`, not to
    calendar boundaries (so e.g. stepping one year from 2003-06-15 gives
    2004-06-15, not 2004-01-01).
    """
    out: list[pd.Timestamp] = []
    d = start
    while d <= end:
        out.append(d)
        d = d + offset
    return out


def resolve_single(cat_line: Mapping[str, Any], *, verbose: bool = True) -> TimeSlices:
    data_url = str(cat_line["Data.URL"])
    # Strip a trailing `.tif` (or anything regex `.tif` matches — see rSDP
    # note about the unanchored pattern).
    name = re.sub(r".tif", "", data_url.rsplit("/", 1)[-1])
    return TimeSlices(paths=[VSICURL_PREFIX + data_url], names=[name])


def resolve_yearly(
    cat_line: Mapping[str, Any],
    years: Sequence[int] | None,
    date_start: datetime.date | str | None,
    date_end: datetime.date | str | None,
    *,
    verbose: bool = True,
) -> TimeSlices:
    import pandas as pd

    template = VSICURL_PREFIX + str(cat_line["Data.URL"])
    min_year = int(cat_line["MinYear"])
    max_year = int(cat_line["MaxYear"])
    cat_years = list(range(min_year, max_year + 1))

    if years is not None:
        requested = [int(y) for y in years]
        keep = [y for y in requested if y in cat_years]
        if not keep:
            raise ValueError(
                f"No dataset available for any specified years. Available years are {cat_years}."
            )
        if len(keep) < len(requested):
            import warnings

            warnings.warn(
                f"No dataset available for some specified years. Returning data for {keep}.",
                UserWarning,
                stacklevel=3,
            )
        paths = substitute_template(template, year=keep)
        names = [str(y) for y in keep]
        _emit(f"Returning yearly dataset with {len(keep)} layers...", verbose)
        return TimeSlices(paths=paths, names=names)

    if date_start is not None and date_end is not None:
        min_date = _as_timestamp(cat_line["MinDate"])
        max_date = _as_timestamp(cat_line["MaxDate"])
        req_start = _as_timestamp(date_start)
        req_end = _as_timestamp(date_end)

        overlap_start = max(req_start, min_date)
        overlap_end = min(req_end, max_date)
        if overlap_start > overlap_end:
            raise ValueError(
                f"No dataset available for the specified years. Available years are {cat_years}."
            )

        dates_overlap = _seq_by_offset(overlap_start, overlap_end, pd.DateOffset(years=1))
        names = [d.strftime("%Y") for d in dates_overlap]
        paths = substitute_template(template, year=names)
        _emit(f"Returning yearly dataset with {len(paths)} layers...", verbose)
        return TimeSlices(paths=paths, names=names)

    # No time args — all catalog years.
    names = [str(y) for y in cat_years]
    paths = substitute_template(template, year=cat_years)
    _emit(f"Returning yearly dataset with {len(cat_years)} layers...", verbose)
    return TimeSlices(paths=paths, names=names)


def resolve_monthly(
    cat_line: Mapping[str, Any],
    years: Sequence[int] | None,
    months_pad: Sequence[str] | None,
    date_start: datetime.date | str | None,
    date_end: datetime.date | str | None,
    *,
    verbose: bool = True,
) -> TimeSlices:
    import pandas as pd

    template = VSICURL_PREFIX + str(cat_line["Data.URL"])
    min_date = _as_timestamp(cat_line["MinDate"])
    max_date = _as_timestamp(cat_line["MaxDate"])

    cat_months = _seq_by_offset(min_date, max_date, pd.DateOffset(months=1))

    if years is not None and months_pad is not None:
        years_str = {str(int(y)) for y in years}
        months_set = set(months_pad)
        dates_overlap = [
            d
            for d in cat_months
            if d.strftime("%Y") in years_str and d.strftime("%m") in months_set
        ]
    elif date_start is not None and date_end is not None:
        req_start = _as_timestamp(date_start)
        req_end = _as_timestamp(date_end)
        overlap_start = max(req_start, min_date)
        overlap_end = min(req_end, max_date)
        if overlap_start > overlap_end:
            raise ValueError("No monthly data available for the specified date range.")
        dates_overlap = _seq_by_offset(overlap_start, overlap_end, pd.DateOffset(months=1))
    elif months_pad is not None:
        months_set = set(months_pad)
        dates_overlap = [d for d in cat_months if d.strftime("%m") in months_set]
    else:
        dates_overlap = cat_months

    if not dates_overlap:
        raise ValueError("No monthly data available for the specified filters.")

    months_overlap = [d.strftime("%m") for d in dates_overlap]
    years_overlap = [d.strftime("%Y") for d in dates_overlap]
    paths = substitute_template(template, year=years_overlap, month=months_overlap)
    names = [d.strftime("%Y-%m") for d in dates_overlap]
    _emit(f"Returning monthly dataset with {len(paths)} layers...", verbose)
    return TimeSlices(paths=paths, names=names)


def resolve_daily(
    cat_line: Mapping[str, Any],
    date_start: datetime.date | str | None,
    date_end: datetime.date | str | None,
    *,
    verbose: bool = True,
) -> TimeSlices:
    import pandas as pd

    template = VSICURL_PREFIX + str(cat_line["Data.URL"])
    min_date = _as_timestamp(cat_line["MinDate"])
    max_date = _as_timestamp(cat_line["MaxDate"])

    if date_start is not None and date_end is not None:
        req_start = _as_timestamp(date_start)
        req_end = _as_timestamp(date_end)
        overlap_start = max(req_start, min_date)
        overlap_end = min(req_end, max_date)
        if overlap_start > overlap_end:
            raise ValueError(
                "No data available for any requested days. "
                f"Available days are {min_date.date()} to {max_date.date()}."
            )
        days_overlap = _seq_by_offset(overlap_start, overlap_end, pd.DateOffset(days=1))
        requested_days = _seq_by_offset(req_start, req_end, pd.DateOffset(days=1))
        if len(days_overlap) < len(requested_days):
            import warnings

            warnings.warn(
                "No data available for some requested days. "
                f"Returning data for {days_overlap[0].date()} to {days_overlap[-1].date()}.",
                UserWarning,
                stacklevel=3,
            )
        _emit(f"Returning daily dataset with {len(days_overlap)} layers...", verbose)
    else:
        # No time args — clip to first 30 days from MinDate.
        days_overlap = _seq_by_offset(
            min_date, min_date + pd.DateOffset(days=29), pd.DateOffset(days=1)
        )
        _emit(
            "No time bounds set for daily data, returning the first 30 layers. "
            "Specify `date_start` or `date_end` to retrieve larger daily time-series...",
            verbose,
        )

    years_overlap = [d.strftime("%Y") for d in days_overlap]
    doys_overlap = [d.strftime("%j") for d in days_overlap]
    paths = substitute_template(template, year=years_overlap, day=doys_overlap)
    names = [d.strftime("%Y-%m-%d") for d in days_overlap]
    return TimeSlices(paths=paths, names=names)


def resolve_time_slices(
    cat_line: Mapping[str, Any],
    years: Sequence[int] | None,
    months_pad: Sequence[str] | None,
    date_start: datetime.date | str | None,
    date_end: datetime.date | str | None,
    *,
    verbose: bool = True,
) -> TimeSlices:
    """Dispatch to the right resolver based on the catalog row's ``TimeSeriesType``.

    Callers should have already run ``validate_args_vs_type(cat_line['TimeSeriesType'], ...)``.
    """
    ts_type = cat_line["TimeSeriesType"]
    if ts_type == "Single":
        return resolve_single(cat_line, verbose=verbose)
    if ts_type == "Yearly":
        return resolve_yearly(cat_line, years, date_start, date_end, verbose=verbose)
    if ts_type == "Monthly":
        return resolve_monthly(cat_line, years, months_pad, date_start, date_end, verbose=verbose)
    if ts_type == "Daily":
        return resolve_daily(cat_line, date_start, date_end, verbose=verbose)
    raise ValueError(f"Unsupported TimeSeriesType: {ts_type!r}")
