"""Load the packaged SDP catalog snapshot; optionally refetch live from S3.

Corresponds to rSDP's `sysdata.rda` + `data-raw/SDP_catalog.R`. See SPEC.md §4.1.

The packaged snapshot filename encodes its date as ``SDP_product_table_MM_DD_YYYY.csv``.
A ``UserWarning`` is emitted when the snapshot is older than ``SDP_STALENESS_MONTHS``
(default 6; env-configurable) to nudge users to `source="live"` or an upgrade.
"""

from __future__ import annotations

import datetime
import importlib.resources
import io
import os
import re
import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from importlib.abc import Traversable

    import pandas as pd


STALENESS_MONTHS_DEFAULT: int = 6
STALENESS_MONTHS_ENV: str = "SDP_STALENESS_MONTHS"

_FILENAME_DATE_RE = re.compile(r"^SDP_product_table_(\d{2})_(\d{2})_(\d{4})\.csv$")
_PACKAGED_CSV_PREFIX = "SDP_product_table_"
_LIVE_URL_BASE = "https://rmbl-sdp.s3.us-east-2.amazonaws.com/data_products/"


def _packaged_csv_resource() -> Traversable:
    """Return the single packaged catalog CSV resource inside pysdp.data."""
    pkg = importlib.resources.files("pysdp.data")
    matches = sorted(
        (
            p
            for p in pkg.iterdir()
            if p.name.startswith(_PACKAGED_CSV_PREFIX) and p.name.endswith(".csv")
        ),
        key=lambda p: p.name,
    )
    if not matches:
        raise RuntimeError(
            "No packaged SDP catalog CSV found under pysdp/data/. "
            "Run `python scripts/update_catalog.py` to fetch one."
        )
    if len(matches) > 1:
        raise RuntimeError(
            f"Multiple packaged SDP catalog CSVs found: {[m.name for m in matches]!r}. "
            "The loader expects exactly one; delete all but the newest."
        )
    return matches[0]


def snapshot_date(filename: str) -> datetime.date | None:
    """Parse the embedded date from a packaged-CSV filename, or `None` if it doesn't match."""
    m = _FILENAME_DATE_RE.match(filename)
    if m is None:
        return None
    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return datetime.date(year, month, day)


def _staleness_months_threshold() -> int:
    raw = os.environ.get(STALENESS_MONTHS_ENV)
    if raw is None:
        return STALENESS_MONTHS_DEFAULT
    try:
        return int(raw)
    except ValueError:
        return STALENESS_MONTHS_DEFAULT


def _emit_staleness_warning_if_needed(
    csv_date: datetime.date | None,
    *,
    today: datetime.date | None = None,
) -> None:
    if csv_date is None:
        return
    today = today if today is not None else datetime.date.today()
    age_days = (today - csv_date).days
    threshold_months = _staleness_months_threshold()
    if age_days > threshold_months * 30:
        age_months = max(1, round(age_days / 30.44))
        warnings.warn(
            f"Packaged SDP catalog is {age_months} months old "
            f"(dated {csv_date.isoformat()}). Consider "
            f"`get_catalog(source='live')` or `pip install -U pysdp`.",
            UserWarning,
            stacklevel=3,
        )


def _parse_sdp_dates(series: pd.Series) -> pd.Series:
    """Parse SDP date strings, handling both ``m/d/y`` and ``m/d/Y`` formats.

    Mirrors rSDP's ``.parse_sdp_date`` in ``R/sdp_catalog_functions.R``.
    The upstream CSV mixes both formats across rows; we detect by the length
    of the year component rather than relying on ``strptime`` fall-through
    (which would silently parse ``"18"`` as year 18 AD under ``%Y``).
    """
    import pandas as pd

    non_null = series.notna()
    has_4digit = series.astype("string").str.contains(r"/\d{4}$", regex=True, na=False)

    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    mask_4d = non_null & has_4digit
    mask_2d = non_null & ~has_4digit
    if mask_4d.any():
        out.loc[mask_4d] = pd.to_datetime(series.loc[mask_4d], format="%m/%d/%Y", errors="coerce")
    if mask_2d.any():
        out.loc[mask_2d] = pd.to_datetime(series.loc[mask_2d], format="%m/%d/%y", errors="coerce")
    return out


def _read_catalog_csv(buffer: io.BytesIO) -> pd.DataFrame:
    import pandas as pd

    df = pd.read_csv(buffer)

    # Normalize the `Deprecated` column to real Python bools. Pandas may
    # auto-parse the "TRUE"/"FALSE" strings (R's uppercase convention) to
    # bools on some versions; on others they stay as strings. Handle both.
    if df["Deprecated"].dtype != bool:
        df["Deprecated"] = (
            df["Deprecated"].astype(str).str.upper().map({"TRUE": True, "FALSE": False})
        )
    if df["Deprecated"].isna().any():
        bad = df.loc[df["Deprecated"].isna(), "CatalogID"].tolist()
        raise ValueError(f"Unparsable Deprecated values for CatalogIDs: {bad!r}")
    df["Deprecated"] = df["Deprecated"].astype(bool)
    df["MinDate"] = _parse_sdp_dates(df["MinDate"])
    df["MaxDate"] = _parse_sdp_dates(df["MaxDate"])
    return df


def load_packaged_catalog(*, emit_warning: bool = True) -> pd.DataFrame:
    """Return the packaged SDP catalog snapshot as a DataFrame.

    Attaches ``df.attrs['snapshot_date']`` (``datetime.date | None``) and
    ``df.attrs['snapshot_filename']`` (``str``) for downstream error messages.
    Emits a ``UserWarning`` if the snapshot is older than the configured
    staleness threshold.
    """
    resource = _packaged_csv_resource()
    with resource.open("rb") as fh:
        df = _read_catalog_csv(io.BytesIO(fh.read()))
    csv_date = snapshot_date(resource.name)
    df.attrs["snapshot_date"] = csv_date
    df.attrs["snapshot_filename"] = resource.name
    if emit_warning:
        _emit_staleness_warning_if_needed(csv_date)
    return df


def live_catalog_url() -> str:
    """Return the URL to fetch the canonical live catalog CSV from S3.

    The URL is derived from the packaged snapshot filename. When a new
    catalog is published upstream, `scripts/update_catalog.py` rotates the
    packaged file; both `source="packaged"` and `source="live"` then point
    at the new file automatically.
    """
    return _LIVE_URL_BASE + _packaged_csv_resource().name


def load_live_catalog() -> pd.DataFrame:
    """Fetch the live catalog CSV from S3 (bypasses the packaged snapshot)."""
    import requests

    url = live_catalog_url()
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = _read_catalog_csv(io.BytesIO(resp.content))
    df.attrs["snapshot_date"] = snapshot_date(url.rsplit("/", 1)[-1])
    df.attrs["snapshot_filename"] = url.rsplit("/", 1)[-1]
    return df
