"""Bulk download of SDP datasets to local disk.

Corresponds to rSDP's `download_data()`. Implementation lands in Phase 5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import os
    from collections.abc import Sequence

    import pandas as pd


def download(
    urls: str | Sequence[str] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    *,
    catalog_ids: str | Sequence[str] | None = None,
    overwrite: bool = False,
    resume: bool = True,
    max_workers: int = 8,
    return_status: bool = True,
) -> pd.DataFrame | None:
    """Download SDP datasets to local disk.

    See SPEC.md §4.4.
    """
    raise NotImplementedError("Phase 5: download")
