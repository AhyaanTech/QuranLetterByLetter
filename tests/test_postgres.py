"""Integration tests for the PostgreSQL database loaded from quran_offline.db.

Run after:
    docker compose up -d
    uv run scripts/load_to_postgres.py --drop

Then:
    uv run pytest tests/
    uv run pytest tests/ -v
"""

import pytest

# ---------------------------------------------------------------------------
# Known-good counts (Quran has a fixed number of words/verses/chapters)
# ---------------------------------------------------------------------------
EXPECTED_WORDS = 83_668
EXPECTED_AYAHS = 6_236
EXPECTED_SURAHS = 114


# ---------------------------------------------------------------------------
# Row count tests
# ---------------------------------------------------------------------------


def test_word_count(pg_conn):
    count = pg_conn.execute("SELECT COUNT(*) FROM words").fetchone()["count"]
    assert count == EXPECTED_WORDS, f"Expected {EXPECTED_WORDS} words, got {count}"


def test_ayah_count(pg_conn):
    count = pg_conn.execute("SELECT COUNT(*) FROM ayahs").fetchone()["count"]
    assert count == EXPECTED_AYAHS, f"Expected {EXPECTED_AYAHS} ayahs, got {count}"


def test_surah_count(pg_conn):
    count = pg_conn.execute("SELECT COUNT(*) FROM surahs").fetchone()["count"]
    assert count == EXPECTED_SURAHS, f"Expected {EXPECTED_SURAHS} surahs, got {count}"


def test_letter_breakdown_nonempty(pg_conn):
    count = pg_conn.execute("SELECT COUNT(*) FROM letter_breakdown").fetchone()["count"]
    assert count > 300_000, f"Expected >300,000 letters, got {count}"


def test_mushaf_pages_nonempty(pg_conn):
    count = pg_conn.execute("SELECT COUNT(*) FROM mushaf_pages").fetchone()["count"]
    assert count > 50_000, f"Expected >50,000 mushaf_pages rows, got {count}"


def test_metadata_nonempty(pg_conn):
    count = pg_conn.execute("SELECT COUNT(*) FROM metadata").fetchone()["count"]
    assert count > 0


# ---------------------------------------------------------------------------
# Type correctness: boolean columns must be Python bool, not int
# ---------------------------------------------------------------------------


def test_boolean_flags_letter_breakdown(pg_conn):
    row = pg_conn.execute(
        "SELECT has_shadda, has_fatha, has_kasra, has_damma, is_hamza_variant "
        "FROM letter_breakdown LIMIT 1"
    ).fetchone()
    assert row is not None, "letter_breakdown is empty"
    for col in ("has_shadda", "has_fatha", "has_kasra", "has_damma", "is_hamza_variant"):
        assert isinstance(row[col], bool), (
            f"{col} should be bool, got {type(row[col]).__name__} = {row[col]!r}"
        )


def test_boolean_is_centered_mushaf_pages(pg_conn):
    row = pg_conn.execute("SELECT is_centered FROM mushaf_pages LIMIT 1").fetchone()
    assert row is not None, "mushaf_pages is empty"
    assert isinstance(row["is_centered"], bool), (
        f"is_centered should be bool, got {type(row['is_centered']).__name__}"
    )


# ---------------------------------------------------------------------------
# Foreign key integrity
# ---------------------------------------------------------------------------


def test_fk_letter_breakdown_word_ids(pg_conn):
    orphans = pg_conn.execute("""
        SELECT COUNT(*) FROM letter_breakdown lb
        WHERE NOT EXISTS (SELECT 1 FROM words w WHERE w.id = lb.word_id)
    """).fetchone()["count"]
    assert orphans == 0, f"{orphans} letter_breakdown rows reference missing word_ids"


def test_fk_mushaf_pages_word_ids(pg_conn):
    orphans = pg_conn.execute("""
        SELECT COUNT(*) FROM mushaf_pages mp
        WHERE NOT EXISTS (SELECT 1 FROM words w WHERE w.id = mp.word_id)
    """).fetchone()["count"]
    assert orphans == 0, f"{orphans} mushaf_pages rows reference missing word_ids"


# ---------------------------------------------------------------------------
# Data consistency
# ---------------------------------------------------------------------------


def test_all_words_have_letters(pg_conn):
    words_without_letters = pg_conn.execute("""
        SELECT COUNT(*) FROM words w
        WHERE NOT EXISTS (
            SELECT 1 FROM letter_breakdown lb WHERE lb.word_id = w.id
        )
    """).fetchone()["count"]
    assert words_without_letters == 0, (
        f"{words_without_letters} words have no entries in letter_breakdown"
    )


def test_word_position_contiguous_per_verse(pg_conn):
    """word_position within each verse must be contiguous (no gaps or duplicates)."""
    bad_verses = pg_conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT verse_key,
                   COUNT(*) AS cnt,
                   COUNT(DISTINCT word_position) AS distinct_cnt,
                   MAX(word_position) AS max_pos,
                   MIN(word_position) AS min_pos
            FROM words
            GROUP BY verse_key
            HAVING (MAX(word_position) - MIN(word_position) + 1) != COUNT(*)
               OR COUNT(DISTINCT word_position) != COUNT(*)
        ) t
    """).fetchone()["count"]
    assert bad_verses == 0, f"{bad_verses} verses have non-contiguous word positions"


def test_letter_index_contiguous_per_word(pg_conn):
    """letter_index within each word must start at 0 and be contiguous."""
    bad_words = pg_conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT word_id,
                   COUNT(*) AS cnt,
                   MAX(letter_index) AS max_idx,
                   MIN(letter_index) AS min_idx
            FROM letter_breakdown
            GROUP BY word_id
            HAVING (MAX(letter_index) - MIN(letter_index) + 1) != COUNT(*)
               OR MIN(letter_index) != 0
        ) t
    """).fetchone()["count"]
    assert bad_words == 0, f"{bad_words} words have non-contiguous letter indices"


def test_shadda_count_reasonable(pg_conn):
    """The Quran has many shaddas — sanity-check the diacritic flag."""
    count = pg_conn.execute(
        "SELECT COUNT(*) FROM letter_breakdown WHERE has_shadda"
    ).fetchone()["count"]
    assert count > 5_000, f"Expected >5,000 shadda letters, got {count} — flag may be wrong"


# ---------------------------------------------------------------------------
# Spot-check: known content
# ---------------------------------------------------------------------------


def test_spot_check_first_word(pg_conn):
    """First word of the Quran (1:1, position 1) should start with بسم."""
    row = pg_conn.execute(
        "SELECT text FROM words WHERE surah = 1 AND ayah = 1 AND word_position = 1"
    ).fetchone()
    assert row is not None, "No word found at surah=1, ayah=1, position=1"
    # Accept with or without diacritics
    assert "\u0628" in row["text"], (
        f"First word should contain ب (ba), got: {row['text']!r}"
    )


def test_spot_check_surah_count_fatiha(pg_conn):
    """Al-Fatiha (surah 1) has 7 verses."""
    count = pg_conn.execute(
        "SELECT COUNT(*) FROM ayahs WHERE surah = 1"
    ).fetchone()["count"]
    assert count == 7, f"Surah 1 should have 7 ayahs, got {count}"


def test_spot_check_verse_key_format(pg_conn):
    """verse_key should be in 'surah:ayah' format."""
    row = pg_conn.execute(
        "SELECT verse_key FROM words WHERE surah = 2 AND ayah = 255 LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["verse_key"] == "2:255", (
        f"Expected '2:255', got {row['verse_key']!r}"
    )


# ---------------------------------------------------------------------------
# Index existence
# ---------------------------------------------------------------------------


def test_indexes_exist(pg_conn):
    rows = pg_conn.execute("""
        SELECT indexname FROM pg_indexes
        WHERE schemaname = 'public'
    """).fetchall()
    existing = {row["indexname"] for row in rows}

    required = {
        "idx_words_surah_ayah",
        "idx_words_verse_key",
        "idx_ayahs_surah",
        "idx_letter_breakdown_word",
        "idx_letter_breakdown_verse",
        "idx_mushaf_pages_page",
        "idx_mushaf_pages_word",
    }
    missing = required - existing
    assert not missing, f"Missing indexes: {', '.join(sorted(missing))}"
