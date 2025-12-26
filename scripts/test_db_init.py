#!/usr/bin/env python
"""Test database initialization with Alembic migrations.

Usage:
    # Set a different database connection string
    export PG_CONNECTION_STRING="postgresql://user:pass@host:5432/new_db_name"
    
    # Run this script
    uv run python scripts/test_db_init.py
"""

import asyncio
import sys

from sqlalchemy import text

from imgtag.core.config import settings
from imgtag.db.database import engine, get_async_database_url


async def test_db_connection():
    """Test database connection."""
    url = get_async_database_url(settings.PG_CONNECTION_STRING)
    db_name = settings.PG_CONNECTION_STRING.split("/")[-1].split("?")[0]
    
    print(f"Testing database: {db_name}")
    print(f"Async URL: {url[:50]}...")
    
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            print("✓ Database connection successful")
            return True
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False


async def check_tables():
    """Check which tables exist."""
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """))
        tables = [row[0] for row in result]
        
        if tables:
            print(f"\nExisting tables ({len(tables)}):")
            for t in tables:
                print(f"  - {t}")
        else:
            print("\n✓ Database is empty (fresh installation)")
        
        return tables


async def main():
    print("=" * 50)
    print("Database Initialization Test")
    print("=" * 50)
    
    if not await test_db_connection():
        sys.exit(1)
    
    tables = await check_tables()
    
    print("\n" + "=" * 50)
    if not tables:
        print("Ready for: uv run alembic upgrade head")
    elif "alembic_version" in tables:
        print("Alembic already initialized")
        print("To upgrade: uv run alembic upgrade head")
    else:
        print("Tables exist but no alembic_version")
        print("To stamp existing: uv run alembic stamp head")
    print("=" * 50)
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
