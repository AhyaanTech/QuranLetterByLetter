#!/usr/bin/env python3
"""Load quran_offline.db into PostgreSQL using bulk COPY.

Run after build_db.py + build_letters.py have produced data/output/quran_offline.db.

Requires psycopg v3:
    uv add psycopg[binary]

Usage:
    uv run scripts/load_to_postgres.py --drop
    uv run scripts/load_to_postgres.py --dsn postgresql://user:pass@host/db --drop
    uv run scripts/load_to_postgres.py --truncate --tables words ayahs
    uv run scripts/load_to_postgres.py --dry-run
    POSTGRES_DSN=postgresql://localhost/quran uv run scripts/load_to_postgres.py --drop

DSN resolution order:
    1. --dsn flag
    2. $POSTGRES_DSN environment variable
    3. $DATABASE_URL environment variable
    4. postgresql://localhost/quran (default)
"""

import os
import sys
import time
import sqlite3
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Load .env from project root (if present) without overriding existing env vars
_ENV_FILE = Path(__file__).parent.parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

from quran_db.config import OUTPUT_DB, DIACRITIC_FLAGS
from quran_db.pg_schema import TABLES, TABLE_ORDER, INDEXES, SERIAL_TABLES

try:
    import psycopg
except ImportError:
    print("[ERR] psycopg not installed.")
    print("      Run: uv add psycopg[binary]")
    sys.exit(1)


_DEFAULT_DSN = "postgresql://localhost/quran"
_DSN_ENV_VARS = ["POSTGRES_DSN", "DATABASE_URL"]

# Columns that are stored as 0/1 integers in SQLite but map to BOOLEAN in PostgreSQL
_BOOL_COLUMNS: dict[str, frozenset[str]] = {
    "mushaf_pages": frozenset({"is_centered"}),
    "letter_breakdown": frozenset(DIACRITIC_FLAGS) | frozenset({"is_hamza_variant"}),
}

# Column to ORDER BY when reading from SQLite (metadata has no id)
_ORDER_BY: dict[str, str] = {t: "id" for t in TABLE_ORDER}
_ORDER_BY["metadata"] = "key"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resolve_dsn(dsn_arg: str | None) -> str:
    if dsn_arg:
        return dsn_arg
    for var in _DSN_ENV_VARS:
        val = os.environ.get(var)
        if val:
            return val
    return _DEFAULT_DSN


def _make_transform(col_names: list[str], bool_cols: frozenset[str]):
    """Return a row-transform function, or None if no booleans to convert."""
    bool_indices = [i for i, name in enumerate(col_names) if name in bool_cols]
    if not bool_indices:
        return None

    def transform(row: tuple) -> tuple:
        row = list(row)
        for i in bool_indices:
            if row[i] is not None:
                row[i] = bool(row[i])
        return tuple(row)

    return transform


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------


def create_schema(pg_conn: "psycopg.Connection", tables: list[str]) -> None:
    with pg_conn.cursor() as cur:
        for table in tables:
            cur.execute(TABLES[table])


def drop_tables(pg_conn: "psycopg.Connection", tables: list[str]) -> None:
    """Drop tables in reverse FK order."""
    with pg_conn.cursor() as cur:
        for table in reversed(tables):
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def truncate_tables(pg_conn: "psycopg.Connection", tables: list[str]) -> None:
    if not tables:
        return
    with pg_conn.cursor() as cur:
        cur.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")


def create_indexes(pg_conn: "psycopg.Connection") -> None:
    with pg_conn.cursor() as cur:
        for sql in INDEXES:
            cur.execute(sql)


def reset_sequence(pg_conn: "psycopg.Connection", table: str) -> None:
    """Reset a BIGSERIAL sequence to MAX(id) after bulk load via COPY."""
    with pg_conn.cursor() as cur:
        cur.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), MAX(id)) FROM {table}"
        )


# ---------------------------------------------------------------------------
# Per-table loading
# ---------------------------------------------------------------------------


def load_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn: "psycopg.Connection",
    table: str,
) -> int:
    """COPY one table from SQLite to PostgreSQL. Returns rows loaded."""
    order_by = _ORDER_BY[table]
    sqlite_cur = sqlite_conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}")
    col_names = [desc[0] for desc in sqlite_cur.description]
    cols_sql = ", ".join(col_names)

    bool_cols = _BOOL_COLUMNS.get(table, frozenset())
    transform = _make_transform(col_names, bool_cols)

    count = 0
    copy_sql = f"COPY {table} ({cols_sql}) FROM STDIN"

    with pg_conn.cursor() as cur:
        with cur.copy(copy_sql) as copy:
            for row in sqlite_cur:
                if transform:
                    row = transform(row)
                copy.write_row(row)
                count += 1

    if table in SERIAL_TABLES and count > 0:
        reset_sequence(pg_conn, table)

    return count


def dry_run_counts(sqlite_conn: sqlite3.Connection, tables: list[str]) -> None:
    total = 0
    for table in tables:
        count = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<25} {count:>10,} rows")
        total += count
    print(f"\n  {'TOTAL':<25} {total:>10,} rows")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load quran_offline.db into PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  uv run scripts/load_to_postgres.py --drop
  uv run scripts/load_to_postgres.py --dsn postgresql://user:pass@host/db --drop
  uv run scripts/load_to_postgres.py --truncate --tables words ayahs
  uv run scripts/load_to_postgres.py --no-indexes --drop
  uv run scripts/load_to_postgres.py --dry-run
        """,
    )
    parser.add_argument(
        "--dsn",
        help=f"PostgreSQL DSN (default: $POSTGRES_DSN or {_DEFAULT_DSN})",
    )
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop and recreate all tables before loading",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate tables before loading (preserves schema)",
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        metavar="TABLE",
        help=f"Load specific tables only (default: all). Valid: {', '.join(TABLE_ORDER)}",
    )
    parser.add_argument(
        "--no-indexes",
        action="store_true",
        help="Skip index creation after loading",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQLite row counts only, no PostgreSQL writes",
    )
    args = parser.parse_args()

    if not OUTPUT_DB.exists():
        print(f"[ERR] Database not found: {OUTPUT_DB}")
        print("      Run 'uv run scripts/build_db.py --full' then 'uv run scripts/build_letters.py'")
        return 1

    tables = args.tables if args.tables else list(TABLE_ORDER)
    unknown = [t for t in tables if t not in TABLES]
    if unknown:
        print(f"[ERR] Unknown table(s): {', '.join(unknown)}")
        print(f"      Valid: {', '.join(TABLE_ORDER)}")
        return 1

    dsn = resolve_dsn(args.dsn)

    print("=" * 60)
    print("Quran PostgreSQL Loader")
    print("=" * 60)
    print(f"Source:  {OUTPUT_DB}")
    if not args.dry_run:
        print(f"Target:  {dsn}")
    print(f"Tables:  {', '.join(tables)}")
    if args.dry_run:
        print("Mode:    dry run (no writes)")
    print()

    sqlite_conn = sqlite3.connect(OUTPUT_DB)
    sqlite_conn.row_factory = None  # plain tuples for COPY

    if args.dry_run:
        dry_run_counts(sqlite_conn, tables)
        sqlite_conn.close()
        return 0

    t_start = time.monotonic()

    try:
        with psycopg.connect(dsn, autocommit=False) as pg_conn:
            if args.drop:
                print("Dropping existing tables...")
                drop_tables(pg_conn, TABLE_ORDER)
                pg_conn.commit()
                print("Creating schema...")
                create_schema(pg_conn, TABLE_ORDER)
                pg_conn.commit()
            elif args.truncate:
                print("Truncating tables...")
                truncate_tables(pg_conn, tables)
                pg_conn.commit()

            for table in tables:
                t0 = time.monotonic()
                label = f"Loading {table}..."
                print(f"{label:<35}", end="", flush=True)
                count = load_table(sqlite_conn, pg_conn, table)
                pg_conn.commit()
                elapsed = time.monotonic() - t0
                print(f"{count:>10,} rows  ({elapsed:.1f}s)")

            if not args.no_indexes:
                t0 = time.monotonic()
                print(f"{'Creating indexes...':<35}", end="", flush=True)
                create_indexes(pg_conn)
                pg_conn.commit()
                elapsed = time.monotonic() - t0
                print(f"{'done':>10}       ({elapsed:.1f}s)")

    except psycopg.OperationalError as e:
        print(f"\n[ERR] Could not connect to PostgreSQL: {e}")
        print(f"      DSN: {dsn}")
        sqlite_conn.close()
        return 1

    sqlite_conn.close()

    total_elapsed = time.monotonic() - t_start
    print(f"\nDone. Total: {total_elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
