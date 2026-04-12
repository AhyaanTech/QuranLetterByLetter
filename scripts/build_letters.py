#!/usr/bin/env python3
"""Build letter breakdown table.

Run this after build_db.py to generate character-level analysis.

Usage:
    uv run scripts/build_letters.py           # Build letter breakdown
    uv run scripts/build_letters.py --stats   # Show statistics
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from quran_db.database import connect_output
from quran_db.letter_builder import LetterBreakdownBuilder
from quran_db.validators import DatabaseValidator
from quran_db.config import DIACRITIC_FLAGS
from quran_db.config import OUTPUT_DB


def build_letters(run_integrity: bool = True) -> bool:
    """Build letter breakdown table.

    Args:
        run_integrity: If True, run round-trip integrity tests after building
    """
    if not OUTPUT_DB.exists():
        print(f"[ERR] Database not found: {OUTPUT_DB}")
        print("Run 'uv run scripts/build_db.py' first")
        return False

    print("=" * 60)
    print("Letter Breakdown Builder")
    print("=" * 60)

    with connect_output() as conn:
        builder = LetterBreakdownBuilder(conn)
        stats = builder.build()

        print("\n" + "=" * 60)
        print("Build Complete!")
        print("=" * 60)
        print(f"Words processed: {stats['words_processed']:,}")
        print(f"Letters inserted: {stats['letters_inserted']:,}")
        if stats["words_processed"] > 0:
            avg_letters = stats["letters_inserted"] / stats["words_processed"]
            print(f"Average letters per word: {avg_letters:.1f}")
        else:
            print("Average letters per word: N/A (no words processed)")

        # Run integrity tests if requested
        if run_integrity:
            print("\n")
            validator = DatabaseValidator(conn)
            tests_passed = validator.validate_round_trip_integrity()

            if not tests_passed:
                print("\n⚠️  WARNING: Integrity tests failed!")
                print("    The letter breakdown may have data loss issues.")
                return False

    return True


def show_stats():
    """Show letter breakdown statistics."""
    if not OUTPUT_DB.exists():
        print(f"[ERR] Database not found: {OUTPUT_DB}")
        return False

    with connect_output() as conn:
        cursor = conn.cursor()

        # Check if table exists
        exists = cursor.execute("""
            SELECT name FROM sqlite_master WHERE type='table' AND name='letter_breakdown'
        """).fetchone()

        if not exists:
            print("[ERR] letter_breakdown table not found")
            return False

        print("=" * 60)
        print("Letter Breakdown Statistics")
        print("=" * 60)

        cursor.execute("SELECT COUNT(*) FROM letter_breakdown")
        total_letters = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT word_id) FROM letter_breakdown")
        total_words = cursor.fetchone()[0]

        print(f"\nTotal letters: {total_letters:,}")
        print(f"Total words: {total_words:,}")
        if total_words > 0:
            print(f"Average: {total_letters / total_words:.1f} letters/word")
        else:
            print("Average: N/A (no words)")

        # Diacritic statistics - show all flags that have counts > 0
        print("\nDiacritic frequencies (showing all present):")

        # Single query: SUM each flag column in one pass instead of N round trips
        sums_sql = ", ".join(f"SUM({flag})" for flag in DIACRITIC_FLAGS)
        row = cursor.execute(f"SELECT {sums_sql} FROM letter_breakdown").fetchone()
        for flag, count in zip(DIACRITIC_FLAGS, row):
            if count:
                pct = (count / total_letters) * 100
                readable_name = flag.replace("has_", "").replace("_", " ").title()
                print(f"  {readable_name:25} {count:>8,} ({pct:5.1f}%)")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Build letter breakdown table",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run scripts/build_letters.py              # Build + run integrity tests
  uv run scripts/build_letters.py --no-check   # Build without integrity tests
  uv run scripts/build_letters.py --stats      # Show statistics only
  uv run scripts/build_letters.py --integrity  # Run round-trip integrity tests only
  uv run scripts/build_letters.py --ayah-words # Run ayah-word concatenation test
  uv run scripts/build_letters.py --schema     # Run schema validation only
  uv run scripts/build_letters.py --all-tests  # Run all tests
        """,
    )
    parser.add_argument(
        "--stats", "-s", action="store_true", help="Show statistics only"
    )
    parser.add_argument(
        "--no-check", "-n", action="store_true", help="Skip integrity tests after build"
    )
    parser.add_argument(
        "--integrity",
        "-i",
        action="store_true",
        help="Run round-trip integrity tests only",
    )
    parser.add_argument(
        "--schema", action="store_true", help="Run schema validation only"
    )
    parser.add_argument(
        "--all-tests", "-a", action="store_true", help="Run all tests (no build)"
    )
    parser.add_argument(
        "--ayah-words",
        action="store_true",
        help="Run ayah-word concatenation test only",
    )

    args = parser.parse_args()

    if args.stats:
        return 0 if show_stats() else 1
    elif args.integrity:
        return 0 if run_integrity_only() else 1
    elif args.schema:
        return 0 if run_schema_only() else 1
    elif args.ayah_words:
        return 0 if run_ayah_words_only() else 1
    elif args.all_tests:
        return 0 if run_all_tests() else 1
    else:
        return 0 if build_letters(run_integrity=not args.no_check) else 1


def run_integrity_only() -> bool:
    """Run round-trip integrity tests on existing database."""
    if not OUTPUT_DB.exists():
        print(f"[ERR] Database not found: {OUTPUT_DB}")
        print("Run 'uv run scripts/build_letters.py' first to build the table")
        return False

    print("=" * 60)
    print("Running Round-Trip Integrity Tests Only")
    print("=" * 60)

    with connect_output() as conn:
        validator = DatabaseValidator(conn)
        return validator.validate_round_trip_integrity()


def run_schema_only() -> bool:
    """Run schema validation on existing database."""
    if not OUTPUT_DB.exists():
        print(f"[ERR] Database not found: {OUTPUT_DB}")
        print("Run 'uv run scripts/build_db.py' first to build the database")
        return False

    print("=" * 60)
    print("Running Schema Validation Only")
    print("=" * 60)

    with connect_output() as conn:
        validator = DatabaseValidator(conn)
        return validator.validate_schema()


def run_ayah_words_only() -> bool:
    """Run ayah-word concatenation test on existing database."""
    if not OUTPUT_DB.exists():
        print(f"[ERR] Database not found: {OUTPUT_DB}")
        print("Run 'uv run scripts/build_db.py' first to build the database")
        return False

    print("=" * 60)
    print("Running Ayah-Word Concatenation Test Only")
    print("=" * 60)

    with connect_output() as conn:
        validator = DatabaseValidator(conn)
        return validator.validate_ayah_word_concatenation()


def run_all_tests() -> bool:
    """Run all tests on existing database."""
    if not OUTPUT_DB.exists():
        print(f"[ERR] Database not found: {OUTPUT_DB}")
        print("Run 'uv run scripts/build_db.py' first to build the database")
        return False

    print("=" * 60)
    print("Running All Tests")
    print("=" * 60)

    with connect_output() as conn:
        validator = DatabaseValidator(conn)

        schema_passed = validator.validate_schema()
        integrity_passed = validator.validate_round_trip_integrity()
        ayah_words_passed = validator.validate_ayah_word_concatenation()
        subfield_passed = validator.validate_subfield_consistency()
        contiguity_passed = validator.validate_letter_index_contiguity()
        flags_passed = validator.validate_diacritic_flags()
        word_pos_passed = validator.validate_word_position_ordering()

        # Summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"  Schema Validation:        {'[PASS]' if schema_passed else '[FAIL]'}")
        print(
            f"  Round-Trip Integrity:     {'[PASS]' if integrity_passed else '[FAIL]'}"
        )
        print(
            f"  Ayah-Word Concatenation:  {'[PASS]' if ayah_words_passed else '[SKIP/FAIL]'}"
        )
        print(
            f"  Sub-field Consistency:    {'[PASS]' if subfield_passed else '[FAIL]'}"
        )
        print(
            f"  Letter Index Contiguity:  {'[PASS]' if contiguity_passed else '[FAIL]'}"
        )
        print(
            f"  Diacritic Flag Columns:   {'[PASS]' if flags_passed else '[FAIL]'}"
        )
        print(
            f"  Word Position Ordering:   {'[PASS]' if word_pos_passed else '[FAIL]'}"
        )
        print("=" * 60)

        return (
            schema_passed
            and integrity_passed
            and ayah_words_passed
            and subfield_passed
            and contiguity_passed
            and flags_passed
            and word_pos_passed
        )


if __name__ == "__main__":
    sys.exit(main())
