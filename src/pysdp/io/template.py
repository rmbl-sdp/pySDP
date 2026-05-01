"""URL template substitution for time-series SDP data paths.

Behavior-preserving port of rSDP's ``.substitute_template()`` in
``R/internal_resolve.R``. Substitutes ``{year}``, ``{month}``, and ``{day}``
placeholders with string values, supporting scalar or vector inputs with
length-1 recycling.
"""

from __future__ import annotations

from collections.abc import Iterable


def _as_str_list(value: str | int | Iterable[str | int] | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, int):
        return [str(value)]
    return [str(v) for v in value]


def substitute_template(
    template: str,
    *,
    year: str | int | Iterable[str | int] | None = None,
    month: str | int | Iterable[str | int] | None = None,
    day: str | int | Iterable[str | int] | None = None,
    calendarday: str | int | Iterable[str | int] | None = None,
) -> list[str]:
    """Substitute ``{year}``, ``{month}``, ``{day}``, ``{calendarday}`` placeholders.

    Each placeholder argument may be ``None`` (leave placeholder untouched), a
    scalar string/int (recycled to length N), or an iterable of length 1 or N,
    where N is the longest of the provided arguments. Mismatched-length
    vectors raise ``ValueError``.

    ``{day}`` is day-of-year (DOY, 3-digit, used by Daily products).
    ``{calendarday}`` is calendar day-of-month (2-digit, used by Weekly
    drone imagery products). Both can coexist in a template.

    Parameters
    ----------
    template
        A string URL or path containing zero or more placeholders.

    Returns
    -------
    list of str
        The substituted strings, one per resolved slot. If no placeholders
        are provided, returns ``[template]`` (length 1).
    """
    year_v = _as_str_list(year)
    month_v = _as_str_list(month)
    day_v = _as_str_list(day)
    cday_v = _as_str_list(calendarday)

    provided = [v for v in (year_v, month_v, day_v, cday_v) if v is not None]
    if not provided:
        return [template]

    lens = [len(v) for v in provided]
    n = max(lens)
    for length in lens:
        if length not in (1, n):
            raise ValueError(
                f"Mismatched placeholder vector lengths: {lens!r}. "
                f"Each vector must be length 1 or {n}."
            )

    def _broadcast(values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return values * n if len(values) == 1 else values

    year_b = _broadcast(year_v)
    month_b = _broadcast(month_v)
    day_b = _broadcast(day_v)
    cday_b = _broadcast(cday_v)

    out: list[str] = []
    for i in range(n):
        s = template
        if year_b is not None:
            s = s.replace("{year}", year_b[i])
        if month_b is not None:
            s = s.replace("{month}", month_b[i])
        if day_b is not None:
            s = s.replace("{day}", day_b[i])
        if cday_b is not None:
            s = s.replace("{calendarday}", cday_b[i])
        out.append(s)
    return out
