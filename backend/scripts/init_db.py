"""Create (or re-create with --reset) the tables from sql/schema.sql.

Usage:
    python -m scripts.init_db            # create tables in an empty database
    python -m scripts.init_db --reset    # DROP everything first (local/dev only!)
"""
import argparse
from pathlib import Path

import psycopg

from app.config import settings

SCHEMA = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"


def init(url: str, reset: bool = False) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        if reset:
            conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        conn.execute(SCHEMA.read_text(encoding="utf-8"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--url", default=settings.database_url)
    a = ap.parse_args()
    init(a.url, a.reset)
    print("schema ready")
