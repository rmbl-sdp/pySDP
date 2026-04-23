"""Visual catalog browser for Jupyter notebooks.

Renders an HTML grid of SDP product thumbnails with overlaid metadata,
making catalog discovery visual rather than tabular. Works in JupyterLab,
classic Notebook, and VS Code notebooks.

Each card shows the product thumbnail with a persistent "Open in SDP
Browser" link and a copyable ``open_raster()`` code snippet — no
JavaScript required (JupyterLab's sanitizer strips JS from HTML output).
"""

from __future__ import annotations

import re
from html import escape
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import quote

from pysdp.catalog import get_catalog

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pandas as pd


SDP_BROWSER_BASE = "https://sdpbrowser.org/"


def _product_to_slug(product_name: str) -> str:
    """Convert a catalog Product name to a URL-safe slug.

    Mirrors ``stac-gen/lib/slugs.py::product_to_slug``.
    """
    slug = product_name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _browser_url(product_name: str) -> str:
    """Build an SDP Browser URL that opens this product as a map layer."""
    slug = _product_to_slug(product_name)
    layer_param = quote(f"id={slug}", safe="")
    return f"{SDP_BROWSER_BASE}#layers={layer_param}"


def _card_html(row: pd.Series, width: int) -> str:
    """Render one product card as pure HTML (no JavaScript)."""
    cat_id = escape(str(row.get("CatalogID", "")))
    product = escape(str(row.get("Product", "")))
    domain = escape(str(row.get("Domain", "")))
    resolution = escape(str(row.get("Resolution", "")))
    ts_type = escape(str(row.get("TimeSeriesType", "")))
    thumb = str(row.get("Thumbnail.URL", ""))
    browser_link = _browser_url(str(row.get("Product", "")))
    open_call = f"pysdp.open_raster(&quot;{cat_id}&quot;)"

    return f"""\
<div style="
    position: relative;
    border-radius: 8px;
    overflow: hidden;
    background: #1a1a2e;
    min-height: 170px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
">
    <img src="{thumb}"
         alt="{cat_id}"
         loading="lazy"
         style="
            width: 100%;
            display: block;
            min-height: 140px;
            object-fit: cover;
         "
    >
    <a href="{browser_link}"
       target="_blank"
       rel="noopener"
       title="Open in SDP Browser"
       style="
          position: absolute;
          top: 6px; right: 6px;
          background: rgba(0,0,0,0.6);
          color: white;
          text-decoration: none;
          padding: 3px 8px;
          border-radius: 4px;
          font-size: 11px;
          font-weight: 600;
       "
    >SDP Browser &nearr;</a>
    <div style="
        position: absolute;
        bottom: 0; left: 0; right: 0;
        background: linear-gradient(transparent 0%, rgba(0,0,0,0.88) 55%);
        padding: 30px 10px 8px 10px;
        color: white;
    ">
        <div style="font-size: 11px; opacity: 0.65; letter-spacing: 0.5px;">
            {cat_id}
        </div>
        <div style="
            font-weight: 600;
            font-size: 13px;
            line-height: 1.3;
            margin: 2px 0 3px 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        ">{product}</div>
        <div style="font-size: 11px; opacity: 0.7; margin-bottom: 4px;">
            {domain} &middot; {resolution} &middot; {ts_type}
        </div>
        <code style="
            display: block;
            background: rgba(255,255,255,0.1);
            color: #ccc;
            padding: 3px 6px;
            border-radius: 3px;
            font-size: 10px;
            user-select: all;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        ">{open_call}</code>
    </div>
</div>"""


def _grid_html(df: pd.DataFrame, *, columns: int, width: int, title: str | None) -> str:
    """Render the full grid as an HTML string."""
    cards = "\n".join(_card_html(row, width) for _, row in df.iterrows())
    title_html = ""
    if title:
        title_html = (
            f'<div style="font-family: -apple-system, BlinkMacSystemFont, '
            f"'Segoe UI', Roboto, sans-serif; font-size: 14px; "
            f'color: #888; margin-bottom: 10px;">'
            f"{escape(title)}</div>"
        )
    return f"""\
<div>
{title_html}
<div style="
    display: grid;
    grid-template-columns: repeat({columns}, minmax({width}px, 1fr));
    gap: 10px;
    max-width: {columns * (width + 20)}px;
">
{cards}
</div>
</div>"""


class CatalogBrowser:
    """A displayable grid of SDP product thumbnails.

    In Jupyter, this renders as an interactive HTML grid. The rendering
    uses ``IPython.display.HTML`` when available (via ``_ipython_display_``),
    which is more reliable than ``_repr_html_`` across JupyterLab versions.
    Outside notebooks, ``str(browser)`` returns the raw HTML string.
    """

    def __init__(self, html: str) -> None:
        self._html = html

    def _ipython_display_(self, **kwargs: object) -> None:
        """Jupyter display protocol — uses IPython.display.HTML for reliable rendering."""
        from IPython.display import HTML, display

        display(HTML(self._html))  # type: ignore[no-untyped-call]

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
    deprecated: bool | None = False,
    *,
    columns: int = 4,
    width: int = 220,
    source: Literal["packaged", "live"] = "packaged",
    max_products: int | None = None,
) -> CatalogBrowser:
    """Visual catalog browser — renders a thumbnail grid in Jupyter notebooks.

    Accepts the same filter arguments as :func:`get_catalog` and displays
    each matching product as a card with its thumbnail image + overlaid
    metadata (CatalogID, product name, domain, resolution, time-series type).

    Each card includes:

    - **"SDP Browser ↗"** link (top-right) — opens the product in the
      `SDP Browser <https://sdpbrowser.org/>`_ web map viewer.
    - **Code snippet** (bottom) — a selectable ``pysdp.open_raster("...")``
      call for quick copy-paste into a notebook cell.

    Parameters
    ----------
    domains, types, releases, timeseries_types, deprecated
        Same filters as :func:`get_catalog`.
    columns : int, default 4
        Number of columns in the grid.
    width : int, default 220
        Minimum width of each card in pixels.
    source : {"packaged", "live"}, default "packaged"
        Catalog source. ``"stac"`` is not supported here (thumbnails are
        derived from the CSV catalog's ``Data.URL`` column).
    max_products : int or None, default None
        Cap the number of products shown (useful for large result sets).
        ``None`` shows all matches.

    Returns
    -------
    CatalogBrowser
        An object that renders as an HTML grid in Jupyter (via
        ``_ipython_display_`` / ``_repr_html_``). Outside notebooks,
        cast to ``str`` for the raw HTML.

    Examples
    --------
    Browse all Upper Gunnison vegetation products:

    >>> import pysdp
    >>> pysdp.browse(domains=["UG"], types=["Vegetation"])  # doctest: +SKIP

    Show all topo products across every domain in a 3-column grid:

    >>> pysdp.browse(types=["Topo"], columns=3)  # doctest: +SKIP

    See Also
    --------
    get_catalog : Tabular catalog discovery (returns a DataFrame).
    """
    import pandas as pd

    # browse() only supports CSV-backed sources (not "stac"), so the return
    # is always a DataFrame. Cast to narrow the union type for mypy.
    df = cast(
        pd.DataFrame,
        get_catalog(
            domains=domains,
            types=types,
            releases=releases,
            timeseries_types=timeseries_types,
            deprecated=deprecated,
            source=source,
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
