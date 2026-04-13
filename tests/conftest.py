"""Shared pytest fixtures for PostgreSQL integration tests."""

import os
from pathlib import Path
import pytest
import psycopg
from psycopg.rows import dict_row

# Load .env from project root (if present) without overriding existing env vars
_ENV_FILE = Path(__file__).parent.parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

_DEFAULT_DSN = (
    os.environ.get("POSTGRES_DSN")
    or os.environ.get("DATABASE_URL")
    or "postgresql://quran:quran@localhost:5432/quran"
)


@pytest.fixture(scope="session")
def pg_conn():
    """Session-scoped connection to the test PostgreSQL database.

    Skips the entire session if PostgreSQL is not reachable, so tests can run
    in environments without Docker (e.g. CI without a PG service container).
    """
    try:
        conn = psycopg.connect(_DEFAULT_DSN, row_factory=dict_row)
    except psycopg.OperationalError as e:
        pytest.skip(
            f"PostgreSQL not available at {_DEFAULT_DSN!r} — "
            f"start with 'docker compose up -d' and load with "
            f"'uv run scripts/load_to_postgres.py --drop'. Error: {e}"
        )
    yield conn
    conn.close()
