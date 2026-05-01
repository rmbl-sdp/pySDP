"""Discover available dates for SDP time-series products.

Ports rSDP's ``sdp_get_dates()``. Regular products (Yearly, Monthly,
Daily) compute dates deterministically from MinDate/MaxDate. Irregular
products (Weekly drone imagery) read from a baked manifest or query the
live STAC catalog.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Literal

from pysdp._catalog_data import load_manifests, lookup_catalog_row

if TYPE_CHECKING:
    from collections.abc import Sequence


def get_dates(
    catalog_id: str,
    *,
    source: Literal["auto", "stac", "manifest"] = "auto",
) -> Sequence[datetime.date]:
    """Discover available dates for an SDP time-series product.

    For regular products (Yearly, Monthly, Daily), dates are computed
    from the catalog's MinDate/MaxDate range. For irregular products
    (Weekly), dates come from the STAC catalog (online) or a baked
    manifest (offline).

    Parameters
    ----------
    catalog_id : str
        Six-character SDP catalog ID.
    source : {"auto", "stac", "manifest"}, default "auto"
        ``"auto"`` tries the baked manifest first, falls back to STAC.
        ``"stac"`` queries the live STAC catalog (requires network).
        ``"manifest"`` uses only the offline baked manifest.

    Returns
    -------
    list of datetime.date
        Sorted list of available dates.

    Examples
    --------
    >>> import pysdp
    >>> dates = pysdp.get_dates("R6D001")  # doctest: +SKIP
    >>> len(dates)  # doctest: +SKIP
    111

    >>> pysdp.get_dates("R4D001")  # Yearly → one date per year  # doctest: +SKIP
    """
    import pandas as pd

    row = lookup_catalog_row(catalog_id)
    ts_type = str(row["TimeSeriesType"])

    # Regular products: compute deterministically.
    if ts_type == "Single":
        return [pd.Timestamp(row["MinDate"]).date()]
    if ts_type == "Yearly":
        return [datetime.date(y, 1, 1) for y in range(int(row["MinYear"]), int(row["MaxYear"]) + 1)]
    if ts_type == "Monthly":
        return [d.date() for d in pd.date_range(row["MinDate"], row["MaxDate"], freq="MS")]
    if ts_type == "Daily":
        return [d.date() for d in pd.date_range(row["MinDate"], row["MaxDate"], freq="D")]

    # Irregular products (Weekly): manifest or STAC.
    if source in ("auto", "manifest"):
        manifests = load_manifests()
        if catalog_id in manifests:
            return manifests[catalog_id]
        if source == "manifest":
            raise ValueError(
                f"No manifest found for {catalog_id!r}. Run "
                f"`scripts/update_catalog.py` to regenerate."
            )

    if source in ("auto", "stac"):
        dates = _dates_from_stac(catalog_id, row)
        if dates:
            return dates
        if source == "stac":
            raise ValueError("Failed to retrieve dates from STAC. Check network connectivity.")

    raise ValueError(
        f"No date information available for {catalog_id!r}. "
        f"Try source='stac' with network, or regenerate manifests."
    )


def _dates_from_stac(catalog_id: str, row: object) -> list[datetime.date]:
    """Query the STAC catalog for item dates (network required)."""
    import re

    import pystac

    from pysdp.stac import STAC_ROOT_URL

    try:
        root = pystac.Catalog.from_file(STAC_ROOT_URL)
        # Walk to find the collection for this product.
        for child in root.get_children():
            for collection in child.get_children():
                items = list(collection.get_items())
                item_ids = [i.id for i in items]
                if any(catalog_id in iid for iid in item_ids):
                    dates: list[datetime.date] = []
                    for item in items:
                        m = re.search(r"\d{4}-\d{2}-\d{2}", item.id)
                        if m:
                            dates.append(datetime.date.fromisoformat(m.group()))
                    return sorted(dates)
    except Exception:  # noqa: BLE001
        pass
    return []


__all__ = ["get_dates"]
