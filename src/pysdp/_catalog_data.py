"""Loads the packaged SDP catalog CSV snapshot; fetches live from S3 on request.

Corresponds to rSDP's `sysdata.rda` + `data-raw/SDP_catalog.R`.
Implementation lands in Phase 1.

Staleness check: emits a UserWarning when the packaged snapshot is older
than `SDP_STALENESS_MONTHS` (default 6; env-configurable). See SPEC.md §4.1.
"""

from __future__ import annotations

import os

STALENESS_MONTHS_DEFAULT: int = 6
STALENESS_MONTHS_ENV: str = "SDP_STALENESS_MONTHS"


def _staleness_months_threshold() -> int:
    raw = os.environ.get(STALENESS_MONTHS_ENV)
    if raw is None:
        return STALENESS_MONTHS_DEFAULT
    try:
        return int(raw)
    except ValueError:
        return STALENESS_MONTHS_DEFAULT
