#!/usr/bin/env python3
"""Docker entrypoint: runs the full pipeline and loads data into PostgreSQL.

Steps:
    1. build_db.py --full   (words, ayahs, surahs, mushaf_pages, metadata)
    2. build_letters.py     (letter_breakdown)
    3. load_to_postgres.py  (bulk COPY into PostgreSQL)

Environment variables:
    POSTGRES_DSN  / DATABASE_URL  — PostgreSQL connection string (required)

Example:
    docker run --rm -e POSTGRES_DSN=postgresql://user:pass@host/db <image>
"""

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent


def step(script: str, *args: str) -> None:
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *args])
    if r.returncode != 0:
        sys.exit(r.returncode)


def main() -> None:
    print("=== Step 1: build_db.py --full ===", flush=True)
    step("build_db.py", "--full")

    print("=== Step 2: build_letters.py ===", flush=True)
    step("build_letters.py")

    print("=== Step 3: load_to_postgres.py --drop ===", flush=True)
    step("load_to_postgres.py", "--drop")

    print("=== Pipeline complete ===", flush=True)


if __name__ == "__main__":
    main()
