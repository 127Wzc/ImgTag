"""Subject repositories."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from imgtag.db.repositories.base import BaseRepository
from imgtag.models.subject import ImageSubject, Subject, SubjectSample
from imgtag.models.tag import ImageTag, Tag
from imgtag.models.image import Image


class SubjectRepository(BaseRepository[Subject]):
    """主体词典仓库。"""

    model = Subject

    async def lock_by_ids(self, session: AsyncSession, subject_ids: list[int]) -> None:
        """写回分析结果期间稳定主体定义，网络调用期间不持锁。"""
        if subject_ids:
            await session.execute(
                select(Subject.id).where(Subject.id.in_(subject_ids))
                .order_by(Subject.id).with_for_update(read=True)
            )

    async def list_matching_tags(self, session: AsyncSession, tag_ids: list[int]) -> Sequence[Subject]:
        """只按主名称/别名标签 ID 匹配，分类标签不表示主体身份。"""
        if not tag_ids:
            return []
        result = await session.execute(
            select(Subject).where(
                Subject.is_active.is_(True),
                or_(Subject.primary_tag_id.in_(tag_ids), Subject.alias_tag_ids.overlap(tag_ids)),
            ).order_by(Subject.id).execution_options(populate_existing=True)
        )
        return result.scalars().all()

    async def count_current_images(self, session: AsyncSession, subject_ids: list[int]) -> dict[int, int]:
        """批量统计当前关联图片，排除历史关联，不按标签或提炼样本计数。"""
        if not subject_ids:
            return {}
        rows = (await session.execute(select(ImageSubject.subject_id, func.count(ImageSubject.image_id))
            .where(ImageSubject.subject_id.in_(subject_ids), ImageSubject.is_current.is_(True))
            .group_by(ImageSubject.subject_id))).all()
        return {subject_id: count for subject_id, count in rows}

    async def list_image_ids(self, session: AsyncSession, subject_id: int) -> list[int]:
        result = await session.execute(
            select(ImageSubject.image_id).where(
                ImageSubject.subject_id == subject_id, ImageSubject.is_current.is_(True),
            ).order_by(ImageSubject.image_id)
        )
        return list(result.scalars().all())

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
                selectinload(Subject.cover_image),
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
                selectinload(Subject.cover_image),
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

    async def tagged_images(self, session: AsyncSession, tag_id: int, *, page: int = 1,
                            size: int = 24, keyword: str = "") -> tuple[list[Image], int]:
        conditions = [ImageTag.tag_id == tag_id]
        if keyword.strip():
            term = keyword.strip()
            match = Image.description.ilike(f"%{term}%")
            if term.removeprefix("#").isdigit():
                match = or_(match, Image.id == int(term.removeprefix("#")))
            conditions.append(match)
        base = select(Image).join(ImageTag, ImageTag.image_id == Image.id).where(*conditions)
        total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        rows = (await session.execute(base.order_by(Image.id.desc()).offset((page - 1) * size).limit(size))).scalars().all()
        return list(rows), total

    async def eligible_reference_ids(self, session: AsyncSession, tag_id: int, image_ids: list[int]) -> set[int]:
        rows = await session.execute(select(ImageTag.image_id).where(
            ImageTag.tag_id == tag_id, ImageTag.image_id.in_(image_ids)))
        return set(rows.scalars().all())

    async def associate_tagged_images(self, session: AsyncSession, subject: Subject, actor_id: int | None) -> int:
        """追加标签关联，保留原有主体和主主体，不登记提炼样本。先锁图片以串行化关联写入。"""
        ids = list((await session.execute(select(Image.id).join(ImageTag, ImageTag.image_id == Image.id)
            .where(ImageTag.tag_id == subject.primary_tag_id).order_by(Image.id).with_for_update(of=Image))).scalars().all())
        if not ids:
            return 0
        # 分批追加，避免大图库超过驱动参数上限；图片锁持有到事务提交。
        for start in range(0, len(ids), 500):
            batch = ids[start:start + 500]
            primaries = set((await session.execute(select(ImageSubject.image_id).where(
                ImageSubject.image_id.in_(batch), ImageSubject.is_primary.is_(True)))).scalars().all())
            await session.execute(insert(ImageSubject).values([{
                "image_id": image_id, "subject_id": subject.id, "source": "tag", "state": "confirmed",
                "is_primary": image_id not in primaries, "is_current": True, "created_by": actor_id,
                "synced_primary_tag_id": None,
            } for image_id in batch]).on_conflict_do_nothing(index_elements=["image_id", "subject_id"]))
            await session.execute(update(Image).where(Image.id.in_(batch)).values(subject_analysis=None))
        return len(ids)

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

    async def has_explicit_selection(self, session: AsyncSession, image_id: int) -> bool:
        result = await session.execute(select(Image.subject_selection_explicit).where(Image.id == image_id))
        return bool(result.scalar_one_or_none())

    async def get_current(self, session: AsyncSession, image_id: int) -> Sequence[ImageSubject]:
        result = await session.execute(
            select(ImageSubject).options(selectinload(ImageSubject.subject))
            .where(ImageSubject.image_id == image_id, ImageSubject.is_current.is_(True))
            .order_by(ImageSubject.is_primary.desc(), ImageSubject.subject_id).execution_options(populate_existing=True)
        )
        return result.scalars().all()

    async def replace_current(self, session: AsyncSession, image_id: int, subject_ids: list[int],
                              primary_id: int | None, actor_id: int | None) -> Sequence[ImageSubject]:
        # 调用方持有图片锁；先撤销主标记再设置，满足部分唯一索引。
        await session.execute(update(ImageSubject).where(ImageSubject.image_id == image_id)
                              .values(is_primary=False, is_current=False))
        result = await session.execute(select(ImageSubject).where(ImageSubject.image_id == image_id))
        existing = {row.subject_id: row for row in result.scalars().all()}
        for subject_id in subject_ids:
            row = existing.get(subject_id)
            if row is None:
                row = ImageSubject(image_id=image_id, subject_id=subject_id, created_by=actor_id)
                session.add(row)
            row.is_current = True
            row.is_primary = subject_id == primary_id
            row.source = "manual"
            row.state = "confirmed"
            row.confidence = None
            row.updated_at = datetime.now(timezone.utc)
        await session.flush()
        return await self.get_current(session, image_id)

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
            .values(is_primary=False, is_current=False, updated_at=datetime.now(timezone.utc))
        )

        stmt = select(ImageSubject).where(
            and_(ImageSubject.image_id == image_id, ImageSubject.subject_id == subject_id)
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.is_primary = True
            existing.is_current = True
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
            is_current=True,
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
            .where(ImageSubject.image_id.in_(image_ids), ImageSubject.is_current.is_(True))
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
