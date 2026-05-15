"""Client-side helpers for the SDP data-products issue tracker.

Open issues for SDP datasets are tracked at ``rmbl-sdp/sdp-products`` — a
dedicated repo, separate from the pysdp / rSDP code repos, so that dataset
feedback and client-library bugs stay cleanly separated.

This module is a behavior-preserving port of rSDP's ``R/sdp_issues.R``.
Issue-tracker *infrastructure* (Issue Forms, the GH Actions workflow that
patches STAC ``rmbl:open_issues_count`` fields, the validation bot) lives
in the upstream repo and in ``rSDP/stac-gen/`` — pysdp only consumes the
resulting URLs and API.
"""

from __future__ import annotations

import datetime
import json
import os
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import quote

if TYPE_CHECKING:
    import pandas as pd


ISSUES_REPO: str = "rmbl-sdp/sdp-products"
ISSUES_HTML_BASE: str = f"https://github.com/{ISSUES_REPO}"
ISSUES_API_BASE: str = f"https://api.github.com/repos/{ISSUES_REPO}"
ISSUES_VALID_TYPES: tuple[str, ...] = (
    "incorrect-values",
    "missing-dates",
    "metadata-error",
    "acquisition-gap",
    "documentation",
    "other",
)
ISSUES_CACHE_TTL_SECS: int = 3600

IssueType = Literal[
    "incorrect-values",
    "missing-dates",
    "metadata-error",
    "acquisition-gap",
    "documentation",
    "other",
]


# Columns of the tidy DataFrame returned by `known_issues()`.
_ISSUES_COLUMNS: tuple[str, ...] = (
    "CatalogID",
    "number",
    "title",
    "type",
    "severity",
    "status",
    "created",
    "updated",
    "url",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def report_issue(
    catalog_id: str,
    *,
    type: IssueType | str | None = None,
    open: bool = True,
) -> str:
    """Report a data-quality issue with an SDP product.

    Opens the GitHub Issue Form for ``rmbl-sdp/sdp-products`` with the
    ``CatalogID`` (and optional ``issue_type``) pre-filled. Issues with the
    pysdp *package* itself should go to the pysdp repo instead; this
    function targets the dedicated *data-products* tracker.

    Parameters
    ----------
    catalog_id : str
        Six-character SDP CatalogID (e.g. ``"R3D009"``). Must match a
        current or deprecated entry; if it doesn't, a ``UserWarning`` is
        emitted but the URL is still built.
    type : str, optional
        Optional issue type. One of ``"incorrect-values"``,
        ``"missing-dates"``, ``"metadata-error"``, ``"acquisition-gap"``,
        ``"documentation"``, ``"other"``.
    open : bool, default True
        If ``True``, open the URL in the user's default browser. If
        ``False``, just return the URL.

    Returns
    -------
    str
        The prefilled issue-form URL.

    Raises
    ------
    ValueError
        If ``catalog_id`` isn't exactly six characters, or if ``type``
        isn't one of the valid values.

    Examples
    --------
    >>> import pysdp
    >>> pysdp.report_issue("R4D004")  # doctest: +SKIP
    >>> pysdp.report_issue("R3D009", type="metadata-error", open=False)  # doctest: +SKIP
    """
    import warnings

    from pysdp._catalog_data import load_packaged_catalog
    from pysdp.constants import CATALOG_ID_NCHAR

    if not isinstance(catalog_id, str) or len(catalog_id) != CATALOG_ID_NCHAR:
        raise ValueError(
            f"catalog_id must be a {CATALOG_ID_NCHAR}-char string, got {catalog_id!r}."
        )
    if type is not None and type not in ISSUES_VALID_TYPES:
        raise ValueError(f"`type` must be one of: {', '.join(ISSUES_VALID_TYPES)} (got {type!r}).")

    df = load_packaged_catalog(emit_warning=False)
    if catalog_id not in set(df["CatalogID"].astype(str)):
        warnings.warn(
            f"CatalogID {catalog_id!r} is not in the bundled catalog; filing anyway.",
            UserWarning,
            stacklevel=2,
        )

    params: list[tuple[str, str]] = [
        ("template", "dataset-issue.yml"),
        ("catalog_id", catalog_id),
    ]
    if type is not None:
        params.append(("issue_type", type))
    query = "&".join(f"{k}={quote(v, safe='')}" for k, v in params)
    url = f"{ISSUES_HTML_BASE}/issues/new?{query}"

    if open:
        webbrowser.open(url)
    return url


def known_issues(
    catalog_id: str | None = None,
    *,
    refresh: bool = False,
) -> pd.DataFrame:
    """List open data-quality issues for SDP products.

    Queries the GitHub REST API for open issues on
    ``rmbl-sdp/sdp-products`` and returns a tidy ``DataFrame``. Results are
    cached on disk for one hour (``ISSUES_CACHE_TTL_SECS``) to stay within
    GitHub's anonymous rate limit and keep interactive use responsive.

    Parameters
    ----------
    catalog_id : str, optional
        Optional CatalogID to filter to a single dataset. ``None``
        (default) returns all open issues.
    refresh : bool, default False
        If ``True``, bypass the on-disk cache and re-fetch from GitHub.

    Returns
    -------
    pandas.DataFrame
        One row per open issue with columns: ``CatalogID``, ``number``,
        ``title``, ``type``, ``severity``, ``status``, ``created``,
        ``updated``, ``url``. Returns an empty DataFrame (with the right
        columns) if there are no open issues, or if the API call fails
        offline and no cache is available.

    Notes
    -----
    Set ``GITHUB_TOKEN`` or ``GITHUB_PAT`` in your environment to bump the
    API rate limit from 60 requests/hr (anonymous) to 5000 requests/hr.

    Examples
    --------
    >>> import pysdp
    >>> pysdp.known_issues()  # doctest: +SKIP
    >>> pysdp.known_issues("R4D004")  # doctest: +SKIP
    >>> pysdp.known_issues(refresh=True)  # doctest: +SKIP
    """
    df = _fetch_open_issues(refresh=refresh)
    if catalog_id is not None:
        df = df[df["CatalogID"] == catalog_id].reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Internal: cache + GitHub fetch
# ---------------------------------------------------------------------------


def _cache_dir() -> Path:
    """Return the per-user cache directory for pysdp issues.

    Honors ``XDG_CACHE_HOME`` (used by Linux/macOS power users and CI), with
    a sensible fallback under ``~/.cache/pysdp``. Created on demand.
    """
    base = os.environ.get("XDG_CACHE_HOME")
    cache_dir = Path(base) / "pysdp" if base else Path.home() / ".cache" / "pysdp"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _cache_path() -> Path:
    return _cache_dir() / "open_issues.json"


def _empty_issues_frame() -> pd.DataFrame:
    import pandas as pd

    return pd.DataFrame(
        {
            "CatalogID": pd.Series(dtype="string"),
            "number": pd.Series(dtype="Int64"),
            "title": pd.Series(dtype="string"),
            "type": pd.Series(dtype="string"),
            "severity": pd.Series(dtype="string"),
            "status": pd.Series(dtype="string"),
            "created": pd.Series(dtype="datetime64[ns, UTC]"),
            "updated": pd.Series(dtype="datetime64[ns, UTC]"),
            "url": pd.Series(dtype="string"),
        }
    )


def _read_cache() -> tuple[datetime.datetime, pd.DataFrame] | None:
    """Return ``(fetched_at, df)`` from the cache, or ``None`` if absent/corrupt."""
    import pandas as pd

    path = _cache_path()
    if not path.exists():
        return None
    try:
        with path.open() as fh:
            payload = json.load(fh)
        fetched_at = datetime.datetime.fromisoformat(payload["fetched_at"])
        issues_records = payload["issues"]
    except (OSError, ValueError, KeyError):
        return None
    if not issues_records:
        return fetched_at, _empty_issues_frame()
    df = pd.DataFrame.from_records(issues_records)
    df["created"] = pd.to_datetime(df["created"], utc=True)
    df["updated"] = pd.to_datetime(df["updated"], utc=True)
    return fetched_at, df


def _write_cache(df: pd.DataFrame) -> None:
    payload = {
        "fetched_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "issues": _df_to_records(df),
    }
    path = _cache_path()
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w") as fh:
        json.dump(payload, fh)
    tmp.replace(path)


def _df_to_records(df: pd.DataFrame) -> list[dict[str, object]]:
    """Serialize the issues DataFrame to JSON-safe records.

    Timestamps are emitted as ISO-8601 strings so the JSON cache is
    human-readable and round-trips cleanly through ``read_cache()``.
    """
    import pandas as pd

    out: list[dict[str, object]] = []
    for _, row in df.iterrows():
        rec: dict[str, object] = {}
        for col in _ISSUES_COLUMNS:
            value = row.get(col)
            if isinstance(value, pd.Timestamp):
                rec[col] = value.isoformat()
            elif (
                value is None
                or (isinstance(value, float) and pd.isna(value))
                or pd.api.types.is_scalar(value)
                and pd.isna(value)
            ):
                rec[col] = None
            else:
                rec[col] = value if isinstance(value, int) else str(value)
        out.append(rec)
    return out


def _fetch_open_issues(*, refresh: bool = False) -> pd.DataFrame:
    """Read from cache (if fresh) or hit GitHub, with graceful offline fallback."""
    if not refresh:
        cached = _read_cache()
        if cached is not None:
            fetched_at, df = cached
            age = datetime.datetime.now(datetime.UTC) - fetched_at
            if age.total_seconds() < ISSUES_CACHE_TTL_SECS:
                return df

    try:
        df = _gh_fetch_issues_paginated()
    except Exception as exc:  # noqa: BLE001 — best-effort offline behavior
        import warnings

        warnings.warn(
            f"Could not fetch SDP open issues from GitHub: {exc}",
            UserWarning,
            stacklevel=3,
        )
        cached = _read_cache()
        return cached[1] if cached is not None else _empty_issues_frame()

    _write_cache(df)
    return df


def _gh_fetch_issues_paginated() -> pd.DataFrame:
    """Pull every open issue from the GitHub API (paginated)."""
    import requests

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "pysdp",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    per_page = 100
    page = 1
    all_issues: list[dict[str, object]] = []
    while True:
        url = f"{ISSUES_API_BASE}/issues"
        params: dict[str, str | int] = {
            "state": "open",
            "per_page": per_page,
            "page": page,
        }
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"GitHub API returned HTTP {resp.status_code}")
        chunk = resp.json()
        if not chunk:
            break
        all_issues.extend(chunk)
        if len(chunk) < per_page:
            break
        page += 1

    return _issues_to_dataframe(all_issues)


def _issues_to_dataframe(issues: list[dict[str, object]]) -> pd.DataFrame:
    """Turn a list of GitHub issue objects into a tidy DataFrame.

    The validation bot on ``sdp-products`` auto-applies ``product:<CATID>``,
    ``type:<...>``, ``severity:<...>``, and ``status:<...>`` labels. We peel
    those prefixes off into dedicated columns so users can filter on them
    directly.
    """
    import pandas as pd

    if not issues:
        return _empty_issues_frame()

    # GH lumps PRs into the issues endpoint; filter them out.
    issues = [i for i in issues if "pull_request" not in i]

    def _pick_label(labels: object, prefix: str) -> str | None:
        if not isinstance(labels, list):
            return None
        for lab in labels:
            if not isinstance(lab, dict):
                continue
            name = lab.get("name")
            if isinstance(name, str) and name.startswith(prefix):
                return name[len(prefix) :]
        return None

    df = pd.DataFrame(
        {
            "CatalogID": [_pick_label(i.get("labels"), "product:") for i in issues],
            "number": [int(i["number"]) if "number" in i else 0 for i in issues],  # type: ignore[call-overload]
            "title": [str(i.get("title", "")) for i in issues],
            "type": [_pick_label(i.get("labels"), "type:") for i in issues],
            "severity": [_pick_label(i.get("labels"), "severity:") for i in issues],
            "status": [_pick_label(i.get("labels"), "status:") for i in issues],
            "created": [i.get("created_at") for i in issues],
            "updated": [i.get("updated_at") for i in issues],
            "url": [str(i.get("html_url", "")) for i in issues],
        }
    )
    df["CatalogID"] = df["CatalogID"].astype("string")
    df["title"] = df["title"].astype("string")
    df["type"] = df["type"].astype("string")
    df["severity"] = df["severity"].astype("string")
    df["status"] = df["status"].astype("string")
    df["url"] = df["url"].astype("string")
    df["number"] = df["number"].astype("Int64")
    df["created"] = pd.to_datetime(df["created"], utc=True)
    df["updated"] = pd.to_datetime(df["updated"], utc=True)
    return df


def open_issue_counts(*, refresh: bool = False) -> pd.DataFrame:
    """Return per-CatalogID open-issue counts.

    Internal helper consumed by :func:`pysdp.get_catalog` and
    :func:`pysdp.browse` when called with ``with_issue_counts=True``.
    Always returns a DataFrame with columns ``CatalogID`` and
    ``OpenIssues`` — empty if no issues are known or the API is
    unreachable and no cache exists.
    """
    import pandas as pd

    issues = _fetch_open_issues(refresh=refresh)
    if issues.empty:
        return pd.DataFrame(
            {
                "CatalogID": pd.Series(dtype="string"),
                "OpenIssues": pd.Series(dtype="Int64"),
            }
        )
    issues = issues[issues["CatalogID"].notna()]
    counts = issues.groupby("CatalogID", dropna=True).size().reset_index(name="OpenIssues")
    counts["CatalogID"] = counts["CatalogID"].astype("string")
    counts["OpenIssues"] = counts["OpenIssues"].astype("Int64")
    return counts


def issues_search_url(catalog_id: str) -> str:
    """Build a GitHub issue-search URL filtered to one CatalogID's label."""
    label = quote(f"product:{catalog_id}", safe="")
    return f"{ISSUES_HTML_BASE}/issues?q=is%3Aissue+is%3Aopen+label%3A{label}"


__all__ = [
    "ISSUES_CACHE_TTL_SECS",
    "ISSUES_HTML_BASE",
    "ISSUES_REPO",
    "ISSUES_VALID_TYPES",
    "IssueType",
    "issues_search_url",
    "known_issues",
    "open_issue_counts",
    "report_issue",
]
