#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Database module.

Provides both legacy (PGVectorDB) and new (SQLAlchemy) database access.
Migration in progress: new code should use `from imgtag.db.database import get_async_session`.
"""

# New SQLAlchemy-based database access
from imgtag.db.database import (
    engine,
    async_session_maker,
    get_async_session,
    get_session_context,
    init_db,
    close_db,
)

# Config DB - direct import (no psycopg dependency)
from imgtag.db.config_db import ConfigDB, config_db

# Legacy PGVectorDB (will be deprecated) - lazy import to avoid psycopg
def __getattr__(name: str):
    """Lazy import for legacy modules with psycopg dependency."""
    if name in ("PGVectorDB", "db"):
        from imgtag.db.pg_vector import PGVectorDB, db
        return PGVectorDB if name == "PGVectorDB" else db
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # New SQLAlchemy exports
    "engine",
    "async_session_maker", 
    "get_async_session",
    "get_session_context",
    "init_db",
    "close_db",
    # Config (direct import)
    "ConfigDB",
    "config_db",
    # Legacy exports (lazy loaded)
    "PGVectorDB",
    "db",
]

