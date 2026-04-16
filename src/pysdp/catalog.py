"""Catalog discovery and metadata retrieval.

Corresponds to rSDP's `sdp_get_catalog()` and `sdp_get_metadata()`.
Implementation lands in Phase 1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pandas as pd
    import pystac


def get_catalog(
    domains: Sequence[str] | None = None,
    types: Sequence[str] | None = None,
    releases: Sequence[str] | None = None,
    timeseries_types: Sequence[str] | None = None,
    deprecated: bool = False,
    *,
    source: Literal["packaged", "live", "stac"] = "packaged",
) -> pd.DataFrame | pystac.Catalog:
    """Discover SDP datasets by filtering the product catalog.

    See SPEC.md §4.1.
    """
    raise NotImplementedError("Phase 1: catalog discovery")


def get_metadata(
    catalog_id: str,
    *,
    as_dict: bool = True,
) -> dict[str, Any] | Any:
    """Fetch QGIS-style XML metadata for one SDP dataset.

    See SPEC.md §4.1.
    """
    raise NotImplementedError("Phase 1: catalog metadata")
