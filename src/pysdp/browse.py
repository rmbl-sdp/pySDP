"""Visual catalog browser for Jupyter notebooks.

Renders an HTML grid of SDP product thumbnails with metadata, SDP Browser
links, and copyable ``open_raster()`` snippets. Uses only HTML attributes
(no inline ``style``, no JavaScript, no iframes) for maximum compatibility
across JupyterLab, Positron, VS Code, and classic Notebook — all of which
have different HTML sanitizer policies.
"""

from __future__ import annotations

import warnings
from html import escape
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import quote

from pysdp.catalog import get_catalog

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pandas as pd


# Sentinel for detecting whether the legacy `deprecated=` kwarg was passed.
_UNSET: Any = object()


SDP_BROWSER_BASE = "https://sdpbrowser.org/"


def _browser_url(catalog_id: str) -> str:
    """Build an SDP Browser URL that opens this product as a map layer."""
    return f"{SDP_BROWSER_BASE}#add={quote(catalog_id, safe='')}"


def _card_html(row: pd.Series, width: int) -> str:
    """Render one product card using only HTML attributes (no inline style)."""
    import pandas as pd

    from pysdp.issues import issues_search_url

    cat_id_raw = str(row.get("CatalogID", ""))
    cat_id = escape(cat_id_raw)
    product = escape(str(row.get("Product", "")))
    domain = escape(str(row.get("Domain", "")))
    resolution = escape(str(row.get("Resolution", "")))
    ts_type = escape(str(row.get("TimeSeriesType", "")))
    thumb = escape(str(row.get("Thumbnail.URL", "")))
    browser_link = escape(_browser_url(cat_id_raw))
    open_call = f'pysdp.open_raster("{cat_id}")'

    is_deprecated = bool(row.get("Deprecated", False))
    new_id_raw = row.get("NewVersionID")
    new_id = "" if new_id_raw is None or pd.isna(new_id_raw) else str(new_id_raw).strip()
    if is_deprecated:
        label = f"deprecated → {new_id}" if new_id else "deprecated"
        deprecated_badge = f"<small><b>{escape(label)}</b></small><br>"
        card_bg = "#f0e6e6"
    else:
        deprecated_badge = ""
        card_bg = "#f8f8f8"

    open_issues_raw = row.get("OpenIssues")
    try:
        open_issues = (
            0 if open_issues_raw is None or pd.isna(open_issues_raw) else int(open_issues_raw)
        )
    except (TypeError, ValueError):
        open_issues = 0
    if open_issues > 0:
        plural = "" if open_issues == 1 else "s"
        issue_url = escape(issues_search_url(cat_id_raw))
        issues_badge = (
            f'<small><a href="{issue_url}" target="_blank">'
            f"⚠ {open_issues} open issue{plural}</a></small><br>"
        )
    else:
        issues_badge = ""

    return (
        f'<td width="{width}" valign="top" bgcolor="{card_bg}">'
        f'<img src="{thumb}" width="{width - 10}" alt="{cat_id}" loading="lazy"><br>'
        f"<b>{cat_id}</b><br>"
        f"{product}<br>"
        f"<small>{domain} &middot; {resolution} &middot; {ts_type}</small><br>"
        f"{deprecated_badge}"
        f"{issues_badge}"
        f'<a href="{browser_link}" target="_blank">SDP Browser &nearr;</a><br>'
        f"<code>{escape(open_call)}</code>"
        f"</td>"
    )


def _grid_html(df: pd.DataFrame, *, columns: int, width: int, title: str | None) -> str:
    """Render the full grid as an HTML table using only HTML attributes."""
    card_list = [_card_html(row, width) for _, row in df.iterrows()]
    title_html = ""
    if title:
        title_html = f"<p><b>{escape(title)}</b></p>"

    rows_html: list[str] = []
    for i in range(0, len(card_list), columns):
        chunk = card_list[i : i + columns]
        cells = "".join(chunk)
        for _ in range(columns - len(chunk)):
            cells += f'<td width="{width}"></td>'
        rows_html.append(f"<tr>{cells}</tr>")

    return f'{title_html}<table cellpadding="8" cellspacing="6">{"".join(rows_html)}</table>'


class CatalogBrowser:
    """A displayable grid of SDP product thumbnails.

    Uses only HTML attributes (``width``, ``bgcolor``, ``cellpadding``,
    etc.) — no inline ``style``, no JavaScript, no iframes. This renders
    correctly in JupyterLab, Positron, VS Code notebooks, and classic
    Notebook despite their differing HTML sanitizer policies.

    Outside notebooks, ``str(browser)`` returns the raw HTML string.
    """

    def __init__(self, html: str) -> None:
        self._html = html

    def _repr_html_(self) -> str:
        return self._html

    def __str__(self) -> str:
        return self._html

    def __repr__(self) -> str:
        return f"<CatalogBrowser ({self._html.count('<img')} products)>"


def browse(
    domains: Sequence[str] | None = None,
    types: Sequence[str] | None = None,
    releases: Sequence[str] | None = None,
    timeseries_types: Sequence[str] | None = None,
    deprecated: bool | None | Any = _UNSET,
    *,
    include_deprecated: bool = False,
    with_issue_counts: bool = False,
    columns: int = 4,
    width: int = 220,
    source: Literal["packaged", "live"] = "packaged",
    max_products: int | None = None,
) -> CatalogBrowser:
    """Visual catalog browser — renders a thumbnail grid in Jupyter notebooks.

    Accepts the same filter arguments as :func:`get_catalog` and displays
    each matching product as a card with its thumbnail image, metadata,
    an SDP Browser link, and a copyable ``open_raster()`` snippet.
    Deprecated products are rendered with a tinted background and a small
    badge pointing at the replacement ``CatalogID``.

    Parameters
    ----------
    domains, types, releases, timeseries_types
        Same filters as :func:`get_catalog`.
    include_deprecated : bool, default False
        If ``True``, deprecated products are shown alongside current ones
        (with a deprecation badge). Default hides them.
    deprecated : bool or None, optional
        .. deprecated:: 0.5
           Use ``include_deprecated`` instead.
    with_issue_counts : bool, default False
        If ``True``, fetch open issue counts from
        ``rmbl-sdp/sdp-products`` (cached for one hour) and render a
        "⚠ N open issues" badge on affected cards.
    columns : int, default 4
        Number of columns in the grid.
    width : int, default 220
        Width of each card in pixels.
    source : {"packaged", "live"}, default "packaged"
        Catalog source. ``"stac"`` is not supported here.
    max_products : int or None, default None
        Cap the number of products shown. ``None`` shows all matches.

    Returns
    -------
    CatalogBrowser
        An object that renders as an HTML grid in Jupyter (via
        ``_repr_html_``). Outside notebooks, cast to ``str`` for the raw
        HTML.

    Examples
    --------
    Browse all Upper Gunnison vegetation products:

    >>> import pysdp
    >>> pysdp.browse(domains=["UG"], types=["Vegetation"])  # doctest: +SKIP

    Show all topo products in a 3-column grid:

    >>> pysdp.browse(types=["Topo"], columns=3)  # doctest: +SKIP

    See Also
    --------
    get_catalog : Tabular catalog discovery (returns a DataFrame).
    """
    import pandas as pd

    if deprecated is not _UNSET:
        warnings.warn(
            "`deprecated=` is deprecated in pysdp.browse(); use "
            "`include_deprecated=` instead. `include_deprecated=True` shows "
            "both current and deprecated products.",
            DeprecationWarning,
            stacklevel=2,
        )
        get_catalog_kwargs: dict[str, Any] = {"deprecated": deprecated}
    else:
        get_catalog_kwargs = {"include_deprecated": include_deprecated}

    df = cast(
        pd.DataFrame,
        get_catalog(
            domains=domains,
            types=types,
            releases=releases,
            timeseries_types=timeseries_types,
            source=source,
            with_issue_counts=with_issue_counts,
            **get_catalog_kwargs,
        ),
    )
    if max_products is not None:
        df = df.head(max_products)

    n = len(df)
    filters = []
    if domains:
        filters.append(f"domains={list(domains)}")
    if types:
        filters.append(f"types={list(types)}")
    title = f"{n} product{'s' if n != 1 else ''}"
    if filters:
        title += f" — {', '.join(filters)}"

    html = _grid_html(df, columns=columns, width=width, title=title)
    return CatalogBrowser(html)


__all__ = ["browse"]
