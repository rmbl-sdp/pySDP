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

    pySDP ships with a snapshot of the SDP product catalog baked in; filtering
    is instantaneous and works offline. ``source="live"`` refetches the
    canonical CSV from S3 (useful when the packaged snapshot lags a recent
    catalog update). ``source="stac"`` returns the SDP's static STAC v1
    catalog as a ``pystac.Catalog``, which composes with the broader STAC
    ecosystem.

    Parameters
    ----------
    domains : sequence of str, optional
        Spatial domains to include (``"UG"``, ``"UER"``, ``"GT"``, ``"GMUG"``).
        See ``pysdp.DOMAINS`` for the canonical list. ``None`` (default)
        returns every domain.
    types : sequence of str, optional
        Dataset type categories (e.g., ``"Vegetation"``, ``"Topo"``,
        ``"Climate"``, ``"Snow"``). See ``pysdp.TYPES``. ``None`` returns
        all types.
    releases : sequence of str, optional
        Dataset release cohorts (``"Release1"``..``"Release5"``,
        ``"Basemaps"``). See ``pysdp.RELEASES``. ``None`` returns all.
    timeseries_types : sequence of str, optional
        One or more of ``"Single"``, ``"Yearly"``, ``"Monthly"``,
        ``"Daily"``, ``"Seasonal"``. See ``pysdp.TIMESERIES_TYPES``.
        ``None`` returns all.
    deprecated : bool or None, default False
        ``False`` returns only current datasets. ``True`` returns only
        deprecated ones. ``None`` returns both.
    source : {"packaged", "live", "stac"}, default "packaged"
        Where to pull the catalog from. See Notes.

    Returns
    -------
    pandas.DataFrame or pystac.Catalog
        For CSV-backed sources, a DataFrame with one row per dataset and
        columns matching the SDP product-table schema (``CatalogID``,
        ``Release``, ``Type``, ``Product``, ``Domain``, ``Resolution``,
        ``Deprecated``, ``MinDate``, ``MaxDate``, ``MinYear``, ``MaxYear``,
        ``TimeSeriesType``, ``DataType``, ``DataUnit``,
        ``DataScaleFactor``, ``DataOffset``, ``Data.URL``, ``Metadata.URL``).
        For ``source="stac"``, a ``pystac.Catalog`` rooted at the SDP's
        static STAC v1 catalog.

    Raises
    ------
    ValueError
        If any filter argument contains a value outside its canonical
        vocabulary, or if ``source`` isn't one of the three valid options.

    Warns
    -----
    UserWarning
        When ``source="packaged"`` and the packaged snapshot is older than
        ``SDP_STALENESS_MONTHS`` months (default 6; env-configurable). The
        warning suggests ``source="live"`` or a pysdp upgrade.

    Notes
    -----
    The packaged CSV is refreshed on each pysdp release. ``source="live"``
    hits the S3-hosted canonical CSV directly, so it's always as fresh as
    upstream. ``source="stac"`` ignores filter arguments — use pystac
    traversal to filter the returned catalog. The catalog is browsable at
    `radiantearth's STAC Browser
    <https://radiantearth.github.io/stac-browser/#/external/rmbl-sdp.s3.us-east-2.amazonaws.com/stac/v1/catalog.json>`_.

    Examples
    --------
    Get every current dataset:

    >>> import pysdp
    >>> cat = pysdp.get_catalog()  # doctest: +SKIP
    >>> cat.shape  # doctest: +SKIP
    (140, 18)

    Filter to Upper Gunnison vegetation products:

    >>> veg = pysdp.get_catalog(domains=["UG"], types=["Vegetation"])  # doctest: +SKIP

    Find all yearly time-series products across every domain:

    >>> yearly = pysdp.get_catalog(timeseries_types=["Yearly"])  # doctest: +SKIP

    Return both current and deprecated entries:

    >>> all_rows = pysdp.get_catalog(deprecated=None)  # doctest: +SKIP

    See Also
    --------
    get_metadata : Fetch detailed XML metadata for one dataset.
    open_raster : Open a catalog entry as a lazy ``xarray.Dataset``.
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

    Each SDP product has a companion metadata XML document on S3 that
    describes provenance, sensor details, processing history, and other
    long-form context. This function fetches that XML over HTTP and parses
    it.

    Parameters
    ----------
    catalog_id : str
        Six-character SDP catalog ID (e.g., ``"R3D009"``, ``"BM012"``).
    as_dict : bool, default True
        If ``True``, return a nested ``dict`` parsed via ``xmltodict`` —
        convenient for scripting. If ``False``, return the parsed
        ``lxml.etree._Element`` — better for XPath queries.

    Returns
    -------
    dict or lxml.etree._Element
        Parsed metadata. For dict output, the top-level key is typically
        ``"qgis"`` (reflecting the document's QGIS metadata schema).

    Raises
    ------
    ValueError
        If ``catalog_id`` isn't exactly six characters.
    KeyError
        If ``catalog_id`` isn't in the packaged catalog. The message
        includes the snapshot date and suggests ``source="live"`` or an upgrade.
    requests.HTTPError
        If the XML URL returns a non-2xx status (rare; implies an
        upstream data-hosting issue).

    Examples
    --------
    Get the metadata for the UG 3 m bare-earth DEM as a dict:

    >>> import pysdp
    >>> meta = pysdp.get_metadata("R3D009")  # doctest: +SKIP
    >>> meta["qgis"]["abstract"]  # doctest: +SKIP
    'This 3 m resolution digital elevation model...'

    See Also
    --------
    get_catalog : Discover catalog IDs by filtering.
    open_raster : Open a catalog entry as a raster.
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
