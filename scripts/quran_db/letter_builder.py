#!/usr/bin/env python3
"""Letter breakdown table builder.

Segments each word into individual Arabic letters with diacritics.
This is a separate step that can be run after the core tables are built.
"""

import json
import unicodedata
import sqlite3
from typing import List, Optional
from dataclasses import dataclass

from .config import (
    TABLE_WORDS,
    TABLE_LETTER_BREAKDOWN,
    DIACRITIC_TYPES,
    DIACRITIC_FLAGS,
    CODEPOINT_TO_FLAG,
    SKIPPED_CATEGORIES,
    DB_WORDS,
)


@dataclass
class DiacriticInfo:
    """Information about a single diacritic mark."""

    char: str
    codepoint: int
    name: str
    category: str
    type: str


@dataclass
class LetterBreakdown:
    """Represents a single letter with its diacritics."""

    word_id: int
    verse_key: str
    word_position: int
    letter_index: int
    base_letter: str
    letter_with_diacritics: str
    diacritics: List[DiacriticInfo]

    # Computed flags
    flags: dict


class LetterBreakdownBuilder:
    """Builds the letter_breakdown table."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.cursor = conn.cursor()
        self.stats = {
            "words_processed": 0,
            "letters_inserted": 0,
        }

    def build(self) -> dict:
        """Build the letter_breakdown table."""
        print("\n" + "=" * 60)
        print("Building Letter Breakdown Table")
        print("=" * 60)

        self._create_table()
        self._populate_table()
        self._create_indexes()
        self._update_word_positions()

        return self.stats

    def _create_table(self) -> None:
        """Create letter_breakdown table with all columns."""
        print("\n[1/4] Creating table...")

        # Drop existing
        self.cursor.execute(f"DROP TABLE IF EXISTS {TABLE_LETTER_BREAKDOWN};")

        # Create with all flag columns (using centralized DIACRITIC_FLAGS from config)
        flags_sql = ",\n            ".join(
            [f"{flag} INTEGER DEFAULT 0" for flag in DIACRITIC_FLAGS]
        )

        self.cursor.execute(f"""
            CREATE TABLE {TABLE_LETTER_BREAKDOWN} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL,
                verse_key TEXT NOT NULL,
                word_position INTEGER NOT NULL,
                letter_index INTEGER NOT NULL,
                base_letter TEXT NOT NULL,
                letter_with_diacritics TEXT,
                base_letter_codepoint INTEGER,
                base_letter_category TEXT,
                base_letter_name TEXT,
                diacritics_json TEXT,
                {flags_sql},
                letter_type TEXT,
                is_hamza_variant INTEGER DEFAULT 0,
                source_db TEXT,
                UNIQUE(word_id, letter_index)
            );
        """)

        print("    [OK] Table created")

    def _create_indexes(self) -> None:
        """Create indexes after bulk insert for better performance."""
        print("\n[3/4] Creating indexes...")

        indexes = [
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_LETTER_BREAKDOWN}_word ON {TABLE_LETTER_BREAKDOWN}(word_id);",
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_LETTER_BREAKDOWN}_verse ON {TABLE_LETTER_BREAKDOWN}(verse_key);",
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_LETTER_BREAKDOWN}_base ON {TABLE_LETTER_BREAKDOWN}(base_letter);",
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_LETTER_BREAKDOWN}_shadda ON {TABLE_LETTER_BREAKDOWN}(has_shadda);",
        ]
        for idx_sql in indexes:
            self.cursor.execute(idx_sql)

        self.conn.commit()
        print("    [OK] Indexes created")

    def _populate_table(self) -> None:
        """Populate table by segmenting all words."""
        print("\n[2/4] Segmenting words into letters...")

        # Get all words
        self.cursor.execute(f"""
            SELECT id, verse_key, text
            FROM {TABLE_WORDS}
            ORDER BY id;
        """)
        words = self.cursor.fetchall()

        total_words = len(words)
        print(f"    Processing {total_words:,} words...")

        # Prepare insert
        insert_sql = self._get_insert_sql()

        batch = []
        batch_size = 1000
        total_letters = 0

        for i, (word_id, verse_key, text) in enumerate(words):
            letters = self._segment_word(word_id, verse_key, text)

            for letter in letters:
                batch.append(self._letter_to_tuple(letter))
                total_letters += 1

            if len(batch) >= batch_size:
                self.cursor.executemany(insert_sql, batch)
                self.conn.commit()
                batch = []

                if (i + 1) % 10000 == 0:
                    print(f"      Progress: {i + 1:,}/{total_words:,} words")

        # Insert remaining
        if batch:
            self.cursor.executemany(insert_sql, batch)
            self.conn.commit()

        self.stats["words_processed"] = total_words
        self.stats["letters_inserted"] = total_letters
        print(f"    [OK] Inserted {total_letters:,} letters")

    def _segment_word(
        self, word_id: int, verse_key: str, text: str
    ) -> List[LetterBreakdown]:
        """Segment a word into individual letters."""
        letters = []
        current_base: Optional[str] = None
        current_diacritics: List[DiacriticInfo] = []
        letter_index = 0

        for char in text:
            codepoint = ord(char)
            category = unicodedata.category(char)

            if category == "Lo":  # Base Arabic letter
                # Warn if we have orphan diacritics (accumulated without a base letter)
                if current_base is None and current_diacritics:
                    diacritic_chars = [d.char for d in current_diacritics]
                    print(
                        f"  [WARN] Orphan diacritics before first letter in word {word_id}: "
                        f"{diacritic_chars}"
                    )

                # Save previous letter
                if current_base is not None:
                    letters.append(
                        self._create_letter(
                            word_id,
                            verse_key,
                            letter_index,
                            current_base,
                            current_diacritics,
                        )
                    )
                    letter_index += 1

                # Start new letter
                current_base = char
                current_diacritics = []

            elif category in SKIPPED_CATEGORIES:
                # Exception: small waw (U+06E5) and small yeh (U+06E6) are Lm category
                # but are meaningful Quranic annotation marks - treat them as diacritics
                if codepoint in (0x06E5, 0x06E6):
                    diacritic = self._classify_diacritic(char, codepoint)
                    current_diacritics.append(diacritic)
                else:
                    # Skip other invisible/formatting chars (Cf, Lm)
                    # Cf = Format characters (e.g., joiners, directional marks)
                    # Lm = Letter modifiers (e.g., tatweel/kashida U+0640)
                    # These are cosmetic and not needed for letter analysis
                    continue

            elif category in ("Mn", "Me"):  # Diacritic marks (nonspacing, enclosing)
                diacritic = self._classify_diacritic(char, codepoint)
                current_diacritics.append(diacritic)

            elif category == "Nd":  # Decimal digit
                if current_base is not None:
                    letters.append(
                        self._create_letter(
                            word_id,
                            verse_key,
                            letter_index,
                            current_base,
                            current_diacritics,
                        )
                    )
                    letter_index += 1
                letters.append(
                    self._create_letter(word_id, verse_key, letter_index, char, [])
                )
                letter_index += 1
                current_base = None
                current_diacritics = []

            else:  # Other characters
                if current_base is not None:
                    letters.append(
                        self._create_letter(
                            word_id,
                            verse_key,
                            letter_index,
                            current_base,
                            current_diacritics,
                        )
                    )
                    letter_index += 1
                current_base = char
                current_diacritics = []

        # Don't forget last letter
        if current_base is not None:
            letters.append(
                self._create_letter(
                    word_id, verse_key, letter_index, current_base, current_diacritics
                )
            )

        return letters

    def _create_letter(
        self,
        word_id: int,
        verse_key: str,
        letter_index: int,
        base: str,
        diacritics: List[DiacriticInfo],
    ) -> LetterBreakdown:
        """Create a LetterBreakdown object."""
        # Build letter with diacritics
        letter_with_diac = base + "".join(d.char for d in diacritics)

        # Compute flags
        flags = self._compute_flags(diacritics)

        # Get base letter info
        base_name = unicodedata.name(base, "UNKNOWN")
        letter_type = self._get_letter_type(base_name)

        # Check for hamza: in base name OR as combining diacritic (decomposed forms)
        is_hamza = (
            "HAMZA" in base_name
            or "WASLA" in base_name
            or any(d.codepoint in (0x0654, 0x0655) for d in diacritics)
        )

        # Add to flags
        flags["letter_type"] = letter_type
        flags["is_hamza_variant"] = 1 if is_hamza else 0

        return LetterBreakdown(
            word_id=word_id,
            verse_key=verse_key,
            word_position=0,  # Updated later
            letter_index=letter_index,
            base_letter=base,
            letter_with_diacritics=letter_with_diac,
            diacritics=diacritics,
            flags=flags,
        )

    def _classify_diacritic(self, char: str, codepoint: int) -> DiacriticInfo:
        """Classify a diacritic character."""
        name = unicodedata.name(char, "UNKNOWN")
        category = unicodedata.category(char)

        if codepoint in DIACRITIC_TYPES:
            dtype, _ = DIACRITIC_TYPES[codepoint]
        elif category == "Mn":
            dtype = "unknown_mark"
        else:
            dtype = "other"

        return DiacriticInfo(
            char=char, codepoint=codepoint, name=name, category=category, type=dtype
        )

    def _compute_flags(self, diacritics: List[DiacriticInfo]) -> dict:
        """Compute boolean flags from diacritics using centralized mapping."""
        # Initialize all flags to 0 using centralized DIACRITIC_FLAGS
        flags = {flag: 0 for flag in DIACRITIC_FLAGS}

        # Set flags based on codepoint-to-flag mapping from config
        for d in diacritics:
            flag_name = CODEPOINT_TO_FLAG.get(d.codepoint)
            if flag_name:
                flags[flag_name] = 1

        return flags

    def _get_letter_type(self, name: str) -> str:
        """Determine letter type from Unicode name."""
        # Check Alef Maksura first - it's a substring of other Alef names
        if "ALEF MAKSURA" in name:
            return "long_vowel"

        vowel_carriers = ["ARABIC LETTER ALEF", "ARABIC LETTER ALEF WITH"]
        if any(vc in name for vc in vowel_carriers):
            return "vowel_carrier"

        if "WAW" in name or "YEH" in name:
            return "long_vowel"

        return "consonant"

    def _get_insert_sql(self) -> str:
        """Generate INSERT SQL statement."""
        columns = [
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
            # Flag columns from centralized DIACRITIC_FLAGS
            *DIACRITIC_FLAGS,
            "letter_type",
            "is_hamza_variant",
            "source_db",
        ]
        placeholders = ", ".join(["?"] * len(columns))
        return f"INSERT INTO {TABLE_LETTER_BREAKDOWN} ({', '.join(columns)}) VALUES ({placeholders});"

    def _letter_to_tuple(self, letter: LetterBreakdown) -> tuple:
        """Convert LetterBreakdown to tuple for insertion."""
        diacritics_json = json.dumps(
            [
                {
                    "char": d.char,
                    "codepoint": d.codepoint,
                    "name": d.name,
                    "type": d.type,
                }
                for d in letter.diacritics
            ],
            ensure_ascii=False,
        )

        base_cp = ord(letter.base_letter)
        base_cat = unicodedata.category(letter.base_letter)
        base_name = unicodedata.name(letter.base_letter, "UNKNOWN")

        return (
            letter.word_id,
            letter.verse_key,
            letter.word_position,
            letter.letter_index,
            letter.base_letter,
            letter.letter_with_diacritics,
            base_cp,
            base_cat,
            base_name,
            diacritics_json,
            # Flag values from centralized DIACRITIC_FLAGS
            *[letter.flags.get(flag, 0) for flag in DIACRITIC_FLAGS],
            letter.flags.get("letter_type", "consonant"),
            letter.flags.get("is_hamza_variant", 0),
            DB_WORDS.name,
        )

    def _update_word_positions(self) -> None:
        """Update word_position to be per-verse rather than global."""
        print("\n[4/4] Updating word positions per verse...")

        # Use a single SQL statement with ROW_NUMBER() for efficiency
        # This replaces ~83K individual UPDATEs with one query
        self.cursor.execute(f"""
            UPDATE {TABLE_LETTER_BREAKDOWN}
            SET word_position = (
                SELECT pos FROM (
                    SELECT
                        word_id,
                        verse_key,
                        ROW_NUMBER() OVER (PARTITION BY verse_key ORDER BY word_id) as pos
                    FROM (
                        SELECT DISTINCT word_id, verse_key
                        FROM {TABLE_LETTER_BREAKDOWN}
                    )
                ) sub
                WHERE sub.word_id = {TABLE_LETTER_BREAKDOWN}.word_id
                  AND sub.verse_key = {TABLE_LETTER_BREAKDOWN}.verse_key
            );
        """)

        self.conn.commit()

        # Verify no rows were left with position 0 (would indicate the UPDATE failed)
        zero_count = self.cursor.execute(
            f"SELECT COUNT(*) FROM {TABLE_LETTER_BREAKDOWN} WHERE word_position = 0"
        ).fetchone()[0]
        if zero_count:
            raise RuntimeError(
                f"_update_word_positions() left {zero_count} rows with word_position=0"
            )

        print("    [OK] Word positions updated")
