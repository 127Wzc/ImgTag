"""全库向量重建与进度管理。"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.config_cache import config_cache
from imgtag.core.logging_config import get_logger
from imgtag.db.database import async_session_maker, engine
from imgtag.db.repositories import config_repository, image_repository
from imgtag.services.embedding_service import embedding_service

logger = get_logger(__name__)


class VectorRebuildService:
    def __init__(self):
        self.status: dict[str, Any] = {}
        self._reset(running=False)

    def _reset(self, *, running: bool) -> None:
        # 保持字典身份稳定，端点和状态响应始终读取同一份进度。
        self.status.update(
            is_running=running,
            total=0,
            processed=0,
            succeeded=0,
            skipped=0,
            failed=0,
            last_error="",
            message="正在准备重建..." if running else "",
        )

    async def prepare(self, session: AsyncSession) -> int:
        """先占用任务状态，再校验维度，防止启动与首次轮询之间的竞态。"""
        if self.status["is_running"]:
            raise ValueError("重建任务正在进行中")
        self._reset(running=True)
        try:
            expected_dim = await embedding_service.get_dimensions()
            if expected_dim <= 0:
                raise ValueError("向量维度必须大于 0")
            db_dim = await image_repository.get_embedding_dimensions(session)
            if expected_dim != db_dim:
                logger.info("自动调整向量维度: %s -> %s", db_dim, expected_dim)
                await image_repository.resize_embedding_dimensions(session, expected_dim)
                await config_repository.set_value(session, "embedding_dimensions", str(expected_dim))
                await session.commit()
                await config_cache.refresh()
                # DDL 会使 asyncpg 的语句缓存失效，重建前回收连接池。
                await engine.dispose()
            embedding_service.reload_model()
            return expected_dim
        except Exception as exc:
            self.status.update(is_running=False, message=f"准备重建失败: {exc}")
            await session.rollback()
            logger.exception("准备向量重建失败")
            raise

    async def run(self) -> None:
        """逐张处理，成功、失败或跳过都计入已处理进度。"""
        self.status["message"] = "正在获取图片列表..."
        try:
            async with async_session_maker() as session:
                images = await image_repository.list_embedding_inputs(session)
            self.status["total"] = len(images)
            logger.info("开始重建向量: 共 %s 张图片", len(images))

            for image_id, description, tags in images:
                try:
                    if not (description or "").strip() and not any((tag or "").strip() for tag in tags or []):
                        self.status["skipped"] += 1
                        continue
                    embedding = await embedding_service.get_embedding_combined(description or "", tags or [])
                    async with async_session_maker() as session:
                        updated = await image_repository.set_embedding(session, image_id, embedding)
                        await session.commit()
                    self.status["succeeded" if updated else "skipped"] += 1
                except Exception as exc:
                    logger.error("重建图片 %s 向量失败: %s", image_id, exc)
                    self.status["failed"] += 1
                    self.status["last_error"] = str(exc)[:500]
                finally:
                    self.status["processed"] += 1
                    self.status["message"] = (
                        f"已处理 {self.status['processed']}/{self.status['total']}，"
                        f"成功 {self.status['succeeded']}，失败 {self.status['failed']}，"
                        f"跳过 {self.status['skipped']}"
                    )

            self.status["message"] = (
                f"重建完成: 成功 {self.status['succeeded']}，"
                f"失败 {self.status['failed']}，跳过 {self.status['skipped']}"
            )
            logger.info(self.status["message"])
        except Exception as exc:
            logger.exception("向量重建任务失败")
            self.status["message"] = f"重建失败: {exc}"
            self.status["last_error"] = str(exc)[:500]
        finally:
            self.status["is_running"] = False


vector_rebuild_service = VectorRebuildService()
