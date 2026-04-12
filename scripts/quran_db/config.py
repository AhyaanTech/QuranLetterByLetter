#!/usr/bin/env python3
"""Configuration and constants for Quran database building."""

from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
DATA_DIR = PROJECT_ROOT / "data"
DB_DIR = DATA_DIR / "output"  # used by database.py for ensure_directories
OUTPUT_DB = DB_DIR / "quran_offline.db"

# Source databases
DB_WORDS = DATA_DIR / "source" / "qpc-hafs-word-by-word.db"
DB_LAYOUT = DATA_DIR / "source" / "digital-khatt-15-lines.db"  # KFGQPC V2 15-line layout
DB_TAJWEED = DATA_DIR / "source" / "qpc-hafs-tajweed.db"  # Official Tajweed colors (optional)

# Schema constants
TOTAL_PAGES = 610
LINES_PER_PAGE = 15
TOTAL_SURAHS = 114

# Table names
TABLE_WORDS = "words"
TABLE_WORDS_TAJWEED = "words_tajweed"  # Official Tajweed colors
TABLE_AYAHS = "ayahs"
TABLE_SURAHS = "surahs"
TABLE_MUSHAF_PAGES = "mushaf_pages"
TABLE_LETTER_BREAKDOWN = "letter_breakdown"
TABLE_METADATA = "metadata"

# Letter breakdown flags - derived from DIACRITIC_TYPES
# These are the boolean flag columns in the letter_breakdown table
DIACRITIC_FLAGS = [
    "has_fatha",
    "has_kasra",
    "has_damma",
    "has_sukun",
    "has_shadda",
    "has_tanwin_fath",
    "has_tanwin_kasr",
    "has_tanwin_damm",
    "has_maddah",
    "has_hamza_above",
    "has_hamza_below",
    "has_superscript_alef",
    "has_subscript_alef",
    # Quranic stop signs and annotations (excluding standalone markers)
    "has_small_high_sad_lam",
    "has_small_high_qaf_lam",
    "has_small_high_meem_initial",
    "has_small_high_lam",
    "has_small_high_jeem",
    "has_small_high_three_dots",
    "has_small_high_seen",
    "has_small_high_rounded_zero",
    "has_small_high_upright_zero",
    "has_small_high_dotless_head",
    "has_small_high_meem_isolated",
    "has_small_low_seen",
    "has_small_high_maddah",
    "has_small_waw",
    "has_small_yeh",
    "has_small_high_noon",
    "has_small_high_three_dots_alt",
    "has_empty_centre_low_stop",
    "has_empty_centre_high_stop",
    "has_rounded_high_stop",
    "has_small_low_meem",
    # Note: has_end_of_ayah, has_start_of_rub, has_place_of_sajdah removed
    # These are standalone markers (U+06DD, U+06DE, U+06E9), not diacritics
]

# Unicode codepoints for diacritics
DIACRITIC_TYPES = {
    # Basic diacritics (harakat)
    0x064E: ("haraka", "fatha"),
    0x0650: ("haraka", "kasra"),
    0x064F: ("haraka", "damma"),
    0x0652: ("sukun", "sukun"),
    # Tanwin
    0x064B: ("tanwin", "tanwin_fath"),
    0x064D: ("tanwin", "tanwin_kasr"),
    0x064C: ("tanwin", "tanwin_damm"),
    # Other marks
    0x0651: ("shadda", "shadda"),
    0x0653: ("maddah", "maddah"),
    0x0654: ("hamza", "hamza_above"),
    0x0655: ("hamza", "hamza_below"),
    0x0670: ("special", "superscript_alef"),
    0x0656: ("special", "subscript_alef"),
    # Quranic annotation marks (small high/low characters)
    # Note: U+06DD (end of ayah), U+06DE (start of rub), U+06E9 (place of sajdah)
    # are standalone markers, not diacritics - they are excluded from this list
    0x06D6: ("quranic_stop", "small_high_sad_lam"),  # صلى
    0x06D7: ("quranic_stop", "small_high_qaf_lam"),  # قلى
    0x06D8: ("quranic_stop", "small_high_meem_initial"),  # meem at start
    0x06D9: ("quranic_stop", "small_high_lam"),  # لام
    0x06DA: ("quranic_annotation", "small_high_jeem"),  # جيم
    0x06DB: ("quranic_annotation", "small_high_three_dots"),  # three dots
    0x06DC: ("quranic_annotation", "small_high_seen"),  # سين
    # 0x06DD excluded - standalone end-of-ayah marker (U+06DD is Cf category)
    # 0x06DE excluded - standalone start-of-rub marker (U+06DE is So category)
    0x06DF: ("quranic_annotation", "small_high_rounded_zero"),  # rounded zero
    0x06E0: ("quranic_annotation", "small_high_upright_zero"),  # upright zero
    0x06E1: ("quranic_annotation", "small_high_dotless_head"),  # dotless head
    0x06E2: ("quranic_annotation", "small_high_meem_isolated"),  # meem isolated
    0x06E3: ("quranic_annotation", "small_low_seen"),  # low seen
    0x06E4: ("quranic_annotation", "small_high_maddah"),  # high maddah
    0x06E5: (
        "quranic_annotation",
        "small_waw",
    ),  # small waw (Lm category, but meaningful)
    0x06E6: (
        "quranic_annotation",
        "small_yeh",
    ),  # small yeh (Lm category, but meaningful)
    0x06E7: ("quranic_annotation", "small_high_noon"),  # high noon
    0x06E8: ("quranic_annotation", "small_high_three_dots_alt"),  # three dots alt
    # 0x06E9 excluded - standalone place-of-sajdah marker (U+06E9 is So category)
    0x06EA: ("quranic_annotation", "empty_centre_low_stop"),  # empty centre low
    0x06EB: ("quranic_annotation", "empty_centre_high_stop"),  # empty centre high
    0x06EC: ("quranic_annotation", "rounded_high_stop"),  # rounded high
    0x06ED: ("quranic_annotation", "small_low_meem"),  # low meem
}

# Build reverse mapping: codepoint -> flag name for efficient lookup
# This is derived from DIACRITIC_TYPES to ensure consistency
CODEPOINT_TO_FLAG = {
    codepoint: f"has_{type_info[1]}" for codepoint, type_info in DIACRITIC_TYPES.items()
}

# Unicode categories to skip during segmentation (invisible/formatting characters)
# These are stripped from text during both building and validation for consistency
SKIPPED_CATEGORIES = {
    "Cf",
    "Lm",
}  # Format characters and Letter modifiers (e.g., tatweel)
