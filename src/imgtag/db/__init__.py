#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Database module.

Provides SQLAlchemy-based async database access.

NOTE: Repositories are NOT auto-imported here to avoid circular dependencies.
Import repositories explicitly from `imgtag.db.repositories` when needed.
"""

# SQLAlchemy async database access
from imgtag.db.database import (
    engine,
    async_session_maker,
    get_async_session,
    get_session_context,
    init_db,
    close_db,
)

__all__ = [
    # Database engine and session
    "engine",
    "async_session_maker",
    "get_async_session",
    "get_session_context",
    "init_db",
    "close_db",
]

