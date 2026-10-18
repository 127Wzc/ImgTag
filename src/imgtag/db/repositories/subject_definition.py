"""主体提炼模板与版本的数据访问。"""
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.db.repositories.base import BaseRepository
from imgtag.models.subject import Subject, SubjectDefinitionVersion, SubjectPromptTemplate

SUBJECT_HISTORY_LIMIT = 3


class SubjectDefinitionRepository(BaseRepository[SubjectDefinitionVersion]):
    model = SubjectDefinitionVersion

    async def create(self, session: AsyncSession, **kwargs) -> SubjectDefinitionVersion:
        # 写入方锁定主体，备份、清理、替换在同一事务提交。
        row = await super().create(session, **kwargs)
        await self.prune_history(session, row.subject_id)
        return row

    async def get_history(self, session: AsyncSession, subject_id: int, version_id: int):
        result = await session.execute(select(SubjectDefinitionVersion).where(
            SubjectDefinitionVersion.id == version_id, SubjectDefinitionVersion.subject_id == subject_id,
            SubjectDefinitionVersion.state == "history").with_for_update().execution_options(populate_existing=True))
        return result.scalar_one_or_none()

    async def prune_history(self, session: AsyncSession, subject_id: int) -> None:
        """当前内容在 subjects，历史独立保留最近三份。"""
        older = (select(SubjectDefinitionVersion.id)
            .where(SubjectDefinitionVersion.subject_id == subject_id)
            .order_by(SubjectDefinitionVersion.id.desc()).offset(SUBJECT_HISTORY_LIMIT))
        await session.execute(delete(SubjectDefinitionVersion)
            .where(SubjectDefinitionVersion.id.in_(older))
            .execution_options(synchronize_session=False))

    async def lock_subject(self, session: AsyncSession, subject_id: int) -> Subject | None:
        result = await session.execute(select(Subject).where(Subject.id == subject_id)
                                       .with_for_update().execution_options(populate_existing=True))
        return result.scalar_one_or_none()

    async def list_versions(self, session: AsyncSession, subject_id: int, offset: int = 0):
        # 顺便收束旧数据，父行锁避免与提炼和手动修改交错。
        if await self.lock_subject(session, subject_id) is None:
            return []
        await self.prune_history(session, subject_id)
        result = await session.execute(select(SubjectDefinitionVersion)
            .where(SubjectDefinitionVersion.subject_id == subject_id, SubjectDefinitionVersion.state == "history")
            .order_by(SubjectDefinitionVersion.id.desc()).limit(SUBJECT_HISTORY_LIMIT).offset(offset))
        return result.scalars().all()



class SubjectTemplateRepository(BaseRepository[SubjectPromptTemplate]):
    model = SubjectPromptTemplate

    async def list_templates(self, session: AsyncSession):
        result = await session.execute(select(SubjectPromptTemplate)
                                      .order_by(SubjectPromptTemplate.is_builtin.desc(), SubjectPromptTemplate.id))
        return result.scalars().all()


subject_definition_repository = SubjectDefinitionRepository()
subject_template_repository = SubjectTemplateRepository()
