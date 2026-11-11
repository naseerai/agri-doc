"""
tests/conftest.py — Shared pytest configuration and fixtures.
"""

import os
import sys

# Ensure the project root is on the path for all tests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use in-memory SQLite for all tests (avoids contaminating real DB)
os.environ["DATABASE_PATH"] = ":memory:"

# Patch database module to always use a single shared connection for :memory:
# so tables created by initialize_database() are visible to subsequent calls.
import sqlite3
import database as _db_module

_SHARED_CONN = sqlite3.connect(":memory:", check_same_thread=False)
_SHARED_CONN.row_factory = sqlite3.Row


def _shared_get_connection():
    """Yield the single shared in-memory connection for all test calls."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        try:
            yield _SHARED_CONN
            _SHARED_CONN.commit()
        except Exception:
            _SHARED_CONN.rollback()
            raise
    return _ctx()


# Monkey-patch the database module's get_connection to use shared connection
import contextlib

@contextlib.contextmanager
def _patched_get_connection():
    try:
        yield _SHARED_CONN
        _SHARED_CONN.commit()
    except Exception:
        _SHARED_CONN.rollback()
        raise

_db_module.get_connection = _patched_get_connection

# Initialize tables once on the shared connection
_db_module.initialize_database()
