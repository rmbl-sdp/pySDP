"""Package constants for pysdp.

Values mirror the internal constants in rSDP's R/constants.R.
"""

from __future__ import annotations

from typing import Final

SDP_CRS: Final[str] = "EPSG:32613"
"""Coordinate reference system for all SDP raster products (UTM zone 13N)."""

VSICURL_PREFIX: Final[str] = "/vsicurl/"
"""Prefix used by GDAL's virtual file system for HTTPS-hosted datasets."""

DOMAINS: Final[tuple[str, ...]] = ("UG", "UER", "GT", "GMUG")
"""Spatial domains available in the SDP."""

TYPES: Final[tuple[str, ...]] = (
    "Mask",
    "Topo",
    "Vegetation",
    "Hydro",
    "Planning",
    "Radiation",
    "Snow",
    "Climate",
    "Imagery",
    "Supplemental",
)
"""Dataset type categories."""

RELEASES: Final[tuple[str, ...]] = (
    "Basemaps",
    "Release1",
    "Release2",
    "Release3",
    "Release4",
    "Release5",
    "Release6",
)
"""Dataset release cohorts."""

TIMESERIES_TYPES: Final[tuple[str, ...]] = (
    "Single",
    "Yearly",
    "Seasonal",
    "Monthly",
    "Weekly",
    "Daily",
)
"""Time-series structure types for SDP datasets."""

CATALOG_ID_NCHAR: Final[int] = 6
"""Length of a valid SDP Catalog ID (e.g., 'R3D009', 'BM012')."""
