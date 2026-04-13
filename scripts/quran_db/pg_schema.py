"""PostgreSQL DDL for quran_offline database.

All CREATE TABLE statements and indexes, translated from the SQLite schema.
Type mapping:
  INTEGER PRIMARY KEY            → INTEGER PRIMARY KEY  (explicit IDs from source)
  INTEGER PRIMARY KEY AUTOINCREMENT → BIGSERIAL PRIMARY KEY
  INTEGER DEFAULT 0  (booleans) → BOOLEAN DEFAULT FALSE
  TEXT                           → TEXT
  INTEGER (non-boolean)          → INTEGER
"""

from .config import DIACRITIC_FLAGS

# --- Boolean flag DDL fragment (generated from centralized DIACRITIC_FLAGS list) ---
_FLAG_COLS = "\n    ".join(f"{flag} BOOLEAN DEFAULT FALSE," for flag in DIACRITIC_FLAGS)

# --- Table DDL ---

_WORDS = """
CREATE TABLE words (
    id INTEGER PRIMARY KEY,
    surah INTEGER NOT NULL,
    ayah INTEGER NOT NULL,
    word_position INTEGER NOT NULL,
    text TEXT NOT NULL,
    verse_key TEXT NOT NULL
)
"""

_SURAHS = """
CREATE TABLE surahs (
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
)
"""

_AYAHS = """
CREATE TABLE ayahs (
    id BIGSERIAL PRIMARY KEY,
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
)
"""

_MUSHAF_PAGES = """
CREATE TABLE mushaf_pages (
    id BIGSERIAL PRIMARY KEY,
    page_number INTEGER NOT NULL,
    line_number INTEGER NOT NULL,
    word_id INTEGER NOT NULL REFERENCES words(id),
    verse_key TEXT NOT NULL,
    line_type TEXT,
    is_centered BOOLEAN DEFAULT FALSE
)
"""

_LETTER_BREAKDOWN = f"""
CREATE TABLE letter_breakdown (
    id BIGSERIAL PRIMARY KEY,
    word_id INTEGER NOT NULL REFERENCES words(id),
    verse_key TEXT NOT NULL,
    word_position INTEGER NOT NULL,
    letter_index INTEGER NOT NULL,
    base_letter TEXT NOT NULL,
    letter_with_diacritics TEXT,
    base_letter_codepoint INTEGER,
    base_letter_category TEXT,
    base_letter_name TEXT,
    diacritics_json TEXT,
    {_FLAG_COLS}
    letter_type TEXT,
    is_hamza_variant BOOLEAN DEFAULT FALSE,
    source_db TEXT,
    UNIQUE (word_id, letter_index)
)
"""

_METADATA = """
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT
)
"""

# Mapping: table name → CREATE TABLE SQL
TABLES: dict[str, str] = {
    "words": _WORDS,
    "surahs": _SURAHS,
    "ayahs": _AYAHS,
    "mushaf_pages": _MUSHAF_PAGES,
    "letter_breakdown": _LETTER_BREAKDOWN,
    "metadata": _METADATA,
}

# Load order respects foreign key dependencies
TABLE_ORDER: list[str] = [
    "words",
    "surahs",
    "ayahs",
    "mushaf_pages",
    "letter_breakdown",
    "metadata",
]

# Tables that use BIGSERIAL and need their sequence reset after bulk load
SERIAL_TABLES: frozenset[str] = frozenset({"ayahs", "mushaf_pages", "letter_breakdown"})

# --- Index DDL ---

INDEXES: list[str] = [
    # words
    "CREATE INDEX idx_words_surah_ayah ON words(surah, ayah)",
    "CREATE INDEX idx_words_verse_key ON words(verse_key)",
    # surahs
    "CREATE INDEX idx_surahs_revelation ON surahs(revelation_type)",
    # ayahs
    "CREATE INDEX idx_ayahs_surah ON ayahs(surah)",
    "CREATE INDEX idx_ayahs_juz ON ayahs(juz)",
    "CREATE INDEX idx_ayahs_page ON ayahs(page)",
    # mushaf_pages
    "CREATE INDEX idx_mushaf_pages_page ON mushaf_pages(page_number)",
    "CREATE INDEX idx_mushaf_pages_page_line ON mushaf_pages(page_number, line_number)",
    "CREATE INDEX idx_mushaf_pages_word ON mushaf_pages(word_id)",
    "CREATE INDEX idx_mushaf_pages_verse ON mushaf_pages(verse_key)",
    # letter_breakdown
    "CREATE INDEX idx_letter_breakdown_word ON letter_breakdown(word_id)",
    "CREATE INDEX idx_letter_breakdown_verse ON letter_breakdown(verse_key)",
    "CREATE INDEX idx_letter_breakdown_base ON letter_breakdown(base_letter)",
    # Partial indexes for the two most-queried diacritic flags
    "CREATE INDEX idx_letter_breakdown_shadda ON letter_breakdown(word_id) WHERE has_shadda",
    "CREATE INDEX idx_letter_breakdown_fatha ON letter_breakdown(word_id) WHERE has_fatha",
]
