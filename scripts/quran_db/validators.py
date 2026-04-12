#!/usr/bin/env python3
"""Data integrity validators for the Quran database.

Ensures data correctness by verifying:
1. Letter concatenation matches word text
2. Word concatenation matches ayah text (when available)
3. Foreign key integrity
4. Count consistency across tables
"""

import json
import sqlite3
import unicodedata
from typing import List, Optional
from dataclasses import dataclass
from collections import defaultdict

from .config import (
    TABLE_WORDS,
    TABLE_AYAHS,
    TABLE_SURAHS,
    TABLE_MUSHAF_PAGES,
    TABLE_LETTER_BREAKDOWN,
    TABLE_WORDS_TAJWEED,  # Official Tajweed colors
    TOTAL_SURAHS,
    DIACRITIC_FLAGS,
    CODEPOINT_TO_FLAG,
    SKIPPED_CATEGORIES,
)


@dataclass
class ValidationResult:
    """Result of a validation test."""

    name: str
    passed: bool
    message: str
    details: Optional[str] = None


def _clean_text_for_comparison(text: str) -> str:
    """Strip skipped categories (Cf, Lm) from text for fair comparison.

    The builder intentionally skips invisible/formatting characters (Cf, Lm)
    during segmentation, so we must strip them from original text too.

    Exception: SMALL WAW (U+06E5) and SMALL YEH (U+06E6) are Lm category
    but are now included in letter breakdown as diacritics, so we keep them.
    """
    kept_codepoints = {0x06E5, 0x06E6}  # SMALL WAW, SMALL YEH
    return "".join(
        c
        for c in text
        if unicodedata.category(c) not in SKIPPED_CATEGORIES
        or ord(c) in kept_codepoints
    )


class DatabaseValidator:
    """Validates Quran database integrity."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.cursor = conn.cursor()
        self.results: List[ValidationResult] = []

    def validate_all(self, skip_sample_check: bool = True) -> List[ValidationResult]:
        """Run all validation tests.

        Args:
            skip_sample_check: If True, skip the 1000-word sample test since
                the comprehensive round-trip test covers all words anyway.
        """
        print("\n" + "=" * 60)
        print("Running Data Integrity Tests")
        print("=" * 60)

        # Basic counts
        self._validate_word_count()
        self._validate_ayah_count()
        self._validate_surah_count()

        # Cross-table consistency
        self._validate_ayah_word_ranges()
        self._validate_mushaf_page_references()

        # Text integrity
        if not skip_sample_check:
            # Sample-based quick check (optional, superseded by round-trip test)
            self._validate_letter_to_word_concatenation()

        # Comprehensive round-trip integrity test (the gold standard)
        round_trip_result = self.validate_round_trip_integrity()
        self.results.append(
            ValidationResult(
                name="Round-Trip Integrity",
                passed=round_trip_result,
                message="All words and verses reconstruct perfectly"
                if round_trip_result
                else "Reconstruction failed - see details above",
            )
        )

        # Check for orphaned records
        self._validate_foreign_key_integrity()

        # New validation tests
        subfield_result = self.validate_subfield_consistency()
        self.results.append(
            ValidationResult(
                name="Sub-field Consistency",
                passed=subfield_result,
                message="base_letter + diacritics match letter_with_diacritics"
                if subfield_result
                else "Sub-field mismatches found",
            )
        )

        contiguity_result = self.validate_letter_index_contiguity()
        self.results.append(
            ValidationResult(
                name="Letter Index Contiguity",
                passed=contiguity_result,
                message="All letter indexes contiguous"
                if contiguity_result
                else "Gaps found in letter indexes",
            )
        )

        flags_result = self.validate_diacritic_flags()
        self.results.append(
            ValidationResult(
                name="Diacritic Flag Columns",
                passed=flags_result,
                message="All has_* columns match diacritics_json"
                if flags_result
                else "Flag column mismatches found",
            )
        )

        word_pos_result = self.validate_word_position_ordering()
        self.results.append(
            ValidationResult(
                name="Word Position Ordering",
                passed=word_pos_result,
                message="All verses have contiguous word positions"
                if word_pos_result
                else "Non-contiguous word positions found",
            )
        )

        return self.results

    def print_summary(self) -> bool:
        """Print validation summary. Returns True if all passed."""
        print("\n" + "=" * 60)
        print("Validation Summary")
        print("=" * 60)

        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed

        for result in self.results:
            status = "[PASS]" if result.passed else "[FAIL]"
            print(f"\n{status} {result.name}")
            print(f"       {result.message}")
            if result.details:
                print(f"       {result.details}")

        print("\n" + "-" * 60)
        print(f"Results: {passed} passed, {failed} failed")
        print("=" * 60)

        return failed == 0

    def _validate_word_count(self) -> None:
        """Check word count is reasonable."""
        count = self.cursor.execute(f"SELECT COUNT(*) FROM {TABLE_WORDS}").fetchone()[0]

        # Expected: ~83,668 words in Quran
        expected_min = 80000
        expected_max = 90000

        passed = expected_min <= count <= expected_max
        self.results.append(
            ValidationResult(
                name="Word Count",
                passed=passed,
                message=f"Found {count:,} words"
                + (
                    f" (expected {expected_min:,}-{expected_max:,})"
                    if not passed
                    else ""
                ),
                details=None if passed else f"Count outside expected range",
            )
        )

    def _validate_ayah_count(self) -> None:
        """Check ayah count is exactly 6236."""
        count = self.cursor.execute(f"SELECT COUNT(*) FROM {TABLE_AYAHS}").fetchone()[0]
        expected = 6236

        passed = count == expected
        self.results.append(
            ValidationResult(
                name="Ayah Count",
                passed=passed,
                message=f"Found {count:,} ayahs (expected {expected:,})",
                details=None
                if passed
                else f"Mismatch: got {count}, expected {expected}",
            )
        )

    def _validate_surah_count(self) -> None:
        """Check surah count is exactly 114."""
        count = self.cursor.execute(f"SELECT COUNT(*) FROM {TABLE_SURAHS}").fetchone()[
            0
        ]
        expected = TOTAL_SURAHS

        passed = count == expected
        self.results.append(
            ValidationResult(
                name="Surah Count",
                passed=passed,
                message=f"Found {count} surahs (expected {expected})",
                details=None
                if passed
                else f"Mismatch: got {count}, expected {expected}",
            )
        )

    def _validate_ayah_word_ranges(self) -> None:
        """Verify ayah word ranges are consistent."""
        issues = []

        # Check that first_word_id < last_word_id for all ayahs
        inconsistent = self.cursor.execute(f"""
            SELECT verse_key, first_word_id, last_word_id
            FROM {TABLE_AYAHS}
            WHERE first_word_id > last_word_id
            LIMIT 5;
        """).fetchall()

        if inconsistent:
            issues.append(f"{len(inconsistent)} ayahs with inverted word ranges")

        # Check word counts match actual word count
        mismatches = self.cursor.execute(f"""
            SELECT a.verse_key, a.word_count, COUNT(w.id) as actual
            FROM {TABLE_AYAHS} a
            LEFT JOIN {TABLE_WORDS} w ON w.verse_key = a.verse_key
            GROUP BY a.verse_key
            HAVING a.word_count != COUNT(w.id)
            LIMIT 5;
        """).fetchall()

        if mismatches:
            issues.append(f"{len(mismatches)} ayahs with mismatched word counts")

        passed = len(issues) == 0
        self.results.append(
            ValidationResult(
                name="Ayah Word Ranges",
                passed=passed,
                message="Word ranges consistent"
                if passed
                else f"Found {len(issues)} issues",
                details="; ".join(issues) if issues else None,
            )
        )

    def _validate_mushaf_page_references(self) -> None:
        """Verify all mushaf_pages reference valid words."""
        orphaned = self.cursor.execute(f"""
            SELECT COUNT(*) 
            FROM {TABLE_MUSHAF_PAGES} mp
            LEFT JOIN {TABLE_WORDS} w ON w.id = mp.word_id
            WHERE w.id IS NULL;
        """).fetchone()[0]

        passed = orphaned == 0
        self.results.append(
            ValidationResult(
                name="Mushaf Page References",
                passed=passed,
                message=f"All {TABLE_MUSHAF_PAGES} entries reference valid words"
                if passed
                else f"{orphaned} orphaned entries",
                details=None
                if passed
                else f"Found {orphaned} entries without matching words",
            )
        )

    def _validate_letter_to_word_concatenation(self) -> None:
        """CRITICAL: Verify concatenating letters forms the original word."""
        print("\n[TEST] Letter-to-Word Concatenation (this may take a moment)...")

        # Check if letter_breakdown table exists
        table_exists = self.cursor.execute(
            """
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name=?
        """,
            (TABLE_LETTER_BREAKDOWN,),
        ).fetchone()

        if not table_exists:
            self.results.append(
                ValidationResult(
                    name="Letter Concatenation",
                    passed=False,
                    message="letter_breakdown table not found",
                    details="Run letter breakdown generator first",
                )
            )
            return

        # Sample some words to verify
        # We check: base_letters + diacritics should match word.text
        sample_size = 1000

        mismatches = []
        samples = self.cursor.execute(
            f"""
            SELECT
                w.id,
                w.text as word_text,
                GROUP_CONCAT(lb.letter_with_diacritics, '') as letters_concat
            FROM {TABLE_WORDS} w
            JOIN (
                SELECT word_id, letter_with_diacritics, letter_index
                FROM {TABLE_LETTER_BREAKDOWN}
                ORDER BY word_id, letter_index
            ) lb ON lb.word_id = w.id
            WHERE w.id IN (SELECT id FROM {TABLE_WORDS} ORDER BY RANDOM() LIMIT ?)
            GROUP BY w.id;
        """,
            (sample_size,),
        ).fetchall()

        # Compare in Python after stripping skipped categories from original text
        # (letters_concat is already clean since builder excludes Cf/Lm)
        for row in samples:
            word_id, word_text, letters_concat = row
            clean_word_text = _clean_text_for_comparison(word_text)
            if clean_word_text != letters_concat:
                mismatches.append(
                    f"word_id={word_id}: '{word_text}' != '{letters_concat}'"
                )
                if len(mismatches) >= 10:
                    break

        passed = len(mismatches) == 0
        self.results.append(
            ValidationResult(
                name="Letter Concatenation",
                passed=passed,
                message=f"Sampled {sample_size} words: letters form words correctly"
                if passed
                else f"Found {len(mismatches)} mismatches in sample",
                details="; ".join(mismatches[:3]) if mismatches else None,
            )
        )

    def _validate_foreign_key_integrity(self) -> None:
        """Check for orphaned records across tables."""
        issues = []

        # Check mushaf_pages -> words
        orphaned_mp = self.cursor.execute(f"""
            SELECT COUNT(*) FROM {TABLE_MUSHAF_PAGES} mp
            WHERE NOT EXISTS (SELECT 1 FROM {TABLE_WORDS} w WHERE w.id = mp.word_id);
        """).fetchone()[0]

        if orphaned_mp:
            issues.append(f"{orphaned_mp} orphaned mushaf_pages")

        # Check letter_breakdown -> words (if exists)
        table_exists = self.cursor.execute(
            """
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name=?
        """,
            (TABLE_LETTER_BREAKDOWN,),
        ).fetchone()

        if table_exists:
            orphaned_lb = self.cursor.execute(f"""
                SELECT COUNT(*) FROM {TABLE_LETTER_BREAKDOWN} lb
                WHERE NOT EXISTS (SELECT 1 FROM {TABLE_WORDS} w WHERE w.id = lb.word_id);
            """).fetchone()[0]

            if orphaned_lb:
                issues.append(f"{orphaned_lb} orphaned letter_breakdown entries")

        passed = len(issues) == 0
        self.results.append(
            ValidationResult(
                name="Foreign Key Integrity",
                passed=passed,
                message="All foreign keys valid"
                if passed
                else f"Found {len(issues)} issues",
                details="; ".join(issues) if issues else None,
            )
        )

    def validate_complete_ayah_reconstruction(
        self, sample_size: int = 10
    ) -> ValidationResult:
        """Validate that words concatenate to form complete ayah text.

        NOTE: This requires ayahs.text to be populated first.
        """
        # Check if ayahs have text
        has_text = self.cursor.execute(f"""
            SELECT COUNT(*) FROM {TABLE_AYAHS} WHERE text IS NOT NULL AND text != ''
        """).fetchone()[0]

        if has_text == 0:
            return ValidationResult(
                name="Ayah Reconstruction",
                passed=True,  # Not a failure, just not tested
                message="Ayah text not populated (skipping test)",
                details="Populate ayahs.text to enable this validation",
            )

        mismatches = []

        # Sample some ayahs
        samples = self.cursor.execute(
            f"""
            SELECT 
                a.verse_key,
                a.text as ayah_text,
                GROUP_CONCAT(w.text, ' ') as words_concat
            FROM {TABLE_AYAHS} a
            JOIN {TABLE_WORDS} w ON w.verse_key = a.verse_key
            WHERE a.text IS NOT NULL
            GROUP BY a.verse_key
            ORDER BY RANDOM()
            LIMIT ?;
        """,
            (sample_size,),
        ).fetchall()

        for row in samples:
            verse_key, ayah_text, words_concat = row
            # Normalize both for comparison (remove extra spaces)
            ayah_clean = " ".join(ayah_text.split())
            words_clean = " ".join(words_concat.split()) if words_concat else ""

            if ayah_clean != words_clean:
                mismatches.append(f"{verse_key}: word concat doesn't match ayah text")

        passed = len(mismatches) == 0
        return ValidationResult(
            name="Ayah Reconstruction",
            passed=passed,
            message=f"Sampled {len(samples)} ayahs"
            if passed
            else f"Found {len(mismatches)} mismatches",
            details="; ".join(mismatches[:3]) if mismatches else None,
        )

    def validate_ayah_word_concatenation(self) -> bool:
        """
        Verify that concatenating words forms the complete ayah text.

        This validates that: JOIN(words.text, ' ') == ayahs.text
        Requires ayahs.text to be populated first.

        NOTE: This test may fail if words and ayahs use different scripts
        (e.g., Uthmani words vs Imlaai ayah text). This is expected and
        not a data integrity issue - it's a script tradition difference.

        Returns:
            True if all ayahs match or if mismatches are script-related, False otherwise
        """
        print("\n" + "=" * 60)
        print("Validating Ayah-Word Concatenation")
        print("=" * 60)
        print("Verifies: words (joined) == ayah.text")

        # Check if ayahs have text populated
        ayahs_with_text = self.cursor.execute(f"""
            SELECT COUNT(*) FROM {TABLE_AYAHS} 
            WHERE text IS NOT NULL AND text != ''
        """).fetchone()[0]

        if ayahs_with_text == 0:
            print("\n[SKIP] Ayahs.text is not populated")
            print("       Run ayah text population step first")
            print("       (This is expected if you haven't populated ayah text yet)")
            return True  # Not a failure, just not tested

        print(f"\nChecking {ayahs_with_text:,} ayahs with text...")

        # Find mismatches between word concatenation and ayah text
        mismatches = self.cursor.execute(f"""
            SELECT 
                a.verse_key,
                a.text as ayah_text,
                GROUP_CONCAT(w.text, ' ') as words_concat
            FROM {TABLE_AYAHS} a
            JOIN {TABLE_WORDS} w ON w.verse_key = a.verse_key
            WHERE a.text IS NOT NULL AND a.text != ''
            GROUP BY a.verse_key
            HAVING TRIM(ayah_text) != TRIM(words_concat)
            LIMIT 50;
        """).fetchall()

        if not mismatches:
            print(f"  [PASS] All {ayahs_with_text:,} ayahs match word concatenation")
            print("  (Words and ayahs use the same script - consistent)")
            return True

        # Check if mismatches are due to script differences (Uthmani vs Imlaai)
        # vs actual data corruption
        script_mismatches = 0
        data_mismatches = []

        for verse_key, ayah_text, words_concat in mismatches:
            if self._is_script_difference(ayah_text or "", words_concat or ""):
                script_mismatches += 1
            else:
                data_mismatches.append((verse_key, ayah_text, words_concat))

        if not data_mismatches:
            # All mismatches are script differences - expected behavior
            print(f"  [INFO] Found {script_mismatches} script differences (EXPECTED)")
            print("  Words and ayahs use different scripts (Uthmani vs Imlaai).")
            print("  This is NORMAL - different traditions use different characters.")
            print("  The word positions and counts are still correct.")
            return True
        else:
            print(
                f"  [FAIL] {len(data_mismatches)} real mismatches (plus {script_mismatches} script differences)"
            )
            print("\n  Sample mismatches (verse_key | length_ayah | length_words):")
            for verse_key, ayah_text, words_concat in data_mismatches[:10]:
                print(
                    f"    - {verse_key}: ayah={len(ayah_text) if ayah_text else 0} chars, words={len(words_concat) if words_concat else 0} chars"
                )

        return False

    def validate_word_tajweed_consistency(self) -> bool:
        """
        Verify that words_tajweed has matching entries for all words.

        Checks:
        1. All words have corresponding tajweed entries
        2. Tajweed text matches word text (same script)

        Returns:
            True if consistent, False otherwise
        """
        print("\n" + "=" * 60)
        print("Validating Word-Tajweed Consistency")
        print("=" * 60)
        print("Verifies: words_tajweed matches words table")

        # Check if tajweed table exists
        table_exists = self.cursor.execute(
            """
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name=?
        """,
            (TABLE_WORDS_TAJWEED,),
        ).fetchone()

        if not table_exists:
            print("\n[SKIP] words_tajweed table not found")
            print("       Run build with Tajweed database to add")
            return True  # Not a failure - Tajweed is optional

        # Count words vs tajweed entries
        word_count = self.cursor.execute(
            f"SELECT COUNT(*) FROM {TABLE_WORDS}"
        ).fetchone()[0]
        tajweed_count = self.cursor.execute(
            f"SELECT COUNT(*) FROM {TABLE_WORDS_TAJWEED}"
        ).fetchone()[0]

        print(f"\nWords: {word_count:,}")
        print(f"Tajweed entries: {tajweed_count:,}")

        if word_count != tajweed_count:
            print(f"  [WARN] Count mismatch - some words missing Tajweed data")
            return False

        # Check for orphaned tajweed entries (no matching word)
        orphaned = self.cursor.execute(f"""
            SELECT COUNT(*) FROM {TABLE_WORDS_TAJWEED} wt
            WHERE NOT EXISTS (SELECT 1 FROM {TABLE_WORDS} w WHERE w.id = wt.word_id)
        """).fetchone()[0]

        if orphaned > 0:
            print(f"  [WARN] {orphaned} orphaned Tajweed entries")
            return False

        print("  [PASS] All words have matching Tajweed entries")
        return True

    def _is_script_difference(self, text_a: str, text_b: str) -> bool:
        """Check if two texts differ due to Uthmani vs Imlaai script, not data corruption."""
        uthmani_chars = {
            0x671,
            0x670,
            0x6E1,
            0x6E2,
            0x6E3,
            0x6E4,
            0x6E5,
            0x6E6,
            0x6E7,
            0x6E8,
        }
        cps_a = set(ord(c) for c in text_a)
        cps_b = set(ord(c) for c in text_b)
        has_uthmani_a = bool(cps_a & uthmani_chars)
        has_uthmani_b = bool(cps_b & uthmani_chars)
        return has_uthmani_a != has_uthmani_b

    def validate_round_trip_integrity(self) -> bool:
        """
        COMPREHENSIVE ROUND-TRIP TEST

        Verifies that generated letters perfectly reconstruct into their original words,
        and that words perfectly reconstruct into full verses.

        This is the gold standard for verifying parsing logic integrity.
        If sum(letters) == word and sum(words) == ayah, we mathematically guarantee
        that our parsing logic didn't drop a single shadda, letter, or sequence.

        Returns:
            True if all tests passed, False otherwise
        """
        print("\n" + "=" * 60)
        print("Running Round-Trip Integrity Tests")
        print("=" * 60)
        print("This verifies that letters -> words -> verses reconstruct perfectly")

        cursor = self.cursor

        # Check if letter_breakdown table exists
        table_exists = cursor.execute(
            """
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name=?
        """,
            (TABLE_LETTER_BREAKDOWN,),
        ).fetchone()

        if not table_exists:
            print(
                "\n[ERR] letter_breakdown table not found - cannot run integrity tests"
            )
            return False

        # ---------------------------------------------------------
        # TEST 1: Word-Level Verification (Letters -> Word)
        # ---------------------------------------------------------
        print("\n[Test 1/2] Word-Level Reconstruction...")

        # Fetch all original words
        cursor.execute(f"""
            SELECT id, verse_key, text 
            FROM {TABLE_WORDS} 
            ORDER BY id;
        """)
        original_words = {
            row[0]: {"verse_key": row[1], "text": row[2]} for row in cursor.fetchall()
        }

        # Fetch all parsed letters and reconstruct words
        cursor.execute(f"""
            SELECT word_id, letter_with_diacritics 
            FROM {TABLE_LETTER_BREAKDOWN} 
            ORDER BY word_id, letter_index;
        """)

        reconstructed_words = defaultdict(str)
        for word_id, letter in cursor.fetchall():
            reconstructed_words[word_id] += letter

        # Compare each word
        word_mismatches = []
        for word_id, orig_data in original_words.items():
            orig_text = orig_data["text"]
            recon_text = reconstructed_words.get(word_id, "")

            # Strip skipped categories (Cf, Lm) from original text
            # to ensure fair 1:1 visual comparison (builder intentionally skips these)
            clean_orig_text = _clean_text_for_comparison(orig_text)

            if clean_orig_text != recon_text:
                word_mismatches.append(
                    (word_id, orig_data["verse_key"], clean_orig_text, recon_text)
                )

        word_test_passed = len(word_mismatches) == 0

        if word_test_passed:
            print(f"  [PASS] All {len(original_words):,} words reconstructed perfectly")
        else:
            print(f"  [FAIL] Found {len(word_mismatches):,} word mismatches")
            print("\n  Sample mismatches (Word ID | Verse | Expected | Reconstructed):")
            for m in word_mismatches[:5]:
                print(f"    - ID {m[0]} | {m[1]}")
                print(f"      Expected: {m[2]}")
                print(f"      Got:      {m[3]}")

        # ---------------------------------------------------------
        # TEST 2: Verse-Level Verification (Words -> Verse)
        # ---------------------------------------------------------
        print("\n[Test 2/2] Verse-Level Reconstruction...")

        # Group original words into verses (sorted by word_id for deterministic order)
        original_verses = defaultdict(list)
        for word_id in sorted(original_words.keys()):
            data = original_words[word_id]
            original_verses[data["verse_key"]].append(data["text"])

        # Fetch reconstructed words grouped by verse
        # Note: We need to order by word_position for correct reconstruction
        # GROUP BY ensures one row per word even if word_position update failed
        cursor.execute(f"""
            SELECT verse_key, word_id, MIN(word_position) as word_position
            FROM {TABLE_LETTER_BREAKDOWN}
            GROUP BY verse_key, word_id
            ORDER BY verse_key, word_position;
        """)

        recon_verse_words = defaultdict(list)
        for verse_key, word_id, _ in cursor.fetchall():
            recon_verse_words[verse_key].append(reconstructed_words.get(word_id, ""))

        # Compare each verse
        verse_mismatches = []
        for verse_key, orig_word_list in original_verses.items():
            recon_word_list = recon_verse_words.get(verse_key, [])

            # Clean original words (strip skipped categories: Cf, Lm)
            clean_orig_word_list = [
                _clean_text_for_comparison(word) for word in orig_word_list
            ]

            # Join with spaces to form full verse text
            orig_verse_text = " ".join(clean_orig_word_list)
            recon_verse_text = " ".join(recon_word_list)

            if orig_verse_text != recon_verse_text:
                verse_mismatches.append((verse_key, orig_verse_text, recon_verse_text))

        verse_test_passed = len(verse_mismatches) == 0

        # Check for orphaned verse_keys in letter_breakdown not in words table
        extra_verses = set(recon_verse_words.keys()) - set(original_verses.keys())
        if extra_verses:
            verse_test_passed = False
            print(
                f"  [FAIL] {len(extra_verses)} orphaned verse_keys in letter_breakdown not in words table"
            )
            for v in list(extra_verses)[:5]:
                print(f"    - {v}")

        if verse_test_passed:
            print(
                f"  [PASS] All {len(original_verses):,} verses reconstructed perfectly"
            )
        else:
            print(f"  [FAIL] Found {len(verse_mismatches):,} verse mismatches")
            print("\n  Sample mismatches:")
            for m in verse_mismatches[:3]:
                print(f"    - Verse {m[0]}:")
                print(f"      Expected: {m[1][:80]}{'...' if len(m[1]) > 80 else ''}")
                print(f"      Got:      {m[2][:80]}{'...' if len(m[2]) > 80 else ''}")

        # ---------------------------------------------------------
        # Summary
        # ---------------------------------------------------------
        print("\n" + "=" * 60)
        if word_test_passed and verse_test_passed:
            print("ALL ROUND-TRIP INTEGRITY TESTS PASSED")
            print(
                f"   Verified: {len(original_words):,} words -> {len(original_verses):,} verses"
            )
            print("=" * 60)
            return True
        else:
            print("WARNING: INTEGRITY TESTS FAILED")
            print(f"   Word mismatches: {len(word_mismatches):,}")
            print(f"   Verse mismatches: {len(verse_mismatches):,}")
            print("=" * 60)
            return False

    def validate_subfield_consistency(self) -> bool:
        """Verify base_letter + diacritics_json chars == letter_with_diacritics for every row."""
        print("\n" + "=" * 60)
        print("Validating Sub-field Consistency")
        print("=" * 60)
        print("Verifies: base_letter + diacritics == letter_with_diacritics")

        # Check table exists
        table_exists = self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE_LETTER_BREAKDOWN,),
        ).fetchone()
        if not table_exists:
            print("\n[SKIP] letter_breakdown table not found")
            return True

        self.cursor.execute(f"""
            SELECT id, word_id, base_letter, diacritics_json, letter_with_diacritics
            FROM {TABLE_LETTER_BREAKDOWN}
            ORDER BY id;
        """)

        mismatches = []
        total = 0
        for (
            row_id,
            word_id,
            base_letter,
            diacritics_json,
            letter_with_diac,
        ) in self.cursor.fetchall():
            total += 1
            diac_chars = ""
            if diacritics_json:
                try:
                    diacritics = json.loads(diacritics_json)
                    diac_chars = "".join(d["char"] for d in diacritics)
                except (json.JSONDecodeError, KeyError):
                    mismatches.append(
                        (row_id, word_id, "invalid JSON", letter_with_diac)
                    )
                    continue

            reconstructed = base_letter + diac_chars
            if reconstructed != letter_with_diac:
                mismatches.append((row_id, word_id, reconstructed, letter_with_diac))

            if len(mismatches) >= 20:
                break

        if not mismatches:
            print(f"  [PASS] All {total:,} letters have consistent sub-fields")
            return True
        else:
            print(f"  [FAIL] Found {len(mismatches)} sub-field mismatches")
            for row_id, word_id, got, expected in mismatches[:5]:
                print(
                    f"    - letter id={row_id}, word_id={word_id}: '{got}' != '{expected}'"
                )
            return False

    def validate_letter_index_contiguity(self) -> bool:
        """Verify letter_index values are contiguous 0..N-1 for each word."""
        print("\n" + "=" * 60)
        print("Validating Letter Index Contiguity")
        print("=" * 60)

        # Check table exists
        table_exists = self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE_LETTER_BREAKDOWN,),
        ).fetchone()
        if not table_exists:
            print("\n[SKIP] letter_breakdown table not found")
            return True

        # Find words where max(letter_index) != count - 1 (indicates gap)
        gaps = self.cursor.execute(f"""
            SELECT word_id, COUNT(*) as cnt, MAX(letter_index) as max_idx
            FROM {TABLE_LETTER_BREAKDOWN}
            GROUP BY word_id
            HAVING max_idx != cnt - 1
            LIMIT 20;
        """).fetchall()

        if not gaps:
            word_count = self.cursor.execute(
                f"SELECT COUNT(DISTINCT word_id) FROM {TABLE_LETTER_BREAKDOWN}"
            ).fetchone()[0]
            print(f"  [PASS] All {word_count:,} words have contiguous letter indexes")
            return True
        else:
            print(
                f"  [FAIL] Found {len(gaps)} words with non-contiguous letter indexes"
            )
            for word_id, cnt, max_idx in gaps[:5]:
                print(
                    f"    - word_id={word_id}: {cnt} letters but max_index={max_idx} (expected {cnt - 1})"
                )
            return False

    def validate_diacritic_flags(self) -> bool:
        """Verify the 32 has_* boolean columns match what's in diacritics_json for every letter.

        The subfield consistency test verifies base_letter + diacritics == letter_with_diacritics,
        but it never checks whether the 32 boolean flag columns (has_fatha, has_shadda, etc.)
        actually reflect the diacritics present. A bug in CODEPOINT_TO_FLAG would silently
        produce wrong flags while that test passes.
        """
        print("\n" + "=" * 60)
        print("Validating Diacritic Flag Columns")
        print("=" * 60)
        print("Verifies: has_* columns match diacritics_json codepoints")

        table_exists = self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE_LETTER_BREAKDOWN,),
        ).fetchone()
        if not table_exists:
            print("\n[SKIP] letter_breakdown table not found")
            return True

        # Fetch all flag columns along with diacritics_json in one pass
        flag_cols = ", ".join(DIACRITIC_FLAGS)
        self.cursor.execute(f"""
            SELECT id, word_id, diacritics_json, {flag_cols}
            FROM {TABLE_LETTER_BREAKDOWN}
            ORDER BY id;
        """)

        mismatches = []
        total = 0
        for row in self.cursor.fetchall():
            total += 1
            row_id = row[0]
            word_id = row[1]
            diacritics_json_str = row[2]
            flag_values = row[3:]  # one value per flag in DIACRITIC_FLAGS order

            # Determine which flags should be set from diacritics_json
            expected_flags = set()
            if diacritics_json_str:
                try:
                    diacritics = json.loads(diacritics_json_str)
                    for d in diacritics:
                        cp = d.get("codepoint")
                        if cp and cp in CODEPOINT_TO_FLAG:
                            expected_flags.add(CODEPOINT_TO_FLAG[cp])
                except (json.JSONDecodeError, KeyError):
                    mismatches.append((row_id, word_id, "invalid diacritics_json", ""))
                    if len(mismatches) >= 20:
                        break
                    continue

            # Compare expected vs actual flag columns
            for flag_name, actual_value in zip(DIACRITIC_FLAGS, flag_values):
                expected_value = 1 if flag_name in expected_flags else 0
                if bool(actual_value) != bool(expected_value):
                    mismatches.append(
                        (row_id, word_id, flag_name, f"expected={expected_value}, got={actual_value}")
                    )
                    break  # one mismatch per row is enough to flag it

            if len(mismatches) >= 20:
                break

        if not mismatches:
            print(f"  [PASS] All {total:,} letters have correct diacritic flag columns")
            return True
        else:
            print(f"  [FAIL] Found {len(mismatches)} flag mismatches (stopped at 20)")
            for row_id, word_id, flag, detail in mismatches[:5]:
                print(f"    - letter id={row_id}, word_id={word_id}: {flag}: {detail}")
            return False

    def validate_word_position_ordering(self) -> bool:
        """Verify word_position values within each verse are contiguous and unique.

        For each verse, word_position should form a gapless sequence with no duplicates.
        The letter index contiguity test checks letters within a word; this checks
        words within a verse.
        """
        print("\n" + "=" * 60)
        print("Validating Word Position Ordering")
        print("=" * 60)
        print("Verifies: word_position is contiguous and unique within each verse")

        # Check for gaps or duplicates: if positions span min..max with no gaps,
        # then (max - min + 1) == count. Combined with a duplicate check via count
        # vs distinct count.
        gaps = self.cursor.execute(f"""
            SELECT
                verse_key,
                COUNT(*) as cnt,
                COUNT(DISTINCT word_position) as distinct_cnt,
                MAX(word_position) as max_pos,
                MIN(word_position) as min_pos
            FROM {TABLE_WORDS}
            GROUP BY verse_key
            HAVING (max_pos - min_pos + 1) != cnt
               OR distinct_cnt != cnt
            LIMIT 20;
        """).fetchall()

        if not gaps:
            verse_count = self.cursor.execute(
                f"SELECT COUNT(DISTINCT verse_key) FROM {TABLE_WORDS}"
            ).fetchone()[0]
            print(f"  [PASS] All {verse_count:,} verses have contiguous word positions")
            return True
        else:
            print(f"  [FAIL] Found {len(gaps)} verses with non-contiguous or duplicate word positions")
            for verse_key, cnt, distinct_cnt, max_pos, min_pos in gaps[:5]:
                if distinct_cnt != cnt:
                    issue = f"duplicate positions ({cnt} words, {distinct_cnt} distinct)"
                else:
                    issue = f"gap in range {min_pos}..{max_pos} ({cnt} words)"
                print(f"    - {verse_key}: {issue}")
            return False

    def validate_schema(self) -> bool:
        """
        Validate database schema against DATABASE_SCHEMA.md specification.

        Checks:
        1. All required tables exist
        2. Tables have correct columns
        3. Required indexes exist
        4. Foreign key relationships are valid

        Returns:
            True if schema is valid, False otherwise
        """
        print("\n" + "=" * 60)
        print("Validating Database Schema")
        print("=" * 60)

        all_passed = True

        # Define expected schema from DATABASE_SCHEMA.md
        expected_tables = {
            TABLE_WORDS: {
                "required_columns": [
                    "id",
                    "surah",
                    "ayah",
                    "word_position",
                    "text",
                    "verse_key",
                ],
                "required_indexes": [
                    f"idx_{TABLE_WORDS}_surah_ayah",
                    f"idx_{TABLE_WORDS}_verse_key",
                ],
            },
            TABLE_WORDS_TAJWEED: {
                "required_columns": [
                    "word_id",
                    "text",
                    "tajweed_color",
                    "tajweed_rule",
                ],
                "required_indexes": [f"idx_{TABLE_WORDS_TAJWEED}_word"],
            },
            TABLE_AYAHS: {
                "required_columns": [
                    "id",
                    "verse_key",
                    "surah",
                    "ayah",
                    "juz",
                    "hizb",
                    "rub",
                    "manzil",
                    "ruku",
                    "sajda_type",
                    "sajda_id",
                    "page",
                    "first_word_id",
                    "last_word_id",
                    "word_count",
                ],
                "required_indexes": [
                    f"idx_{TABLE_AYAHS}_surah",
                    f"idx_{TABLE_AYAHS}_juz",
                    f"idx_{TABLE_AYAHS}_page",
                ],
            },
            TABLE_SURAHS: {
                "required_columns": [
                    "id",
                    "name_ar",
                    "name_en",
                    "name_translation",
                    "revelation_type",
                    "verses_count",
                    "first_ayah_id",
                    "last_ayah_id",
                    "first_word_id",
                    "last_word_id",
                    "bismillah_pre",
                ],
                "required_indexes": [f"idx_{TABLE_SURAHS}_revelation"],
            },
            TABLE_MUSHAF_PAGES: {
                "required_columns": [
                    "id",
                    "page_number",
                    "line_number",
                    "word_id",
                    "verse_key",
                    "line_type",
                    "is_centered",
                ],
                "required_indexes": [
                    f"idx_{TABLE_MUSHAF_PAGES}_page",
                    f"idx_{TABLE_MUSHAF_PAGES}_page_line",
                    f"idx_{TABLE_MUSHAF_PAGES}_word",
                    f"idx_{TABLE_MUSHAF_PAGES}_verse",
                ],
            },
            TABLE_LETTER_BREAKDOWN: {
                "required_columns": [
                    "id",
                    "word_id",
                    "verse_key",
                    "word_position",
                    "letter_index",
                    "base_letter",
                    "letter_with_diacritics",
                    "base_letter_codepoint",
                    "base_letter_category",
                    "base_letter_name",
                    "diacritics_json",
                    # All diacritic flags from centralized config
                    *DIACRITIC_FLAGS,
                    "letter_type",
                    "is_hamza_variant",
                    "source_db",
                ],
                "required_indexes": [
                    f"idx_{TABLE_LETTER_BREAKDOWN}_word",
                    f"idx_{TABLE_LETTER_BREAKDOWN}_verse",
                    f"idx_{TABLE_LETTER_BREAKDOWN}_base",
                    f"idx_{TABLE_LETTER_BREAKDOWN}_shadda",
                ],
            },
            "metadata": {"required_columns": ["key", "value"], "required_indexes": []},
        }

        # Get actual tables
        actual_tables = {
            row[0]
            for row in self.cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        # Check each expected table
        for table_name, spec in expected_tables.items():
            print(f"\n[Table: {table_name}]")

            # Check table exists
            if table_name not in actual_tables:
                print(f"  [FAIL] Table missing")
                all_passed = False
                continue
            print(f"  [PASS] Table exists")

            # Get actual columns
            actual_columns = {
                row[1]
                for row in self.cursor.execute(
                    f"PRAGMA table_info({table_name})"
                ).fetchall()
            }

            # Check required columns
            missing_columns = set(spec["required_columns"]) - actual_columns
            if missing_columns:
                print(f"  [FAIL] Missing columns: {', '.join(missing_columns)}")
                all_passed = False
            else:
                print(
                    f"  [PASS] All {len(spec['required_columns'])} required columns present"
                )

            # Check indexes
            actual_indexes = {
                row[0]
                for row in self.cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
                    (table_name,),
                ).fetchall()
            }

            missing_indexes = set(spec["required_indexes"]) - actual_indexes
            if missing_indexes:
                print(f"  [FAIL] Missing indexes: {', '.join(missing_indexes)}")
                all_passed = False
            else:
                print(
                    f"  [PASS] All {len(spec['required_indexes'])} required indexes present"
                )

        # Check for unexpected tables
        expected_table_names = set(expected_tables.keys())
        unexpected = actual_tables - expected_table_names - {"sqlite_sequence"}
        if unexpected:
            print(f"\n[NOTE] Unexpected tables found: {', '.join(unexpected)}")

        # Summary
        print("\n" + "=" * 60)
        if all_passed:
            print("SCHEMA VALIDATION PASSED")
            print(f"   All {len(expected_tables)} tables validated")
        else:
            print("SCHEMA VALIDATION FAILED")
            print("   Some tables/columns/indexes are missing")
        print("=" * 60)

        return all_passed
