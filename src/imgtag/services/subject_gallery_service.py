"""主体标签图库与封面；关联数量不代表本次提炼参考图。"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.db.repositories import subject_repository
from imgtag.schemas.base import PaginatedResponse
from imgtag.schemas.subject import SubjectReferenceImage
from imgtag.services.storage_service import storage_service


class SubjectGalleryService:
    async def reference_images(self, session: AsyncSession, subject_id: int, *, page: int, size: int, keyword: str):
        subject = await subject_repository.get_by_id(session, subject_id)
        if subject is None:
            raise HTTPException(404, "主体不存在")
        images, total = await subject_repository.tagged_images(session, subject.primary_tag_id,
                                                               page=page, size=size, keyword=keyword)
        urls = await storage_service.get_read_urls_with_session(session, images)
        return PaginatedResponse[SubjectReferenceImage].create([
            SubjectReferenceImage(id=image.id, image_url=urls.get(image.id, ""), description=image.description)
            for image in images], total, page, size)

    async def cover_urls(self, session: AsyncSession, subjects) -> dict[int, str]:
        images = {row.cover_image.id: row.cover_image for row in subjects if getattr(row, "cover_image", None)}
        return await storage_service.get_read_urls_with_session(session, list(images.values()))

    async def associate_on_create(self, session: AsyncSession, subject, actor_id: int | None) -> int:
        return await subject_repository.associate_tagged_images(session, subject, actor_id)


subject_gallery_service = SubjectGalleryService()
