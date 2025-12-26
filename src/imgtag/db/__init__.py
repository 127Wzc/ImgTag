#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Database module.

Provides SQLAlchemy-based async database access.
All legacy synchronous code has been removed.
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

# Repository exports for convenience
from imgtag.db.repositories import (
    config_repository,
    image_repository,
    tag_repository,
    image_tag_repository,
    user_repository,
    collection_repository,
    image_collection_repository,
    task_repository,
    approval_repository,
    audit_log_repository,
)

__all__ = [
    # Database engine and session
    "engine",
    "async_session_maker",
    "get_async_session",
    "get_session_context",
    "init_db",
    "close_db",
    # Repositories
    "config_repository",
    "image_repository",
    "tag_repository",
    "image_tag_repository",
    "user_repository",
    "collection_repository",
    "image_collection_repository",
    "task_repository",
    "approval_repository",
    "audit_log_repository",
]
