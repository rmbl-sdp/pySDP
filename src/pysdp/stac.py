"""STAC catalog access.

Wraps `pystac` / `pystac-client` for the SDP's static STAC v1 catalog.
Implementation lands in Phase 1 (read path).
"""

from __future__ import annotations

STAC_ROOT_URL = "https://rmbl-sdp.s3.us-east-2.amazonaws.com/stac/v1/catalog.json"
