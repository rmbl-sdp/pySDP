"""Bulk download of SDP datasets to local disk.

Ports rSDP's `download_data()`. See SPEC.md §4.4.

Primary backend: `requests` + `concurrent.futures.ThreadPoolExecutor`,
using only core pysdp dependencies. Higher-throughput backends
(`obstore`, `fsspec` + `s3fs`) are planned for Phase 7 when at-scale
download performance becomes a hot path (ROADMAP §Phase 7); for the
v0.1 use case — researchers pulling a handful of SDP products to local
disk — the threaded-requests path is plenty fast.
"""

from __future__ import annotations

import os
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pysdp._catalog_data import lookup_catalog_row
from pysdp.io.template import substitute_template

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pandas as pd


#: Files smaller than this (bytes) are treated as invalid/partial and
#: re-downloaded. Mirrors rSDP's ``file.size(...) > 1000`` heuristic.
_MIN_VALID_FILE_SIZE: int = 1000


def _emit(msg: str, verbose: bool) -> None:
    if verbose:
        print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# catalog_id → URL expansion
# ---------------------------------------------------------------------------


def _expand_catalog_id(catalog_id: str) -> list[str]:
    """Expand a catalog_id to its full set of `Data.URL`s.

    - Single: the lone Data.URL.
    - Yearly: one URL per catalog year (`MinYear`..`MaxYear`).
    - Monthly: one URL per catalog month between MinDate and MaxDate.
    - Daily: raises. Daily products expand to potentially thousands of
      files; we require explicit `urls=` to force users to be deliberate
      (matches rSDP's pattern of taking URLs, not catalog IDs, for downloads).
    """
    import pandas as pd

    row = lookup_catalog_row(catalog_id)
    ts_type = str(row["TimeSeriesType"])
    data_url = str(row["Data.URL"])

    if ts_type == "Single":
        return [data_url]

    if ts_type == "Yearly":
        years = list(range(int(row["MinYear"]), int(row["MaxYear"]) + 1))
        return substitute_template(data_url, year=years)

    if ts_type == "Monthly":
        months = pd.date_range(row["MinDate"], row["MaxDate"], freq="MS")
        return substitute_template(
            data_url,
            year=[d.strftime("%Y") for d in months],
            month=[d.strftime("%m") for d in months],
        )

    if ts_type == "Daily":
        days_between = (row["MaxDate"] - row["MinDate"]).days + 1
        raise ValueError(
            f"Cannot expand Daily catalog_id {catalog_id!r} via `catalog_ids=` "
            f"(would be ~{days_between} files). Pass explicit URLs via `urls=` "
            f"for selective daily-slice downloads, or open via "
            f"`pysdp.open_raster(...)` with a date range first."
        )

    raise ValueError(f"Unsupported TimeSeriesType for download: {ts_type!r}")


def _expand_catalog_ids(ids: str | Sequence[str]) -> list[str]:
    if isinstance(ids, str):
        ids = [ids]
    out: list[str] = []
    for cid in ids:
        out.extend(_expand_catalog_id(cid))
    return out


# ---------------------------------------------------------------------------
# File + backend helpers
# ---------------------------------------------------------------------------


def _is_valid_existing(path: Path) -> bool:
    return path.exists() and path.stat().st_size > _MIN_VALID_FILE_SIZE


def _download_one(url: str, dest: Path, *, resume: bool) -> dict[str, Any]:
    """Fetch a single URL to `dest`. Returns a status dict (never raises).

    `resume=True` uses an HTTP Range request to continue a partial download
    when a small partial file already exists at `dest`. Completed files
    (> _MIN_VALID_FILE_SIZE) are filtered out before reaching this function.
    """
    import requests

    headers: dict[str, str] = {}
    mode = "wb"
    # Resume (HTTP Range + append) only when there's a genuinely partial file
    # on disk (< _MIN_VALID_FILE_SIZE). A larger existing file here means the
    # caller passed overwrite=True and wants a fresh download — so we
    # truncate with mode="wb" rather than appending.
    if resume and dest.exists():
        existing_size = dest.stat().st_size
        if 0 < existing_size <= _MIN_VALID_FILE_SIZE:
            headers["Range"] = f"bytes={existing_size}-"
            mode = "ab"

    result: dict[str, Any] = {
        "url": url,
        "dest": str(dest),
        "success": False,
        "status": None,
        "size": 0,
        "error": None,
    }
    try:
        with requests.get(url, headers=headers, stream=True, timeout=60) as r:
            result["status"] = r.status_code
            r.raise_for_status()
            with open(dest, mode) as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        result["size"] = dest.stat().st_size
        result["success"] = True
    except Exception as exc:  # noqa: BLE001 — downloads fail for many reasons
        result["error"] = str(exc)
        if dest.exists():
            result["size"] = dest.stat().st_size
    return result


def _download_parallel(
    urls: Sequence[str],
    dests: Sequence[Path],
    *,
    max_workers: int,
    resume: bool,
) -> list[dict[str, Any]]:
    """Download multiple URLs concurrently via a ThreadPool.

    Phase 7 (ROADMAP) will add faster backends (obstore, fsspec+s3fs). For
    v0.1 this threaded-requests implementation is plenty fast for the
    researcher-pulls-a-handful-of-products use case.
    """
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_download_one, url, dest, resume=resume)
            for url, dest in zip(urls, dests, strict=True)
        ]
        return [f.result() for f in futures]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def download(
    urls: str | Sequence[str] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    *,
    catalog_ids: str | Sequence[str] | None = None,
    overwrite: bool = False,
    resume: bool = True,
    max_workers: int = 8,
    return_status: bool = True,
    verbose: bool = True,
) -> pd.DataFrame | None:
    """Download SDP COG(s) to a local directory.

    See SPEC.md §4.4.

    Parameters
    ----------
    urls, catalog_ids
        Exactly one is required. ``catalog_ids`` resolves via the packaged
        catalog (``Single`` → one URL; ``Yearly`` → all catalog years;
        ``Monthly`` → all catalog months; ``Daily`` raises because
        expansion is open-ended — pass explicit URLs instead).
    output_dir
        Directory where files land. Created if it doesn't exist. Required.
    overwrite
        ``False`` (default) skips files that already exist locally with
        size > 1 kB (matches rSDP's heuristic). ``True`` re-downloads them.
    resume
        ``True`` (default) attempts an HTTP Range resume when a small
        partial file exists at the destination.
    max_workers
        Parallelism for HTTP fetches (threaded requests).
    return_status
        If ``True`` (default), returns a ``pandas.DataFrame`` with one row
        per URL and columns ``[url, dest, success, status, size, error]``.
        If ``False``, returns ``None``.

    Returns
    -------
    pandas.DataFrame | None
    """
    import pandas as pd

    if urls is not None and catalog_ids is not None:
        raise ValueError("Specify `urls` OR `catalog_ids`, not both.")
    if urls is None and catalog_ids is None:
        raise ValueError("You must specify `urls` or `catalog_ids`.")
    if output_dir is None:
        raise ValueError("`output_dir` is required.")

    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    if catalog_ids is not None:
        url_list = _expand_catalog_ids(catalog_ids)
    elif isinstance(urls, str):
        url_list = [urls]
    else:
        url_list = list(urls) if urls is not None else []

    dest_paths = [output_path / Path(u).name for u in url_list]

    existing: list[dict[str, Any]] = []
    to_download_urls: list[str] = []
    to_download_dests: list[Path] = []
    for url, dest in zip(url_list, dest_paths, strict=True):
        if _is_valid_existing(dest) and not overwrite:
            existing.append(
                {
                    "url": url,
                    "dest": str(dest),
                    "success": True,
                    "status": "exists",
                    "size": dest.stat().st_size,
                    "error": None,
                }
            )
        else:
            to_download_urls.append(url)
            to_download_dests.append(dest)

    if existing:
        _emit(
            f"Skipping {len(existing)} existing file(s). Specify `overwrite=True` to re-download.",
            verbose,
        )
    if to_download_urls:
        _emit(
            f"Downloading {len(to_download_urls)} file(s) to {output_path}...",
            verbose,
        )

    download_results = _download_parallel(
        to_download_urls,
        to_download_dests,
        max_workers=max_workers,
        resume=resume,
    )

    failures = [r for r in download_results if not r["success"]]
    if failures:
        warnings.warn(
            f"Downloaded {len(download_results) - len(failures)} / "
            f"{len(download_results)} file(s) successfully; "
            f"{len(failures)} failed (see returned DataFrame for details).",
            UserWarning,
            stacklevel=2,
        )

    _emit("Download complete.", verbose)

    all_results = existing + download_results
    if return_status:
        return pd.DataFrame(all_results)
    return None


__all__ = ["download"]
