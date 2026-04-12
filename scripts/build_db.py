#!/usr/bin/env python3
"""Quran Database Builder - Main Entry Point

Builds the offline Quran database from source files and validates integrity.

Usage:
    uv run scripts/build_db.py              # Full build + validate
    uv run scripts/build_db.py --build      # Build only
    uv run scripts/build_db.py --validate   # Validate only
    uv run scripts/build_db.py --schema     # Show schema
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from quran_db.cli import main

if __name__ == "__main__":
    sys.exit(main())
