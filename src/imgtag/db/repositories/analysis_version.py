"""图片分析历史，只保留最近三份被替换的内容。"""
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.db.repositories.base import BaseRepository
from imgtag.models.analysis_version import ImageAnalysisVersion


class AnalysisVersionRepository(BaseRepository[ImageAnalysisVersion]):
    model = ImageAnalysisVersion

    async def get_history(self, session: AsyncSession, image_id: int, version_id: int):
        result = await session.execute(select(ImageAnalysisVersion).where(
            ImageAnalysisVersion.id == version_id, ImageAnalysisVersion.image_id == image_id,
            ImageAnalysisVersion.state == "history").with_for_update().execution_options(populate_existing=True))
        return result.scalar_one_or_none()

    async def prune_history(self, session: AsyncSession, image_id: int):
        older = select(self.model.id).where(self.model.image_id == image_id).order_by(self.model.id.desc()).offset(3)
        await session.execute(delete(self.model).where(self.model.id.in_(older))
                              .execution_options(synchronize_session=False))

    async def versions(self, session: AsyncSession, image_id: int, offset: int = 0):
        result = await session.execute(select(self.model).where(
            self.model.image_id == image_id, self.model.state == "history")
            .order_by(self.model.id.desc()).offset(offset).limit(3))
        return result.scalars().all()


analysis_version_repository = AnalysisVersionRepository()
