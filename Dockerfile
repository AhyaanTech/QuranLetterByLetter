# Build the full Quran pipeline and load data into PostgreSQL.
#
# Source databases are downloaded from a GitHub Release at build time so the
# resulting image is self-contained — just supply a POSTGRES_DSN at runtime.
#
# Build:
#   docker build \
#     --build-arg RELEASE_URL=https://github.com/ahyaantech/QuranLetterByLetter/releases/download/v1.0-data \
#     -t ghcr.io/ahyaantech/quranletterbyletter:latest .
#
# Run:
#   docker run --rm -e POSTGRES_DSN=postgresql://user:pass@host/db \
#     ghcr.io/ahyaantech/quranletterbyletter:latest

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

# Download source databases from GitHub Release (baked into the image)
ARG RELEASE_URL=https://github.com/ahyaantech/QuranLetterByLetter/releases/download/v1.0-data
ADD ${RELEASE_URL}/qpc-hafs-word-by-word.db  data/source/qpc-hafs-word-by-word.db
ADD ${RELEASE_URL}/digital-khatt-15-lines.db data/source/digital-khatt-15-lines.db
ADD ${RELEASE_URL}/qpc-hafs-tajweed.db       data/source/qpc-hafs-tajweed.db

# Install dependencies
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen

# Copy pipeline scripts
COPY scripts/ scripts/

ENTRYPOINT ["uv", "run", "scripts/entrypoint.py"]
