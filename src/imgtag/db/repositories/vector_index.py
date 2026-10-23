"""向量索引目录、在线 DDL 与跨进程维护锁。"""

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from imgtag.core.internal_config import HNSW_STATE_KEY

INDEX_NAME = "ix_images_embedding_hnsw"
INDEX_LOCK = 824713


class VectorIndexRepository:
    async def search_options(self, session: AsyncSession) -> dict:
        """一次读取运行参数与索引可用性；关闭时不执行目录子查询。"""
        row = (await session.execute(text("""
            WITH settings AS (
                SELECT COALESCE(MAX(value) FILTER (WHERE key = 'search_hnsw_enabled'), 'false') AS enabled,
                       COALESCE(MAX(value) FILTER (WHERE key = 'search_hnsw_ef_search'), '40')::int AS ef_search
                FROM config WHERE key IN ('search_hnsw_enabled', 'search_hnsw_ef_search')
            )
            SELECT enabled = 'true' AS enabled, ef_search,
                   CASE WHEN enabled = 'true' THEN EXISTS (
                SELECT 1 FROM pg_index x JOIN pg_class c ON c.oid = x.indexrelid
                JOIN pg_am am ON am.oid = c.relam
                JOIN pg_attribute a ON a.attrelid = x.indrelid AND a.attnum = x.indkey[0]
                JOIN pg_opclass o ON o.oid = x.indclass[0]
                JOIN pg_extension e ON e.extname = 'vector'
                WHERE x.indrelid = to_regclass('images') AND c.relname = :name
                  AND x.indisvalid AND x.indisready AND am.amname = 'hnsw'
                  AND x.indnatts = 1 AND x.indexprs IS NULL AND x.indpred IS NULL
                  AND a.attname = 'embedding' AND o.opcname = 'vector_cosine_ops'
                  AND a.atttypmod BETWEEN 1 AND 2000
                  AND ARRAY[split_part(e.extversion, '.', 1)::int,
                            split_part(e.extversion, '.', 2)::int] >= ARRAY[0, 8]
            ) ELSE false END AS index_ready FROM settings
        """), {"name": INDEX_NAME})).mappings().one()
        return dict(row)

    async def table_info(self, connection: AsyncConnection | AsyncSession) -> dict:
        row = (await connection.execute(text("""
            SELECT c.oid::integer AS table_oid, n.nspname AS schema_name,
                   a.atttypmod AS dimensions,
                   (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS vector_version,
                   quote_ident(n.nspname) || '.' || quote_ident(c.relname) AS qualified_table
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'embedding'
            WHERE c.oid = to_regclass('images')
        """))).mappings().one()
        return dict(row)

    async def inspect(self, session: AsyncConnection | AsyncSession) -> dict:
        table = await self.table_info(session)
        result = await session.execute(text("""
            SELECT x.indisvalid AND x.indisready AND am.amname = 'hnsw'
                       AND x.indnatts = 1 AND x.indexprs IS NULL AND x.indpred IS NULL
                       AND a.attname = 'embedding' AND o.opcname = 'vector_cosine_ops' AS ready,
                   pg_relation_size(c.oid) AS size_bytes
            FROM pg_class c JOIN pg_index x ON x.indexrelid = c.oid
            JOIN pg_am am ON am.oid = c.relam
            JOIN pg_attribute a ON a.attrelid = x.indrelid AND a.attnum = x.indkey[0]
            JOIN pg_opclass o ON o.oid = x.indclass[0]
            WHERE x.indrelid = :table_oid AND c.relname = :name
        """), {"table_oid": table["table_oid"], "name": INDEX_NAME})
        row = result.mappings().one_or_none()
        running = bool((await session.execute(text("""
            SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory'
                AND classid = :table_oid AND objid = :key AND objsubid = 2 AND granted)
        """), {"table_oid": table["table_oid"], "key": INDEX_LOCK})).scalar_one())
        raw_state = (await session.execute(text("SELECT value FROM config WHERE key = :key"),
                                           {"key": HNSW_STATE_KEY})).scalar_one_or_none()
        state = json.loads(raw_state) if raw_state else {}
        ready = bool(row and row["ready"])
        supported = (0 < table["dimensions"] <= 2000 and
                     tuple(int(part) for part in table["vector_version"].split('.')[:2]) >= (0, 8))
        return {
            **table, "ready": ready, "supported": supported, "exists": row is not None,
            "size_bytes": int(row["size_bytes"]) if row else 0,
            "is_running": running,
            "state": "building" if running else "ready" if ready else "failed" if state.get("error") else "invalid" if row else "missing",
            "last_error": state.get("error", ""),
            "message": ("索引维护中，搜索继续可用" if running else "索引已就绪，可直接复用" if ready
                        else state.get("error") or ("索引未完成或不可用，请重新构建；当前使用精确搜索" if row
                                                    else "尚未构建，当前使用精确搜索")),
        }

    async def acquire(self, conn: AsyncConnection, table_oid: int) -> bool:
        return bool((await conn.execute(text("SELECT pg_try_advisory_lock(:oid, :key)"),
                                       {"oid": table_oid, "key": INDEX_LOCK})).scalar_one())

    async def release(self, conn: AsyncConnection, table_oid: int) -> None:
        await conn.execute(text("SELECT pg_advisory_unlock(:oid, :key)"), {"oid": table_oid, "key": INDEX_LOCK})

    async def lock_resize(self, session: AsyncSession) -> None:
        table = await self.table_info(session)
        locked = (await session.execute(text("SELECT pg_try_advisory_xact_lock(:oid, :key)"),
                                        {"oid": table["table_oid"], "key": INDEX_LOCK})).scalar_one()
        if not locked:
            raise ValueError("索引正在维护，请完成后再调整向量维度")

    async def save_state(self, conn: AsyncConnection, *, error: str = "") -> None:
        await conn.execute(text("""
            INSERT INTO config (key, value, is_secret, updated_at) VALUES (:key, :value, false, now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """), {"key": HNSW_STATE_KEY, "value": json.dumps({"error": error}, ensure_ascii=False)})

    async def build(self, conn: AsyncConnection, table: dict, *, force: bool, ready: bool) -> None:
        # 标识符来自系统目录并通过方言引用，不拼入用户输入。
        quoted_index = conn.dialect.identifier_preparer.quote(INDEX_NAME)
        qualified_index = conn.dialect.identifier_preparer.quote_schema(table["schema_name"]) + "." + quoted_index
        # 在线 DDL 仍需等待旧事务；短暂写入不应使维护立即失败，但等待必须有上限。
        await conn.execute(text("SET lock_timeout = '30s'"))
        await conn.execute(text("SET statement_timeout = '0'"))
        # REINDEX CONCURRENTLY 中断可能留下无效的 _ccnew/_ccold 索引，仅清理本工具的遗留项。
        remnants = (await conn.execute(text("""
            SELECT c.relname FROM pg_class c JOIN pg_index x ON x.indexrelid = c.oid
            WHERE x.indrelid = :table_oid AND NOT x.indisvalid
              AND c.relname ~ '^ix_images_embedding_hnsw_cc(new|old)[0-9]*$'
        """), {"table_oid": table["table_oid"]})).scalars().all()
        for name in remnants:
            qualified = conn.dialect.identifier_preparer.quote_schema(table["schema_name"]) + "." + conn.dialect.identifier_preparer.quote(name)
            await conn.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {qualified}"))
        if force and ready:
            # 在线替换保留旧索引；重建期间可继续服务已有查询。
            await conn.execute(text(f"REINDEX INDEX CONCURRENTLY {qualified_index}"))
        else:
            await conn.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {qualified_index}"))
            await conn.execute(text(
                f"CREATE INDEX CONCURRENTLY {quoted_index} ON {table['qualified_table']} "
                "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
            ))

    async def drop_for_resize(self, session: AsyncSession) -> None:
        table = await self.table_info(session)
        quote = session.bind.dialect.identifier_preparer
        for name in (INDEX_NAME, "ix_images_embedding", "idx_images_embedding"):
            await session.execute(text(f"DROP INDEX IF EXISTS {quote.quote_schema(table['schema_name'])}.{quote.quote(name)}"))


vector_index_repository = VectorIndexRepository()
