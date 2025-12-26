"""Async database connection and session management.

Provides SQLAlchemy async engine and session factory for the application.
"""

import re
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)


def get_async_database_url(url: str) -> str:
    """Convert a standard PostgreSQL URL to asyncpg format.

    asyncpg only supports a limited set of connection parameters as URL query params.
    This function strips out unsupported psycopg/libpq params.

    Args:
        url: PostgreSQL connection URL (postgresql://... or postgresql+psycopg://...).

    Returns:
        Async-compatible URL (postgresql+asyncpg://...).
    """
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    # Replace driver with asyncpg
    async_url = re.sub(
        r"^postgresql(\+\w+)?://",
        "postgresql+asyncpg://",
        url,
    )

    # Parse URL and keep only asyncpg-supported params
    parsed = urlparse(async_url)
    query_params = parse_qs(parsed.query)

    # asyncpg only supports these connection params in URL
    # See: https://magicstack.github.io/asyncpg/current/api/index.html#connection
    asyncpg_supported_params = {
        "command_timeout",
        "statement_cache_size", 
        "max_cached_statement_lifetime",
        "max_cacheable_statement_size",
    }

    # Filter to only supported params
    filtered_params = {
        k: v for k, v in query_params.items() 
        if k in asyncpg_supported_params
    }

    # Rebuild URL with only supported params
    new_query = urlencode(filtered_params, doseq=True)
    new_parsed = parsed._replace(query=new_query)
    return urlunparse(new_parsed)


# Create async engine with connection pooling
_async_url = get_async_database_url(settings.PG_CONNECTION_STRING)
engine = create_async_engine(
    _async_url,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=300,  # Recycle connections after 5 minutes
    echo=False,  # Set to True for SQL debugging
)

# Session factory for creating new sessions
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for getting a database session.

    Yields:
        AsyncSession: Database session that auto-commits on success
        and rollbacks on exception.

    Example:
        @app.get("/users")
        async def get_users(session: AsyncSession = Depends(get_async_session)):
            result = await session.execute(select(User))
            return result.scalars().all()
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_session_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for getting a database session outside of FastAPI.

    Use this for background tasks, scripts, or CLI commands.

    Yields:
        AsyncSession: Database session.

    Example:
        async with get_session_context() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize database tables.

    Creates all tables defined in the ORM models if they don't exist.
    For production, use Alembic migrations instead.
    """
    from imgtag.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")


async def close_db() -> None:
    """Close database connections.

    Should be called on application shutdown.
    """
    await engine.dispose()
    logger.info("Database connections closed")
