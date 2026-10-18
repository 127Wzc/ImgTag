"""仅显式启用时连接 PostgreSQL，测试 schema 随事务回滚。"""

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from imgtag.core.config import settings
from imgtag.db.database import get_async_database_url


@pytest.fixture
async def postgres_connection():
    if os.environ.get('IMGTAG_TEST_POSTGRES') != '1':
        pytest.skip('设置 IMGTAG_TEST_POSTGRES=1 执行 PostgreSQL 回滚测试')
    engine = create_async_engine(get_async_database_url(settings.PG_CONNECTION_STRING))
    schema = 'test_imgtag_' + uuid4().hex
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
                yield connection
            finally:
                await transaction.rollback()
            count = await connection.scalar(text('SELECT count(*) FROM pg_namespace WHERE nspname=:schema'), {'schema': schema})
            assert count == 0, '回滚后不应残留测试 schema'
    finally:
        await engine.dispose()
