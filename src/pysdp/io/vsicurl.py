"""GDAL VSICURL helpers for cloud-based COG access.

Phase 3 sets a minimal, safe set of GDAL env defaults for reading SDP COGs
off S3 without local downloads. Phase 7 (ROADMAP §Phase 7) upgrades these to
the full cloud-tuned set (HTTP/2, multiplex, retry tuning, worker-scoped
broadcast).

Principle (see ROADMAP §2 item 5): `os.environ.setdefault` only — never
clobber a value the user explicitly set.
"""

from __future__ import annotations

import os

from pysdp.constants import VSICURL_PREFIX

__all__ = ["VSICURL_PREFIX", "ensure_gdal_defaults", "gdal_defaults"]


def gdal_defaults() -> dict[str, str]:
    """Return the canonical GDAL-on-S3 env dict for SDP reads.

    Scoped via `rasterio.Env(**gdal_defaults())` inside pysdp readers so
    user overrides are preserved. Phase 7 extends this with HTTP/2 tuning.
    """
    return {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.tiff",
        "VSI_CACHE": "TRUE",
        "VSI_CACHE_SIZE": "5000000",
    }


def ensure_gdal_defaults() -> None:
    """Set SDP-appropriate GDAL env vars if not already present.

    Uses ``os.environ.setdefault`` so existing values survive. Safe to call
    multiple times; the first call wins.
    """
    for key, value in gdal_defaults().items():
        os.environ.setdefault(key, value)
