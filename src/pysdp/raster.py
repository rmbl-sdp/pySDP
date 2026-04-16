"""Lazy cloud raster access.

Corresponds to rSDP's `sdp_get_raster()`. Adds `open_stack()` for
multi-product loads. Implementation lands in Phase 3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import datetime
    import os
    from collections.abc import Sequence

    import xarray as xr


def open_raster(
    catalog_id: str | None = None,
    url: str | None = None,
    *,
    years: Sequence[int] | None = None,
    months: Sequence[int] | None = None,
    date_start: str | datetime.date | None = None,
    date_end: str | datetime.date | None = None,
    chunks: dict[str, int] | Literal["auto"] | None = "auto",
    download: bool = False,
    download_path: str | os.PathLike[str] | None = None,
    overwrite: bool = False,
    verbose: bool = True,
) -> xr.Dataset:
    """Open an SDP raster as a lazy `xarray.Dataset`.

    See SPEC.md §4.2.
    """
    raise NotImplementedError("Phase 3: raster access")


def open_stack(
    catalog_ids: Sequence[str],
    *,
    years: Sequence[int] | None = None,
    months: Sequence[int] | None = None,
    date_start: str | datetime.date | None = None,
    date_end: str | datetime.date | None = None,
    chunks: dict[str, int] | Literal["auto"] | None = "auto",
    align: Literal["exact", "reproject"] = "exact",
    verbose: bool = True,
) -> xr.Dataset:
    """Open multiple SDP products as a single `xarray.Dataset`.

    One data variable per product. See SPEC.md §4.2.
    """
    raise NotImplementedError("Phase 3: multi-product stacks")
