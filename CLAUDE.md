# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Open-source letter-by-letter Quran data pipeline. Produces a SQLite database with full letter breakdown (base letter + 34 diacritic flags) for all 83,668 Quran words (~341,062 letters), plus a PostgreSQL/Hasura layer for GraphQL access.

## Build Commands

Requires [`uv`](https://docs.astral.sh/uv/).

```bash
# Step 1: Build core tables (words, ayahs, surahs, mushaf_pages, metadata)
uv run scripts/build_db.py --full

# Step 2: Build letter_breakdown table
uv run scripts/build_letters.py

# Validate only (no rebuild)
uv run scripts/build_db.py --validate

# Show letter statistics
uv run scripts/build_letters.py --stats

# Run all integrity tests without rebuilding
uv run scripts/build_letters.py --all-tests
```

### Docker (PostgreSQL + Hasura)

```bash
docker compose up -d
# Hasura console: http://localhost:8080/console
```

### Pre-built pipeline image (GHCR)

Published automatically on push to `main` via `.github/workflows/docker.yml`.

```bash
# Run the full pipeline against an existing PostgreSQL instance
docker run --rm \
  -e POSTGRES_DSN=postgresql://user:pass@host/db \
  ghcr.io/ahyaantech/quranletterbyletter:latest

# Rebuild and push manually
gh workflow run docker.yml
```

The image downloads source databases from the `v1.0-data` GitHub Release at build time (baked in). Entrypoint: `scripts/entrypoint.py` → runs `build_db.py --full`, `build_letters.py`, `load_to_postgres.py --drop` in sequence.

## Data Sources

Place these SQLite source databases in `data/source/` before building:
- `qpc-hafs-word-by-word.db` — QPC Hafs word text (from [Tarteel QUL](https://qul.tarteel.io/))
- `digital-khatt-15-lines.db` — KFGQPC V2 15-line Mushaf layout
- `qpc-hafs-tajweed.db` — QPC Tajweed color metadata (optional)

> Source databases are available as assets on the [v1.0-data GitHub Release](https://github.com/AhyaanTech/QuranLetterByLetter/releases/tag/v1.0-data). The `.db` files are gitignored.

Output: `data/output/quran_offline.db`

## Architecture

### Python Package (`scripts/quran_db/`)

| Module | Role |
|---|---|
| `config.py` | DB paths, schema constants (610 pages, 15 lines/page, 114 surahs), 34+ diacritic Unicode codepoints and flag names |
| `database.py` | SQLite context managers, source DB attachment, `ensure_directories()` |
| `builders.py` | `TableBuilder` — creates words/ayahs/surahs/mushaf_pages/metadata tables from source DBs |
| `letter_builder.py` | `LetterBreakdownBuilder` — segments words into letters, classifies diacritics by Unicode category |
| `validators.py` | `DatabaseValidator` — round-trip integrity checks (letters → words, words → ayahs) |
| `cli.py` | argparse CLI wiring for `build_db.py` |

### Output Database Schema (6 Tables)

- **words** (83,668): `id, surah, ayah, word_position, text, verse_key`
- **ayahs** (6,236): `verse_key, surah, ayah, first/last_word_id, word_count` (juz/hizb populated from external source)
- **surahs** (114): chapter metadata placeholders (names populated from external source)
- **mushaf_pages** (~1.2M): `page_number, line_number, word_id, line_type, is_centered`
- **letter_breakdown** (~341,062): `word_id, letter_index, base_letter, letter_with_diacritics, letter_type, is_hamza_variant, 34× has_* boolean diacritic flags, diacritics_json`
- **metadata**: build timestamps, schema versions

### Letter Segmentation Logic

The segmenter in `letter_builder.py` walks each word character-by-character using Unicode categories:
- `Lo` (Letter, other) → base Arabic letter, starts new letter slot
- `Mn`/`Me` (Mark, nonspacing/enclosing) → diacritic, appended to current letter
- `Cf`/`Lm` (Format/Letter modifier) → skipped, **except** U+06E5 (small waw) and U+06E6 (small yeh) which are treated as diacritics
- `Nd` (Decimal digit) → standalone letter slot

### PostgreSQL Layer

`scripts/load_to_postgres.py` reads the built SQLite DB and bulk-loads into PostgreSQL via `COPY`. Config in `hasura/`.

## Related Repositories

- `../FlutterMushafExample` — origin of Python scripts and source SQLite databases; Flutter Mushaf app consuming the DB
- `../QuranWordHasura` — reference for word-level Hasura/PostgreSQL setup pattern
