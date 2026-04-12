#!/usr/bin/env python3
"""Command line interface for database building and validation."""

import sys
import argparse
from pathlib import Path

from .database import (
    connect_output, init_output_db, attach_source_databases,
    validate_source_db, get_schema_info
)
from .builders import TableBuilder
from .validators import DatabaseValidator
from .config import DB_WORDS, DB_LAYOUT, DB_TAJWEED, OUTPUT_DB


def build_database() -> bool:
    """Build the complete database from source files."""
    print("=" * 60)
    print("Quran Database Builder v2.0")
    print("=" * 60)

    # Validate sources (Tajweed is optional)
    try:
        validate_source_db(DB_WORDS, "Words")
        validate_source_db(DB_LAYOUT, "Layout")
        print(f"[OK] Found words DB: {DB_WORDS}")
        print(f"[OK] Found layout DB: {DB_LAYOUT}")

        if DB_TAJWEED.exists():
            print(f"[OK] Found Tajweed DB: {DB_TAJWEED}")
        else:
            print(f"[WARN] Tajweed DB not found: {DB_TAJWEED}")
            print(f"       Download it to enable Tajweed mode")
    except FileNotFoundError as e:
        print(f"[ERR] {e}")
        return False

    # Initialize and build
    init_output_db()

    with connect_output() as conn:
        attach_source_databases(conn)

        builder = TableBuilder(conn)
        stats = builder.build_all()

        conn.commit()

        print("\n" + "=" * 60)
        print("Build Complete!")
        print("=" * 60)
        print(f"Output: {OUTPUT_DB}")
        print(f"Size: {OUTPUT_DB.stat().st_size / 1024 / 1024:.2f} MB")
        print("\nTables created:")
        for table, count in stats.items():
            if table not in ["pages"]:
                print(f"  {table:20} {count:>10,}")

    return True


def validate_database() -> bool:
    """Validate existing database integrity."""
    if not OUTPUT_DB.exists():
        print(f"[ERR] Database not found: {OUTPUT_DB}")
        print("Run with --build first")
        return False

    with connect_output() as conn:
        validator = DatabaseValidator(conn)
        validator.validate_all()
        all_passed = validator.print_summary()

    return all_passed


def show_schema() -> None:
    """Display database schema."""
    if not OUTPUT_DB.exists():
        print(f"[ERR] Database not found: {OUTPUT_DB}")
        return

    with connect_output() as conn:
        tables = get_schema_info(conn)

        print("=" * 60)
        print("Database Schema")
        print("=" * 60)
        print(f"\nDatabase: {OUTPUT_DB}")
        print(f"Size: {OUTPUT_DB.stat().st_size / 1024 / 1024:.2f} MB")
        print(f"\nTables ({len(tables)}):")

        for table_name, columns in sorted(tables.items()):
            count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            print(f"\n  {table_name} ({count:,} rows):")
            for col in columns:
                print(f"    - {col}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Build and validate Quran offline database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run scripts/build_db.py --build          # Build database
  uv run scripts/build_db.py --validate       # Validate only
  uv run scripts/build_db.py --full           # Build + validate
  uv run scripts/build_db.py --schema         # Show schema
        """
    )

    parser.add_argument(
        "--build", "-b",
        action="store_true",
        help="Build database from source files"
    )
    parser.add_argument(
        "--validate", "-v",
        action="store_true",
        help="Validate existing database"
    )
    parser.add_argument(
        "--full", "-f",
        action="store_true",
        help="Build and validate (full pipeline)"
    )
    parser.add_argument(
        "--schema", "-s",
        action="store_true",
        help="Show database schema"
    )

    args = parser.parse_args()

    # Default action if no args
    if not any([args.build, args.validate, args.full, args.schema]):
        args.full = True

    success = True

    if args.schema:
        show_schema()
        return 0

    if args.full or args.build:
        success = build_database() and success

    if args.full or args.validate:
        success = validate_database() and success

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
