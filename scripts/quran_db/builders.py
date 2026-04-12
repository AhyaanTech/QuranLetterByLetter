#!/usr/bin/env python3
"""Database table builders - creates the normalized schema."""

import sqlite3
from typing import List, Tuple

from .config import (
    TABLE_WORDS,
    TABLE_AYAHS,
    TABLE_SURAHS,
    TABLE_MUSHAF_PAGES,
    TABLE_METADATA,
    DB_WORDS,
    DB_LAYOUT,
    TOTAL_PAGES,
    LINES_PER_PAGE,
)
from .database import validate_source_db


class TableBuilder:
    """Builds normalized tables in the output database."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.cursor = conn.cursor()
        self.stats = {}

    def build_all(self) -> dict:
        """Build all tables in dependency order."""
        print("\n" + "=" * 60)
        print("Building Tables")
        print("=" * 60)

        # Core tables (source of truth)
        self._build_words_table()
        self._build_ayahs_table()
        self._build_surahs_table()

        # Layout table
        self._build_mushaf_pages_table()

        # Metadata
        self._build_metadata_table()

        return self.stats

    def _build_words_table(self) -> None:
        """Build words table - core source of truth."""
        print("\n[1/5] Creating words table...")

        self.cursor.execute(f"""
            CREATE TABLE {TABLE_WORDS} (
                id INTEGER PRIMARY KEY,
                surah INTEGER NOT NULL,
                ayah INTEGER NOT NULL,
                word_position INTEGER NOT NULL,
                text TEXT NOT NULL,
                verse_key TEXT NOT NULL
            );
        """)

        self.cursor.execute(f"""
            CREATE INDEX idx_{TABLE_WORDS}_surah_ayah ON {TABLE_WORDS}(surah, ayah);
        """)
        self.cursor.execute(f"""
            CREATE INDEX idx_{TABLE_WORDS}_verse_key ON {TABLE_WORDS}(verse_key);
        """)

        # Copy from source
        self.cursor.execute(f"""
            INSERT INTO {TABLE_WORDS} (id, surah, ayah, word_position, text, verse_key)
            SELECT id, surah, ayah, word, text, surah || ':' || ayah
            FROM words_db.words
            ORDER BY id;
        """)

        count = self.cursor.rowcount
        self.stats[TABLE_WORDS] = count
        print(f"    [OK] {count:,} words")

    def _build_ayahs_table(self) -> None:
        """Build ayahs table - verse metadata."""
        print("\n[2/5] Creating ayahs table...")

        self.cursor.execute(f"""
            CREATE TABLE {TABLE_AYAHS} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                verse_key TEXT NOT NULL UNIQUE,
                surah INTEGER NOT NULL,
                ayah INTEGER NOT NULL,
                text TEXT,
                juz INTEGER,
                hizb INTEGER,
                rub INTEGER,
                manzil INTEGER,
                ruku INTEGER,
                sajda_type TEXT,
                sajda_id INTEGER,
                page INTEGER,
                first_word_id INTEGER,
                last_word_id INTEGER,
                word_count INTEGER
            );
        """)

        self.cursor.execute(f"""
            CREATE INDEX idx_{TABLE_AYAHS}_surah ON {TABLE_AYAHS}(surah);
        """)
        self.cursor.execute(f"""
            CREATE INDEX idx_{TABLE_AYAHS}_juz ON {TABLE_AYAHS}(juz);
        """)
        self.cursor.execute(f"""
            CREATE INDEX idx_{TABLE_AYAHS}_page ON {TABLE_AYAHS}(page);
        """)

        # Derive from words table (no ayah text - build from words when needed)
        self.cursor.execute(f"""
            INSERT INTO {TABLE_AYAHS} (verse_key, surah, ayah, first_word_id, last_word_id, word_count)
            SELECT
                w.verse_key,
                w.surah,
                w.ayah,
                MIN(w.id) as first_word_id,
                MAX(w.id) as last_word_id,
                COUNT(*) as word_count
            FROM {TABLE_WORDS} w
            GROUP BY w.surah, w.ayah
            ORDER BY w.surah, w.ayah;
        """)

        count = self.cursor.rowcount
        self.stats[TABLE_AYAHS] = count
        print(f"    [OK] {count:,} ayahs")
        print(
            f"    [NOTE] Ayah text built from words; populate juz, hizb, sajda markers from external source"
        )

    def _build_surahs_table(self) -> None:
        """Build surahs table - chapter metadata (placeholder)."""
        print("\n[3/5] Creating surahs table...")

        self.cursor.execute(f"""
            CREATE TABLE {TABLE_SURAHS} (
                id INTEGER PRIMARY KEY,
                name_ar TEXT,
                name_en TEXT,
                name_translation TEXT,
                revelation_type TEXT,
                verses_count INTEGER,
                first_ayah_id INTEGER,
                last_ayah_id INTEGER,
                first_word_id INTEGER,
                last_word_id INTEGER,
                bismillah_pre TEXT
            );
        """)

        self.cursor.execute(f"""
            CREATE INDEX idx_{TABLE_SURAHS}_revelation ON {TABLE_SURAHS}(revelation_type);
        """)

        # Create placeholder entries from ayah data
        self.cursor.execute(f"""
            INSERT INTO {TABLE_SURAHS} (id, verses_count, first_word_id, last_word_id)
            SELECT
                surah,
                COUNT(DISTINCT ayah) as verses_count,
                MIN(first_word_id) as first_word_id,
                MAX(last_word_id) as last_word_id
            FROM {TABLE_AYAHS}
            GROUP BY surah
            ORDER BY surah;
        """)

        count = self.cursor.rowcount
        self.stats[TABLE_SURAHS] = count
        print(f"    [OK] {count} surahs (placeholder)")
        print(f"    [NOTE] Populate names, revelation_type from external source")

    def _build_mushaf_pages_table(self) -> None:
        """Build mushaf_pages table - layout coordinates."""
        print("\n[4/5] Creating mushaf_pages table...")

        self.cursor.execute(f"""
            CREATE TABLE {TABLE_MUSHAF_PAGES} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_number INTEGER NOT NULL,
                line_number INTEGER NOT NULL,
                word_id INTEGER NOT NULL,
                verse_key TEXT NOT NULL,
                line_type TEXT,
                is_centered INTEGER DEFAULT 0,
                FOREIGN KEY (word_id) REFERENCES {TABLE_WORDS}(id)
            );
        """)

        # Indexes
        self.cursor.execute(f"""
            CREATE INDEX idx_{TABLE_MUSHAF_PAGES}_page ON {TABLE_MUSHAF_PAGES}(page_number);
        """)
        self.cursor.execute(f"""
            CREATE INDEX idx_{TABLE_MUSHAF_PAGES}_page_line ON {TABLE_MUSHAF_PAGES}(page_number, line_number);
        """)
        self.cursor.execute(f"""
            CREATE INDEX idx_{TABLE_MUSHAF_PAGES}_word ON {TABLE_MUSHAF_PAGES}(word_id);
        """)
        self.cursor.execute(f"""
            CREATE INDEX idx_{TABLE_MUSHAF_PAGES}_verse ON {TABLE_MUSHAF_PAGES}(verse_key);
        """)

        # Merge layout with words
        self.cursor.execute(f"""
            INSERT INTO {TABLE_MUSHAF_PAGES}
                (page_number, line_number, word_id, verse_key, line_type, is_centered)
            SELECT
                p.page_number,
                p.line_number,
                w.id AS word_id,
                w.surah || ':' || w.ayah AS verse_key,
                p.line_type,
                p.is_centered
            FROM layout_db.pages p
            JOIN words_db.words w ON w.id BETWEEN p.first_word_id AND p.last_word_id
            WHERE p.first_word_id IS NOT NULL AND p.last_word_id IS NOT NULL
            ORDER BY p.page_number, p.line_number, w.id;
        """)

        count = self.cursor.rowcount
        pages = self.cursor.execute(
            f"SELECT COUNT(DISTINCT page_number) FROM {TABLE_MUSHAF_PAGES}"
        ).fetchone()[0]

        self.stats[TABLE_MUSHAF_PAGES] = count
        self.stats["pages"] = pages
        print(f"    [OK] {count:,} entries across {pages} pages")

    def _build_metadata_table(self) -> None:
        """Build metadata table - build info."""
        print("\n[5/5] Creating metadata table...")

        self.cursor.execute(f"""
            CREATE TABLE {TABLE_METADATA} (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)

        metadata = [
            ("source_words_db", str(DB_WORDS.name)),
            ("source_layout_db", str(DB_LAYOUT.name)),
            ("total_pages", str(TOTAL_PAGES)),
            ("lines_per_page", str(LINES_PER_PAGE)),
            ("schema_version", "2.0"),
        ]

        self.cursor.executemany(
            f"INSERT INTO {TABLE_METADATA} (key, value) VALUES (?, ?);", metadata
        )

        # Insert built_at separately to get actual timestamp
        self.cursor.execute(
            f"INSERT INTO {TABLE_METADATA} (key, value) VALUES (?, datetime('now'));",
            ("built_at",),
        )

        self.stats[TABLE_METADATA] = len(metadata) + 1
        print(f"    [OK] {len(metadata) + 1} metadata entries")
