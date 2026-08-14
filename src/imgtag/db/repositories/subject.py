"""Subject repositories."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from imgtag.db.repositories.base import BaseRepository
from imgtag.models.subject import ImageSubject, Subject, SubjectSample
from imgtag.models.tag import Tag


class SubjectRepository(BaseRepository[Subject]):
    """主体词典仓库。"""

    model = Subject

    async def get_by_name(self, session: AsyncSession, name: str) -> Optional[Subject]:
        stmt = select(Subject).where(Subject.name == name)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_primary_tag_id(
        self,
        session: AsyncSession,
        primary_tag_id: int,
    ) -> Optional[Subject]:
        stmt = select(Subject).where(Subject.primary_tag_id == primary_tag_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_with_relations(
        self,
        session: AsyncSession,
        subject_id: int,
    ) -> Optional[Subject]:
        stmt = (
            select(Subject)
            .options(
                selectinload(Subject.category_tag),
                selectinload(Subject.primary_tag),
            )
            .where(Subject.id == subject_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_subjects(
        self,
        session: AsyncSession,
        *,
        limit: int = 100,
        offset: int = 0,
        keyword: str | None = None,
        active_only: bool = True,
    ) -> Sequence[Subject]:
        stmt = (
            select(Subject)
            .options(
                selectinload(Subject.category_tag),
                selectinload(Subject.primary_tag),
            )
            .order_by(Subject.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if active_only:
            stmt = stmt.where(Subject.is_active == True)  # noqa: E712
        if keyword and keyword.strip():
            kw = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(Subject.name.ilike(kw), Subject.description.ilike(kw)))
        result = await session.execute(stmt)
        return result.scalars().all()

    async def create_with_tag_links(
        self,
        session: AsyncSession,
        *,
        category_tag_id: int,
        primary_tag_id: int,
        name: str,
        alias_tag_ids: list[int] | None = None,
        alias_names: list[str] | None = None,
        description: str | None = None,
        is_active: bool = True,
        created_by: int | None = None,
    ) -> Subject:
        alias_ids = sorted(set(int(i) for i in (alias_tag_ids or []) if int(i) > 0))

        subject = await self.create(
            session,
            name=name,
            alias_tag_ids=alias_ids or None,
            aliases=alias_names or [],
            description=description,
            is_active=is_active,
            category_tag_id=category_tag_id,
            primary_tag_id=primary_tag_id,
            created_by=created_by,
        )

        related = await self.get_by_id_with_relations(session, subject.id)
        return related if related else subject

    async def list_referencing_tag(
        self,
        session: AsyncSession,
        tag_id: int,
    ) -> Sequence[Subject]:
        """查询引用了指定标签的主体（主名称 / 分类 / 别名），用于标签删除保护。"""
        stmt = select(Subject).where(
            or_(
                Subject.primary_tag_id == tag_id,
                Subject.category_tag_id == tag_id,
                Subject.alias_tag_ids.contains([tag_id]),
            )
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def sync_tag_rename(
        self,
        session: AsyncSession,
        *,
        tag_id: int,
        new_name: str,
    ) -> int:
        """标签改名后同步主体冗余名称（主名称与别名列表），返回受影响主体数。"""
        result = await session.execute(
            update(Subject)
            .where(Subject.primary_tag_id == tag_id)
            .values(name=new_name, updated_at=datetime.now(timezone.utc))
        )
        affected = int(result.rowcount or 0)

        alias_stmt = select(Subject).where(Subject.alias_tag_ids.contains([tag_id]))
        alias_subjects = (await session.execute(alias_stmt)).scalars().all()
        for subject in alias_subjects:
            alias_ids = [int(i) for i in (subject.alias_tag_ids or []) if int(i) > 0]
            if not alias_ids:
                continue
            rows = (
                await session.execute(select(Tag.id, Tag.name).where(Tag.id.in_(alias_ids)))
            ).all()
            name_by_id = {int(row.id): str(row.name) for row in rows}
            subject.aliases = [name_by_id[i] for i in alias_ids if i in name_by_id]
        if alias_subjects:
            await session.flush()
        return affected + len(alias_subjects)


class SubjectSampleRepository(BaseRepository[SubjectSample]):
    """主体样本仓库。"""

    model = SubjectSample

    async def create_sample(
        self,
        session: AsyncSession,
        *,
        subject_id: int,
        image_id: int | None = None,
        embedding_model: str = "stub",
        embedding: list[float] | None = None,
        metadata: dict[str, Any] | None = None,
        created_by: int | None = None,
    ) -> SubjectSample:
        return await self.create(
            session,
            subject_id=subject_id,
            image_id=image_id,
            embedding_model=embedding_model,
            embedding=embedding,
            sample_meta=metadata,
            created_by=created_by,
        )


class ImageSubjectRepository(BaseRepository[ImageSubject]):
    """图片主体结果仓库。"""

    model = ImageSubject

    async def get_primary(
        self,
        session: AsyncSession,
        image_id: int,
    ) -> Optional[ImageSubject]:
        stmt = (
            select(ImageSubject)
            .options(selectinload(ImageSubject.subject))
            .where(and_(ImageSubject.image_id == image_id, ImageSubject.is_primary == True))  # noqa: E712
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_primary_subject(
        self,
        session: AsyncSession,
        *,
        image_id: int,
        subject_id: int,
        confidence: float | None,
        source: str,
        state: str = "confirmed",
        created_by: int | None = None,
    ) -> ImageSubject:
        """设置图片主主体（幂等）。"""
        await session.execute(
            update(ImageSubject)
            .where(and_(ImageSubject.image_id == image_id, ImageSubject.is_primary == True))  # noqa: E712
            .values(is_primary=False, updated_at=datetime.now(timezone.utc))
        )

        stmt = select(ImageSubject).where(
            and_(ImageSubject.image_id == image_id, ImageSubject.subject_id == subject_id)
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.is_primary = True
            existing.source = source
            existing.state = state
            existing.confidence = confidence
            existing.created_by = created_by
            existing.updated_at = datetime.now(timezone.utc)
            await session.flush()
            await session.refresh(existing)
            return existing

        created = await self.create(
            session,
            image_id=image_id,
            subject_id=subject_id,
            confidence=confidence,
            source=source,
            state=state,
            is_primary=True,
            created_by=created_by,
        )
        return created

    async def list_by_image_ids(
        self,
        session: AsyncSession,
        image_ids: list[int],
    ) -> dict[int, list[dict[str, Any]]]:
        if not image_ids:
            return {}

        stmt = (
            select(
                ImageSubject.image_id,
                ImageSubject.subject_id,
                Subject.name,
                ImageSubject.confidence,
                ImageSubject.source,
                ImageSubject.state,
                ImageSubject.is_primary,
            )
            .join(Subject, Subject.id == ImageSubject.subject_id)
            .where(ImageSubject.image_id.in_(image_ids))
            .order_by(ImageSubject.image_id, ImageSubject.is_primary.desc(), ImageSubject.id.asc())
        )
        result = await session.execute(stmt)

        out: dict[int, list[dict[str, Any]]] = {iid: [] for iid in image_ids}
        for row in result.fetchall():
            confidence = float(row.confidence) if row.confidence is not None else None
            out[int(row.image_id)].append(
                {
                    "subject_id": int(row.subject_id),
                    "subject_name": str(row.name),
                    "confidence": confidence,
                    "source": str(row.source),
                    "state": str(row.state),
                    "is_primary": bool(row.is_primary),
                }
            )
        return out


subject_repository = SubjectRepository()
subject_sample_repository = SubjectSampleRepository()
image_subject_repository = ImageSubjectRepository()
