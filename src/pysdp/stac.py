"""STAC catalog access for the SDP static catalog.

Thin wrapper over `pystac.Catalog.from_file()`. The SDP publishes a static
STAC v1 catalog on S3; we read its root JSON and let callers traverse it
with pystac methods. See SPEC.md §4.1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pystac


STAC_ROOT_URL: str = "https://rmbl-sdp.s3.us-east-2.amazonaws.com/stac/v1/catalog.json"


def get_stac_catalog() -> pystac.Catalog:
    """Read and return the SDP static STAC v1 catalog as a `pystac.Catalog`.

    Raises
    ------
    pystac.STACError
        If the catalog JSON cannot be read (e.g., the catalog hasn't been
        synced to S3 yet).
    """
    import pystac

    return pystac.Catalog.from_file(STAC_ROOT_URL)
