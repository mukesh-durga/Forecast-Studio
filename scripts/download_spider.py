#!/usr/bin/env python3
"""Locate (or explain how to obtain) the official Spider dev set.

The Spider dataset is released by Yale under its own license and is distributed
as a manual download (Google Drive / the official Spider page) — it is **not**
redistributed here and cannot be fetched non-interactively. This script does not
scrape or bypass that; it checks whether you already have Spider locally and, if
not, prints exact setup instructions.

    backend/.venv/bin/python scripts/download_spider.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

INSTRUCTIONS = """\
Spider dev set not found.

Manual setup (one time):
  1. Download the official Spider archive from the Spider project page:
       https://yale-lily.github.io/spider   (see "Download" — Yale license)
  2. Unzip it. You need a directory that contains BOTH:
       - dev.json
       - database/   (one <db_id>/<db_id>.sqlite per database)
  3. Point the harness at it, either by placing it at:
       {default}
     or by exporting its path:
       export SPIDER_DIR=/absolute/path/to/spider
  4. Run the subset evaluation:
       backend/.venv/bin/python scripts/run_spider_subset.py --limit 50

Only the dev set is needed. No Spider files are committed to this repo.
"""


def find() -> Path | None:
    candidates = []
    if os.getenv("SPIDER_DIR"):
        candidates.append(Path(os.environ["SPIDER_DIR"]))
    candidates += [REPO / "spider", REPO / "spider" / "spider", REPO / "data" / "spider"]
    for c in candidates:
        if (c / "dev.json").exists() and (c / "database").is_dir():
            return c
    return None


def main() -> None:
    found = find()
    if found is not None:
        db_count = sum(1 for _ in (found / "database").glob("*/*.sqlite"))
        print(f"Found Spider dev set at: {found}")
        print(f"  dev.json present, {db_count} database(s) detected.")
        print("Run:  backend/.venv/bin/python scripts/run_spider_subset.py --limit 50")
        return
    print(INSTRUCTIONS.format(default=REPO / "spider"), file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
