# QuranLetterByLetter

Open-source letter-by-letter Quran data pipeline. Produces a SQLite database with full letter breakdown (base letter + 34 diacritic flags) for all 83,668 Quran words (~341,062 letters), served via PostgreSQL and Hasura GraphQL.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) — Python package manager
- [Docker](https://docs.docker.com/get-docker/) — for PostgreSQL + Hasura
- [`hasura-cli`](https://hasura.io/docs/latest/hasura-cli/install-hasura-cli/) — for metadata management

```bash
brew install uv hasura-cli
```

## Docker image

A pre-built image is published to GHCR on every push to `main`. It bakes in the source databases and runs the full pipeline against a PostgreSQL instance you supply:

```bash
docker run --rm \
  -e POSTGRES_DSN=postgresql://user:pass@host/db \
  ghcr.io/ahyaantech/quranletterbyletter:latest
```

Then apply Hasura metadata to wire up the GraphQL schema:

```bash
hasura metadata apply --project hasura --endpoint http://<hasura-host>:8080 --admin-secret <secret>
```

## Data Sources

Source databases are available as assets on the [v1.0-data GitHub Release](https://github.com/AhyaanTech/QuranLetterByLetter/releases/tag/v1.0-data). Download and place them in `data/source/` before building locally:

| File | Source |
|---|---|
| `qpc-hafs-word-by-word.db` | [Tarteel QUL](https://qul.tarteel.io/) |
| `digital-khatt-15-lines.db` | KFGQPC V2 15-line Mushaf layout |
| `qpc-hafs-tajweed.db` | QPC Tajweed colors *(optional)* |

## Local setup

### 1. Build the SQLite database

```bash
# Build core tables (words, ayahs, surahs, mushaf_pages, metadata)
uv run scripts/build_db.py --full

# Build letter_breakdown table
uv run scripts/build_letters.py
```

### 2. Start PostgreSQL + Hasura

```bash
cp .env.example .env   # configure credentials (defaults work for local dev)
docker compose up -d
```

### 3. Load data into PostgreSQL

```bash
uv run scripts/load_to_postgres.py --drop
```

### 4. Apply Hasura metadata (track tables + relationships)

```bash
hasura metadata apply --project hasura --endpoint http://localhost:8080 --admin-secret hasura_dev_secret
```

GraphQL API is now available at `http://localhost:8080/v1/graphql`.

## Development

### Validate the SQLite build

```bash
uv run scripts/build_db.py --validate
uv run scripts/build_letters.py --all-tests
uv run scripts/build_letters.py --stats
```

### Run PostgreSQL integration tests

```bash
uv run pytest tests/ -v
```

### Hasura console (auto-saves metadata changes to `hasura/metadata/`)

```bash
hasura console --project hasura --endpoint http://localhost:8080 --admin-secret hasura_dev_secret
```

Use this instead of opening `http://localhost:8080/console` directly — changes made here are written back to the YAML files in `hasura/metadata/` and can be committed to git.

### Re-apply metadata after pulling changes

```bash
hasura metadata apply --project hasura --endpoint http://localhost:8080 --admin-secret hasura_dev_secret
```

## Output Schema

| Table | Rows | Description |
|---|---|---|
| `words` | 83,668 | Core word text with surah/ayah/position |
| `ayahs` | 6,236 | Verse metadata (juz, hizb, sajda, page) |
| `surahs` | 114 | Chapter metadata |
| `mushaf_pages` | ~1.2M | Word layout on Mushaf pages (15 lines × 610 pages) |
| `letter_breakdown` | ~341,062 | Letter segmentation with 34 diacritic flags |
| `metadata` | — | Build timestamps and schema version |
