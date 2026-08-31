"""The MySQL connection, and nothing else.

A leaf like config.py and contracts.py: pymysql plus config, no project module
above it, so every feature's `db.py` opens connections the same way. It exists
because there is now more than one of them -- `jobs/db.py` and
`companies/db.py` -- and the pooling note below is a change that must land in
one place, not two.
"""
from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.cursors import Cursor, DictCursor

from backend.config import DB

# Re-exported so main.py can answer 503 without importing pymysql
# (architecture.md 2). Covers refused connections and a missing database.
Unavailable = pymysql.err.OperationalError

# ponytail: one connection per call, no pool -- v1 runs one job at a time.
# Add DBUtils/SQLAlchemy pooling if concurrency ever makes connect() cost real.


@contextmanager
def cursor() -> Iterator[Cursor]:
    conn = pymysql.connect(**DB, cursorclass=DictCursor, autocommit=True)
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()
