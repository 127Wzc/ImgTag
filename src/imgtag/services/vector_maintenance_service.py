"""异常向量扫描与单图重建，复用现有持久化任务队列。"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.db.repositories import image_repository
from imgtag.schemas.base import PaginatedResponse
from imgtag.services.embedding_service import embedding_service
from imgtag.services.storage_service import storage_service
from imgtag.services.task_queue import task_queue


class VectorMaintenanceService:
    async def scan(self, session: AsyncSession, *, page: int, size: int) -> dict:
        dimensions = await embedding_service.get_dimensions()
        db_dimensions = await image_repository.get_embedding_dimensions(session)
        rows, total = await image_repository.find_embedding_anomalies(
            session, dimensions, limit=size, offset=(page - 1) * size,
        )
        ids = [row["id"] for row in rows]
        if ids:
            images = await image_repository.get_by_ids(session, ids)
            urls = await storage_service.get_read_urls_with_session(session, list(images))
            tags = await image_repository.get_batch_image_tags_with_source(session, ids)
            for row in rows:
                row["image_url"] = urls.get(row["id"], "")
                row["tags"] = [tag["name"] for tag in tags.get(row["id"], []) if tag["level"] in (0, 2)]
        return {
            **PaginatedResponse.create(rows, total, page, size).model_dump(),
            "expected_dimensions": dimensions, "db_dimensions": db_dimensions,
        }

    async def rebuild_image(self, session: AsyncSession, image_id: int) -> dict:
        image = await image_repository.get_with_tags(session, image_id)
        if image is None:
            raise HTTPException(404, "图片不存在")
        if not (image.description or "").strip() and not any(
            tag.name.strip() for tag in image.tags if tag.level in (0, 2)
        ):
            raise HTTPException(400, "图片没有可用于生成向量的描述或标签，请先补充内容")
        if await embedding_service.get_dimensions() != await image_repository.get_embedding_dimensions(session):
            raise HTTPException(409, "配置与数据库的向量维度不一致，请先在向量嵌入设置中处理维度配置")
        return await task_queue.enqueue_tasks([image_id], task_type="rebuild_vector", session=session)


vector_maintenance_service = VectorMaintenanceService()
