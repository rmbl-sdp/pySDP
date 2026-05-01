"""pysdp — Native Python interface for the RMBL Spatial Data Platform."""

from __future__ import annotations

try:
    from pysdp._version import __version__
except ImportError:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    try:
        __version__ = _pkg_version("pysdp")
    except PackageNotFoundError:
        __version__ = "0.0.0+unknown"

from pysdp.browse import browse
from pysdp.catalog import get_catalog, get_metadata
from pysdp.constants import DOMAINS, RELEASES, SDP_CRS, TIMESERIES_TYPES, TYPES
from pysdp.dates import get_dates
from pysdp.download import download
from pysdp.extract import extract_points, extract_polygons
from pysdp.raster import open_raster, open_stack

__all__ = [
    "DOMAINS",
    "RELEASES",
    "SDP_CRS",
    "TIMESERIES_TYPES",
    "TYPES",
    "__version__",
    "browse",
    "download",
    "extract_points",
    "extract_polygons",
    "get_catalog",
    "get_dates",
    "get_metadata",
    "open_raster",
    "open_stack",
]
