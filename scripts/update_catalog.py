#!/usr/bin/env python3
"""Refresh the packaged SDP catalog CSV snapshot.

Ports rSDP's `data-raw/SDP_catalog.R`. Downloads the canonical product-table
CSV from S3, writes it to `src/pysdp/data/`, and removes any older snapshots
from that directory (the loader assumes exactly one CSV lives there).

After running, commit the new CSV and push a pysdp release.

Usage
-----
    python scripts/update_catalog.py                       # default URL
    python scripts/update_catalog.py --url <csv-url>       # override
    python scripts/update_catalog.py --dry-run             # report; no writes
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.request import urlopen

DEFAULT_URL = (
    "https://rmbl-sdp.s3.us-east-2.amazonaws.com/data_products/SDP_product_table_04_14_2026.csv"
)
FILENAME_RE = re.compile(r"^SDP_product_table_\d{2}_\d{2}_\d{4}\.csv$")
DATA_DIR = Path(__file__).resolve().parent.parent / "src" / "pysdp" / "data"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_URL, help="CSV URL to fetch")
    ap.add_argument("--dry-run", action="store_true", help="Report actions; make no writes")
    args = ap.parse_args()

    filename = args.url.rsplit("/", 1)[-1]
    if not FILENAME_RE.match(filename):
        print(
            f"URL filename does not match pattern SDP_product_table_MM_DD_YYYY.csv: {filename!r}",
            file=sys.stderr,
        )
        return 2

    dest = DATA_DIR / filename
    print(f"Source: {args.url}")
    print(f"Dest:   {dest}")

    if args.dry_run:
        print("[dry-run] no changes made.")
        return 0

    with urlopen(args.url) as resp:  # noqa: S310 (explicit URL; not user input)
        content: bytes = resp.read()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    print(f"Wrote {len(content):,} bytes.")

    for old in DATA_DIR.glob("SDP_product_table_*.csv"):
        if old.name != filename:
            print(f"Removed older snapshot: {old.name}")
            old.unlink()

    return 0


if __name__ == "__main__":
    sys.exit(main())
