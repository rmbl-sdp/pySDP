"""Catalog discovery and per-dataset metadata retrieval.

Ports rSDP's `sdp_get_catalog()` and `sdp_get_metadata()`. See SPEC.md §4.1.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Literal

from pysdp._catalog_data import (
    load_live_catalog,
    load_packaged_catalog,
    lookup_catalog_row,
)
from pysdp.constants import (
    DOMAINS,
    RELEASES,
    TIMESERIES_TYPES,
    TYPES,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pandas as pd
    import pystac


def _validate_filter(values: Sequence[str] | None, valid: tuple[str, ...], name: str) -> None:
    if values is None:
        return
    invalid = [v for v in values if v not in valid]
    if invalid:
        raise ValueError(f"Invalid {name}: {invalid!r}. Valid values are: {list(valid)!r}")


def _apply_filters(
    df: pd.DataFrame,
    *,
    domains: Sequence[str] | None,
    types: Sequence[str] | None,
    releases: Sequence[str] | None,
    timeseries_types: Sequence[str] | None,
    deprecated: bool | None,
) -> pd.DataFrame:
    """Apply the standard catalog filters. Pure; no I/O. Testable with synthetic DataFrames."""
    import pandas as pd

    mask = pd.Series(True, index=df.index)
    if domains is not None:
        mask &= df["Domain"].isin(list(domains))
    if types is not None:
        mask &= df["Type"].isin(list(types))
    if releases is not None:
        mask &= df["Release"].isin(list(releases))
    if timeseries_types is not None:
        mask &= df["TimeSeriesType"].isin(list(timeseries_types))
    if deprecated is not None:
        mask &= df["Deprecated"] == deprecated
    out = df[mask].reset_index(drop=True)
    # Preserve snapshot metadata across filters (df[mask] loses attrs).
    out.attrs.update(df.attrs)
    return out


def get_catalog(
    domains: Sequence[str] | None = None,
    types: Sequence[str] | None = None,
    releases: Sequence[str] | None = None,
    timeseries_types: Sequence[str] | None = None,
    deprecated: bool | None = False,
    *,
    source: Literal["packaged", "live", "stac"] = "packaged",
) -> pd.DataFrame | pystac.Catalog:
    """Discover SDP datasets by filtering the product catalog.

    Parameters
    ----------
    domains, types, releases, timeseries_types
        Filter values; ``None`` means no filter on that field. Invalid values
        raise ``ValueError`` against the canonical vocabularies in
        ``pysdp.constants``.
    deprecated
        ``False`` (default) returns only current datasets; ``True`` returns
        only deprecated ones; ``None`` returns both.
    source
        ``"packaged"`` (default, offline) filters the CSV snapshot shipped
        with pysdp and emits a ``UserWarning`` if older than
        ``SDP_STALENESS_MONTHS`` (default 6). ``"live"`` refetches the CSV
        from S3. ``"stac"`` returns the static STAC v1 catalog as a
        ``pystac.Catalog`` (filter args are ignored; use pystac traversal).

    Returns
    -------
    pandas.DataFrame | pystac.Catalog
        A filtered DataFrame for the CSV-backed sources; a ``pystac.Catalog``
        for ``source="stac"``.
    """
    if source == "stac":
        from pysdp.stac import get_stac_catalog

        if any(v is not None for v in (domains, types, releases, timeseries_types)):
            warnings.warn(
                "Filter arguments are ignored when source='stac'. "
                "Use pystac traversal to filter the returned catalog.",
                UserWarning,
                stacklevel=2,
            )
        return get_stac_catalog()

    _validate_filter(domains, DOMAINS, "domains")
    _validate_filter(types, TYPES, "types")
    _validate_filter(releases, RELEASES, "releases")
    _validate_filter(timeseries_types, TIMESERIES_TYPES, "timeseries_types")

    if source == "packaged":
        df = load_packaged_catalog()
    elif source == "live":
        df = load_live_catalog()
    else:
        raise ValueError(f"Unknown source: {source!r}. Must be 'packaged', 'live', or 'stac'.")

    return _apply_filters(
        df,
        domains=domains,
        types=types,
        releases=releases,
        timeseries_types=timeseries_types,
        deprecated=deprecated,
    )


def get_metadata(
    catalog_id: str,
    *,
    as_dict: bool = True,
) -> dict[str, Any] | Any:
    """Fetch the QGIS-style XML metadata for one SDP dataset.

    Parameters
    ----------
    catalog_id
        Six-character SDP catalog ID (e.g., ``"R3D009"``).
    as_dict
        If True (default), parse the XML into a nested dict via ``xmltodict``.
        If False, return the parsed ``lxml.etree._Element``.

    Raises
    ------
    ValueError
        If ``catalog_id`` is not exactly six characters.
    KeyError
        If ``catalog_id`` is not in the packaged catalog; the error message
        suggests ``source='live'`` or an upgrade.
    """
    import requests

    row = lookup_catalog_row(catalog_id)
    resp = requests.get(row["Metadata.URL"], timeout=30)
    resp.raise_for_status()

    if as_dict:
        import xmltodict

        return xmltodict.parse(resp.content)
    from lxml import etree

    return etree.fromstring(resp.content)
