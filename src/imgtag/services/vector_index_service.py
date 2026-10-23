"""显式启动在线索引维护；开关不执行 DDL，状态以数据库目录为准。"""

from time import perf_counter

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from imgtag.core.logging_config import get_logger
from imgtag.db.database import engine
from imgtag.db.repositories.config import config_repository
from imgtag.db.repositories.vector_index import vector_index_repository
from imgtag.services.embedding_service import embedding_service

logger = get_logger(__name__)
# 独立连接不占应用查询池；驱动层也取消 30 秒查询上限，允许长时间在线构建。
index_engine = create_async_engine(
    engine.url, hide_parameters=True, poolclass=NullPool,
    connect_args={"command_timeout": None, "server_settings": {"application_name": "imgtag-index-maintenance"}},
)


class VectorIndexService:
    async def status(self, session) -> dict:
        state = await vector_index_repository.inspect(session)
        enabled = await config_repository.get_value(session, "search_hnsw_enabled", "false") == "true"
        expected = await embedding_service.get_dimensions()
        if not state["supported"]:
            state["message"] = "当前环境暂不支持索引加速，继续使用精确搜索"
        return {key: value for key, value in {
            **state, "enabled": enabled, "active": enabled and state["ready"] and state["supported"] and expected == state["dimensions"],
            "dimensions_match": expected == state["dimensions"],
        }.items() if key not in {"table_oid", "schema_name", "qualified_table"}}

    async def prepare(self, *, force: bool = False):
        conn = await index_engine.connect()
        locked = False
        table = None
        try:
            conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            table = await vector_index_repository.table_info(conn)
            locked = await vector_index_repository.acquire(conn, table["table_oid"])
            if not locked:
                raise ValueError("索引维护任务已经在运行")
            state = await vector_index_repository.inspect(conn)
            if not state.get("supported", True):
                raise ValueError("索引加速需要 pgvector 0.8 或更高版本，且普通向量维度不超过 2000")
            if state["ready"] and not force:
                await vector_index_repository.release(conn, table["table_oid"])
                await conn.close()
                return None
            dimensions = await embedding_service.get_dimensions()
            if dimensions != table["dimensions"]:
                raise ValueError("配置与数据库维度不一致，请先处理维度并重建向量")
            if not 0 < dimensions <= 2000:
                raise ValueError("当前 HNSW 索引支持 1 至 2000 维向量")
            await vector_index_repository.save_state(conn)
            return conn, table, state["ready"], force
        except BaseException:
            try:
                if locked:
                    await vector_index_repository.release(conn, table["table_oid"])
            finally:
                await conn.invalidate()
                await conn.close()
            raise

    async def run(self, conn, table, ready: bool, force: bool) -> None:
        started = perf_counter()
        logger.info("开始维护 HNSW 索引: force=%s ready=%s", force, ready)
        try:
            await vector_index_repository.build(conn, table, force=force, ready=ready)
            await vector_index_repository.save_state(conn)
            logger.info("HNSW 索引维护完成: elapsed_ms=%.2f", (perf_counter() - started) * 1000)
        except SQLAlchemyError as exc:
            if getattr(getattr(exc, "orig", None), "sqlstate", None) == "55P03":
                error = "索引维护等待数据库锁超过 30 秒，请在相关长事务结束后重试；已有可用索引继续复用，否则使用精确搜索"
                logger.warning("HNSW 索引维护等待锁超时: elapsed_ms=%.2f", (perf_counter() - started) * 1000)
            else:
                error = "索引维护失败，请查看服务日志后重试；已有可用索引继续复用，否则使用精确搜索"
                logger.exception("HNSW 索引维护失败: elapsed_ms=%.2f", (perf_counter() - started) * 1000)
            await vector_index_repository.save_state(conn, error=error)
        finally:
            try:
                await conn.exec_driver_sql("RESET lock_timeout")
                await conn.exec_driver_sql("RESET statement_timeout")
                await vector_index_repository.release(conn, table["table_oid"])
            finally:
                # 断开物理连接，确保取消/异常时会话级锁也不会留在连接池中。
                await conn.invalidate()
                await conn.close()


vector_index_service = VectorIndexService()
