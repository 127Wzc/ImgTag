"""Tag repository for tag-related database operations.

Provides tag-specific queries including hierarchical tag support.
"""

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import and_, delete as sa_delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.db.repositories.base import BaseRepository
from imgtag.models.tag import ImageTag, Tag


class TagRepository(BaseRepository[Tag]):
    """Repository for Tag model with specialized queries.

    Includes methods for:
    - Hierarchical tag queries
    - Tag with usage count
    - Batch tag operations
    """

    model = Tag

    async def get_by_name(
        self,
        session: AsyncSession,
        name: str,
    ) -> Optional[Tag]:
        """Find tag by name.

        Args:
            session: Database session.
            name: Tag name (case-sensitive).

        Returns:
            Tag instance or None.
        """
        return await self.get_by_field(session, "name", name)

    async def get_or_create(
        self,
        session: AsyncSession,
        name: str,
        *,
        source: str = "system",
        level: int = 2,
    ) -> Tag:
        """Get existing tag or create new one.

        Args:
            session: Database session.
            name: Tag name.
            source: Tag source (system/ai/user).
            level: Tag level (0=category, 1=resolution, 2=normal).

        Returns:
            Existing or newly created Tag.
        """
        existing = await self.get_by_name(session, name)
        if existing:
            return existing

        return await self.create(
            session,
            name=name,
            source=source,
            level=level,
        )

    async def get_or_create_with_flag(
        self,
        session: AsyncSession,
        name: str,
        *,
        source: str = "user",
        level: int = 2,
    ) -> tuple[Tag, bool]:
        """Get existing tag or create new one, with creation flag.

        Args:
            session: Database session.
            name: Tag name.
            source: Tag source (system/ai/user).
            level: Tag level (0=category, 1=resolution, 2=normal).

        Returns:
            Tuple of (Tag, is_new).
        """
        existing = await self.get_by_name(session, name)
        if existing:
            return existing, False

        new_tag = await self.create(
            session,
            name=name,
            source=source,
            level=level,
        )
        return new_tag, True

    async def get_missing_names(
        self,
        session: AsyncSession,
        names: Sequence[str],
        *,
        level: int | None = None,
    ) -> list[str]:
        """Return tag names that do not exist yet.

        Args:
            session: Database session.
            names: Tag names to check.
            level: 历史参数（兼容）。由于 Tag.name 全局唯一，level 不能用于“同名不同层级”的存在性判断；
                因此即使提供该参数，也不会把“存在但 level 不匹配”的名称当作 missing。

        Returns:
            List of missing tag names (unique, sorted).
        """
        normalized = sorted({n.strip() for n in names if n and n.strip()})
        if not normalized:
            return []

        # 由于 Tag.name 全局唯一，存在性应按 name 判断即可。
        # level 参数仅用于兼容旧调用方，不参与过滤；否则会把“存在但 level 不匹配”的名称误判为 missing，
        # 从而触发 IntegrityError / 权限误判。
        stmt = select(Tag.name, Tag.level).where(Tag.name.in_(normalized))
        result = await session.execute(stmt)
        existing_levels = {row.name: row.level for row in result}

        # 兼容：保留该参数，方便上层做额外校验（但这里不改变 missing 的定义）
        _ = level

        return [name for name in normalized if name not in existing_levels]

    async def get_name_levels(
        self,
        session: AsyncSession,
        names: Sequence[str],
    ) -> dict[str, int]:
        """按标签名查询已存在标签的 level。

        Args:
            session: 数据库会话。
            names: 标签名列表。

        Returns:
            已存在标签的 {tag_name: level} 映射。
        """
        normalized = sorted({n.strip() for n in names if n and n.strip()})
        if not normalized:
            return {}

        stmt = select(Tag.name, Tag.level).where(Tag.name.in_(normalized))
        result = await session.execute(stmt)
        return {row.name: row.level for row in result}


    async def get_all_with_count(
        self,
        session: AsyncSession,
    ) -> Sequence[tuple[Tag, int]]:
        """Get all tags with image count.

        Returns:
            List of (Tag, image_count) tuples.
        """
        stmt = (
            select(Tag, func.count(ImageTag.image_id).label("image_count"))
            .outerjoin(ImageTag, Tag.id == ImageTag.tag_id)
            .group_by(Tag.id)
            .order_by(Tag.level, Tag.sort_order, func.count(ImageTag.image_id).desc())
        )
        result = await session.execute(stmt)
        return [(row.Tag, row.image_count) for row in result]

    async def get_by_level(
        self,
        session: AsyncSession,
        level: int,
    ) -> Sequence[Tag]:
        """Get tags by level.

        Args:
            session: Database session.
            level: Tag level to filter.

        Returns:
            List of matching tags.
        """
        stmt = (
            select(Tag)
            .where(Tag.level == level)
            .order_by(Tag.sort_order, Tag.name)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_children(
        self,
        session: AsyncSession,
        parent_id: int,
    ) -> Sequence[Tag]:
        """Get child tags of a parent.

        Args:
            session: Database session.
            parent_id: Parent tag ID.

        Returns:
            List of child tags.
        """
        stmt = (
            select(Tag)
            .where(Tag.parent_id == parent_id)
            .order_by(Tag.sort_order, Tag.name)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def exists(
        self,
        session: AsyncSession,
        name: str,
    ) -> bool:
        """Check if tag name exists.

        Args:
            session: Database session.
            name: Tag name.

        Returns:
            True if exists.
        """
        stmt = select(func.count()).select_from(Tag).where(Tag.name == name)
        result = await session.execute(stmt)
        return (result.scalar() or 0) > 0

    async def rename(
        self,
        session: AsyncSession,
        old_name: str,
        new_name: str,
    ) -> bool:
        """Rename a tag.

        Args:
            session: Database session.
            old_name: Current tag name.
            new_name: New tag name.

        Returns:
            True if renamed successfully, False if not found.
        """
        tag = await self.get_by_name(session, old_name)
        if not tag:
            return False

        tag.name = new_name
        await session.flush()
        return True

    async def get_categories(
        self,
        session: AsyncSession,
    ) -> Sequence[dict[str, Any]]:
        """Get main categories (level=0) with image count.

        Args:
            session: Database session.

        Returns:
            List of category dicts.
        """
        from typing import Any

        stmt = (
            select(
                Tag.id,
                Tag.name,
                Tag.description,
                Tag.sort_order,
                func.count(ImageTag.image_id).label("image_count"),
            )
            .outerjoin(ImageTag, Tag.id == ImageTag.tag_id)
            .where(Tag.level == 0)
            .group_by(Tag.id)
            .order_by(Tag.sort_order, Tag.name)
        )
        result = await session.execute(stmt)
        return [
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "sort_order": row.sort_order,
                "image_count": row.image_count,
            }
            for row in result
        ]

    async def get_resolutions(
        self,
        session: AsyncSession,
    ) -> Sequence[dict[str, Any]]:
        """Get resolution tags (level=1) with image count.

        Args:
            session: Database session.

        Returns:
            List of resolution dicts.
        """
        stmt = (
            select(
                Tag.id,
                Tag.name,
                Tag.description,
                Tag.sort_order,
                func.count(ImageTag.image_id).label("image_count"),
            )
            .outerjoin(ImageTag, Tag.id == ImageTag.tag_id)
            .where(Tag.level == 1)
            .group_by(Tag.id)
            .order_by(Tag.sort_order, Tag.name)
        )
        result = await session.execute(stmt)
        return [
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "sort_order": row.sort_order,
                "image_count": row.image_count,
            }
            for row in result
        ]

    async def get_stats(
        self,
        session: AsyncSession,
    ) -> dict[str, Any]:
        """Get tag count statistics by level.

        Args:
            session: Database session.

        Returns:
            Dict with count for each level and total.
        """
        stmt = (
            select(Tag.level, func.count(Tag.id).label("count"))
            .group_by(Tag.level)
        )
        result = await session.execute(stmt)
        
        counts = {row.level: row.count for row in result}
        
        return {
            "categories": counts.get(0, 0),
            "resolutions": counts.get(1, 0),
            "normal_tags": counts.get(2, 0),
            "total": sum(counts.values()),
        }


    async def get_all_sorted(
        self,
        session: AsyncSession,
        *,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "usage_count",
        level: int | None = None,
        keyword: str | None = None,
    ) -> Sequence[dict[str, Any]]:
        """Get all tags sorted by usage or name.

        Args:
            session: Database session.
            limit: Maximum tags to return.
            offset: Number of tags to skip.
            sort_by: Sort field (usage_count, name).
            level: Tag level filter (None for all, 0=category, 1=resolution, 2=normal).
            keyword: Keyword to filter tag names (fuzzy search).

        Returns:
            List of tag dicts with usage count.
        """
        # 直接查询 tags 表，不再 JOIN 计算 usage_count
        stmt = select(
            Tag.id,
            Tag.name,
            Tag.level,
            Tag.source,
            Tag.description,
            Tag.sort_order,
            Tag.created_at,
            Tag.code,
            Tag.prompt,
            Tag.usage_count,
        )
        
        # 添加 level 过滤
        if level is not None:
            stmt = stmt.where(Tag.level == level)
        
        # 添加关键字模糊搜索
        if keyword:
            stmt = stmt.where(Tag.name.ilike(f"%{keyword}%"))

        if sort_by == "name":
            stmt = stmt.order_by(Tag.level, Tag.name)
        else:
            stmt = stmt.order_by(Tag.level, Tag.usage_count.desc())

        stmt = stmt.offset(offset).limit(limit)

        result = await session.execute(stmt)
        return [
            {
                "id": row.id,
                "name": row.name,
                "level": row.level,
                "source": row.source,
                "description": row.description,
                "sort_order": row.sort_order,
                "usage_count": row.usage_count,
                "created_at": row.created_at,
                "code": row.code,
                "prompt": row.prompt,
            }
            for row in result
        ]

    async def create_category(
        self,
        session: AsyncSession,
        name: str,
        *,
        description: Optional[str] = None,
        sort_order: int = 0,
    ) -> Tag:
        """Create a main category (level=0).

        Args:
            session: Database session.
            name: Category name.
            description: Optional description.
            sort_order: Display order.

        Returns:
            Created Tag instance.
        """
        return await self.create(
            session,
            name=name,
            description=description,
            level=0,
            source="system",
            sort_order=sort_order,
        )

    async def delete_category(
        self,
        session: AsyncSession,
        tag_id: int,
    ) -> tuple[bool, str]:
        """Delete a category if not in use.

        Args:
            session: Database session.
            tag_id: Category tag ID.

        Returns:
            Tuple of (success, message).
        """
        tag = await self.get_by_id(session, tag_id)
        if not tag:
            return False, "分类不存在"

        if tag.level != 0:
            return False, "只能删除主分类 (level=0)"

        # Check if in use
        count_stmt = (
            select(func.count())
            .select_from(ImageTag)
            .where(ImageTag.tag_id == tag_id)
        )
        count = (await session.execute(count_stmt)).scalar() or 0
        if count > 0:
            return False, f"分类已被 {count} 张图片使用，无法删除"

        await self.delete(session, tag)
        return True, f"分类 '{tag.name}' 已删除"

    async def sync_usage_counts(
        self,
        session: AsyncSession,
    ) -> int:
        """Sync all tag usage counts by recalculating from image_tags.

        Used for manual sync when triggers might be out of sync.

        Args:
            session: Database session.

        Returns:
            Number of tags updated.
        """
        # 使用一条 UPDATE 语句批量更新所有标签的 usage_count
        await session.execute(text("""
            UPDATE tags t
            SET usage_count = (
                SELECT COUNT(*) FROM image_tags it WHERE it.tag_id = t.id
            )
        """))
        
        # 获取更新的标签数量
        count_stmt = select(func.count()).select_from(Tag)
        count = (await session.execute(count_stmt)).scalar() or 0
        
        await session.flush()
        return count


class ImageTagRepository(BaseRepository[ImageTag]):
    """Repository for ImageTag association.

    Handles image-tag relationships.
    """

    model = ImageTag

    async def add_tag_to_image(
        self,
        session: AsyncSession,
        image_id: int,
        tag_id: int,
        *,
        source: str = "ai",
        sort_order: int = 99,
        added_by: Optional[int] = None,
    ) -> ImageTag:
        """Add a tag to an image.

        Args:
            session: Database session.
            image_id: Image ID.
            tag_id: Tag ID.
            source: Tag source (ai/user/system).
            sort_order: Display order.
            added_by: User ID who added this tag.

        Returns:
            Created ImageTag association.
        """
        return await self.create(
            session,
            image_id=image_id,
            tag_id=tag_id,
            source=source,
            sort_order=sort_order,
            added_by=added_by,
        )

    async def remove_tag_from_image(
        self,
        session: AsyncSession,
        image_id: int,
        tag_id: int,
    ) -> bool:
        """Remove a tag from an image.

        Args:
            session: Database session.
            image_id: Image ID.
            tag_id: Tag ID.

        Returns:
            True if removed, False if not found.
        """
        stmt = select(ImageTag).where(
            and_(
                ImageTag.image_id == image_id,
                ImageTag.tag_id == tag_id,
            )
        )
        result = await session.execute(stmt)
        association = result.scalar_one_or_none()

        if association:
            await session.delete(association)
            await session.flush()
            return True
        return False

    async def get_image_tags(
        self,
        session: AsyncSession,
        image_id: int,
    ) -> Sequence[Tag]:
        """Get all tags for an image.

        Args:
            session: Database session.
            image_id: Image ID.

        Returns:
            List of Tag instances.
        """
        stmt = (
            select(Tag)
            .join(ImageTag, Tag.id == ImageTag.tag_id)
            .where(ImageTag.image_id == image_id)
            .order_by(ImageTag.sort_order, Tag.name)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_image_tag(
        self,
        session: AsyncSession,
        image_id: int,
        tag_id: int,
    ) -> ImageTag | None:
        """Get a specific image-tag association.

        Args:
            session: Database session.
            image_id: Image ID.
            tag_id: Tag ID.

        Returns:
            ImageTag if exists, None otherwise.
        """
        stmt = select(ImageTag).where(
            and_(
                ImageTag.image_id == image_id,
                ImageTag.tag_id == tag_id,
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


    async def set_image_tags(
        self,
        session: AsyncSession,
        image_id: int,
        tag_names: list[str],
        *,
        source: str = "ai",
        added_by: Optional[int] = None,
    ) -> list[Tag]:
        """Set tags for an image (smart update).

        Preserves existing tag sources. New tags use specified source.

        Args:
            session: Database session.
            image_id: Image ID.
            tag_names: List of tag names to set.
            source: Source for new tags (ai/user/system).
            added_by: User ID if user-added.

        Returns:
            List of Tag instances after update.
        """

        # Get current tags with source
        current_stmt = (
            select(ImageTag.tag_id, ImageTag.source)
            .where(ImageTag.image_id == image_id)
        )
        current_result = await session.execute(current_stmt)
        current_tags = {row.tag_id: row.source for row in current_result}

        # Get or create all tags
        final_tags = []
        for idx, tag_name in enumerate(tag_names):
            tag = await tag_repository.get_or_create(
                session, tag_name, source=source, level=2
            )
            final_tags.append(tag)

            if tag.id in current_tags:
                # Already exists, keep original source
                continue

            # Add new tag association
            new_assoc = ImageTag(
                image_id=image_id,
                tag_id=tag.id,
                source=source,
                added_by=added_by,
                sort_order=idx,
                added_at=datetime.now(timezone.utc),
            )
            session.add(new_assoc)

        # Remove tags not in new list (BUT preserve level=0 and level=1 tags!)
        new_tag_ids = {t.id for t in final_tags}
        tags_to_remove = set(current_tags.keys()) - new_tag_ids

        if tags_to_remove:
            from sqlalchemy import delete as sa_delete

            # 只删除 level=2 的普通标签，保留分类(level=0)和分辨率(level=1)标签
            # 先查询哪些是 level=2 的标签
            level_check_stmt = select(Tag.id).where(
                and_(
                    Tag.id.in_(tags_to_remove),
                    Tag.level == 2,  # 只删除普通标签
                )
            )
            level_result = await session.execute(level_check_stmt)
            level2_tag_ids = {row.id for row in level_result}

            if level2_tag_ids:
                # 只删除 source='ai' 的标签关联，保留用户添加的标签
                delete_stmt = sa_delete(ImageTag).where(
                    and_(
                        ImageTag.image_id == image_id,
                        ImageTag.tag_id.in_(level2_tag_ids),
                        ImageTag.source == "ai",  # 只删除 AI 标签
                    )
                )
                await session.execute(delete_stmt)

        await session.flush()
        return final_tags

    async def set_image_tags_by_ids(
        self,
        session: AsyncSession,
        image_id: int,
        tag_ids: list[int],
        *,
        source: str = "user",
        added_by: Optional[int] = None,
    ) -> int:
        """按 ID 设置图片的普通标签（level=2）。

        语义约束：
        - 仅管理 level=2 普通标签
        - 不影响主分类(level=0)与分辨率(level=1)

        实现：
        - 对比当前 level=2 关联与目标 tag_ids，做最小增删

        Args:
            session: Database session.
            image_id: Image ID.
            tag_ids: 目标普通标签 ID 列表（仅 level=2，非法/不存在/非 level=2 会被忽略）。
            source: Source for new associations (user/ai).
            added_by: User ID if user-added.

        Returns:
            Number of associations changed.
        """

        # Filter out invalid tag IDs (id=0)
        tag_ids = [tid for tid in tag_ids if tid and tid > 0]
        # 去重（保持输入顺序）
        if tag_ids:
            seen: set[int] = set()
            deduped: list[int] = []
            for tid in tag_ids:
                if tid in seen:
                    continue
                seen.add(tid)
                deduped.append(tid)
            tag_ids = deduped

        # Validate tag IDs exist AND must be level=2
        if tag_ids:
            valid_ids_stmt = select(Tag.id).where(
                and_(
                    Tag.id.in_(tag_ids),
                    Tag.level == 2,
                )
            )
            valid_result = await session.execute(valid_ids_stmt)
            valid_ids = {row.id for row in valid_result}
            tag_ids = [tid for tid in tag_ids if tid in valid_ids]

        # Get current level=2 associations only
        current_stmt = (
            select(ImageTag.tag_id)
            .join(Tag, Tag.id == ImageTag.tag_id)
            .where(
                and_(
                    ImageTag.image_id == image_id,
                    Tag.level == 2,
                )
            )
        )
        current_result = await session.execute(current_stmt)
        current_tag_ids = {row.tag_id for row in current_result}

        new_tag_id_set = set(tag_ids)
        
        # Calculate additions and deletions
        to_add = new_tag_id_set - current_tag_ids
        to_remove = current_tag_ids - new_tag_id_set
        
        changes = 0
        
        # Add new associations
        if to_add:
            now = datetime.now(timezone.utc)
            for idx, tag_id in enumerate(tag_ids):
                if tag_id in to_add:
                    new_assoc = ImageTag(
                        image_id=image_id,
                        tag_id=tag_id,
                        source=source,
                        added_by=added_by,
                        sort_order=idx,
                        added_at=now,
                    )
                    session.add(new_assoc)
                    changes += 1
        
        # Remove old level=2 associations
        if to_remove:
            delete_stmt = sa_delete(ImageTag).where(
                and_(
                    ImageTag.image_id == image_id,
                    ImageTag.tag_id.in_(to_remove),
                )
            )
            result = await session.execute(delete_stmt)
            changes += result.rowcount or 0
        
        await session.flush()
        return changes

    async def set_image_category(
        self,
        session: AsyncSession,
        image_id: int,
        category_id: int | None,
        *,
        source: str = "user",
        added_by: Optional[int] = None,
    ) -> int:
        """设置图片主分类（level=0），保证唯一性。

        行为：
        - 无论 category_id 是否为空，都会先删除该图片已有的所有 level=0 分类关联
        - 若 category_id 非空，再插入新的分类关联

        Args:
            session: 数据库会话
            image_id: 图片 ID
            category_id: 目标分类 tag_id（level=0），None 表示清空分类
            source: 关联来源
            added_by: 操作用户 ID（可为空）

        Returns:
            变更的关联数量（删除 + 新增）
        """
        changes = 0

        # 删除旧的 level=0 分类关联
        del_stmt = sa_delete(ImageTag).where(
            and_(
                ImageTag.image_id == image_id,
                ImageTag.tag_id.in_(select(Tag.id).where(Tag.level == 0)),
            )
        )
        del_result = await session.execute(del_stmt)
        changes += del_result.rowcount or 0

        # 插入新的分类关联（如果有）
        if category_id:
            now = datetime.now(timezone.utc)
            insert_stmt = pg_insert(ImageTag).values(
                {
                    "image_id": image_id,
                    "tag_id": category_id,
                    "source": source,
                    "added_by": added_by,
                    "sort_order": 0,
                    "added_at": now,
                }
            )
            insert_stmt = insert_stmt.on_conflict_do_nothing(
                index_elements=["image_id", "tag_id"]
            )
            ins_result = await session.execute(insert_stmt)
            changes += ins_result.rowcount or 0

        await session.flush()
        return changes

    async def clear_image_tags(
        self,
        session: AsyncSession,
        image_id: int,
    ) -> int:
        """Remove all tags from an image.

        Args:
            session: Database session.
            image_id: Image ID.

        Returns:
            Number of tags removed.
        """

        stmt = sa_delete(ImageTag).where(ImageTag.image_id == image_id)
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount

    # ==================== Batch Operations ====================

    async def batch_add_tags_to_images(
        self,
        session: AsyncSession,
        image_ids: list[int],
        tag_names: list[str],
        *,
        source: str = "user",
        added_by: Optional[int] = None,
        owner_id: Optional[int] = None,
    ) -> int:
        """Add tags to multiple images (append mode).

        Uses bulk INSERT for efficiency.

        Args:
            session: Database session.
            image_ids: List of image IDs.
            tag_names: Tag names to add.
            source: Tag source.
            added_by: User ID.
            owner_id: If provided, only update images uploaded by this user.

        Returns:
            Number of new associations created.
        """
        if not image_ids or not tag_names:
            return 0

        # 如果指定了 owner_id，先过滤出属于该用户的图片
        if owner_id is not None:
            from imgtag.models.image import Image
            stmt = select(Image.id).where(
                and_(Image.id.in_(image_ids), Image.uploaded_by == owner_id)
            )
            result = await session.execute(stmt)
            image_ids = [row.id for row in result]
            if not image_ids:
                return 0


        # Get or create all tags first
        tags = []
        for name in tag_names:
            tag = await tag_repository.get_or_create(session, name, source=source)
            tags.append(tag)

        tag_ids = [t.id for t in tags]

        # Get existing associations in one query
        existing_stmt = select(ImageTag.image_id, ImageTag.tag_id).where(
            and_(
                ImageTag.image_id.in_(image_ids),
                ImageTag.tag_id.in_(tag_ids),
            )
        )
        existing_result = await session.execute(existing_stmt)
        existing_pairs = {(row.image_id, row.tag_id) for row in existing_result}

        # Build insert data
        now = datetime.now(timezone.utc)
        new_records = []
        for image_id in image_ids:
            for idx, tag_id in enumerate(tag_ids):
                if (image_id, tag_id) not in existing_pairs:
                    new_records.append({
                        "image_id": image_id,
                        "tag_id": tag_id,
                        "source": source,
                        "added_by": added_by,
                        "sort_order": idx,
                        "added_at": now,
                    })

        if not new_records:
            return 0

        # Bulk insert using PostgreSQL INSERT .. ON CONFLICT DO NOTHING
        insert_stmt = pg_insert(ImageTag).values(new_records)
        insert_stmt = insert_stmt.on_conflict_do_nothing(
            index_elements=["image_id", "tag_id"]
        )
        await session.execute(insert_stmt)
        await session.flush()

        return len(new_records)

    async def batch_replace_tags_for_images(
        self,
        session: AsyncSession,
        image_ids: list[int],
        tag_names: list[str],
        *,
        source: str = "user",
        added_by: Optional[int] = None,
        owner_id: Optional[int] = None,
    ) -> int:
        """Replace all tags for multiple images.

        Deletes existing tags and inserts new ones in bulk.

        Args:
            session: Database session.
            image_ids: List of image IDs.
            tag_names: New tag names.
            source: Tag source.
            added_by: User ID.
            owner_id: If provided, only update images uploaded by this user.

        Returns:
            Number of new associations created.
        """
        if not image_ids:
            return 0

        # 如果指定了 owner_id，先过滤出属于该用户的图片
        if owner_id is not None:
            from imgtag.models.image import Image
            stmt = select(Image.id).where(
                and_(Image.id.in_(image_ids), Image.uploaded_by == owner_id)
            )
            result = await session.execute(stmt)
            image_ids = [row.id for row in result]
            if not image_ids:
                return 0


        # 仅替换普通标签(level=2)，保留主分类(level=0)与分辨率(level=1)
        await session.execute(
            sa_delete(ImageTag).where(
                and_(
                    ImageTag.image_id.in_(image_ids),
                    ImageTag.tag_id.in_(select(Tag.id).where(Tag.level == 2)),
                )
            )
        )

        if not tag_names:
            await session.flush()
            return 0

        # Get or create all tags
        tags = []
        for name in tag_names:
            tag = await tag_repository.get_or_create(session, name, source=source)
            tags.append(tag)

        # Build insert data
        now = datetime.now(timezone.utc)
        new_records = []
        for image_id in image_ids:
            for idx, tag in enumerate(tags):
                new_records.append({
                    "image_id": image_id,
                    "tag_id": tag.id,
                    "source": source,
                    "added_by": added_by,
                    "sort_order": idx,
                    "added_at": now,
                })

        # Bulk insert
        insert_stmt = pg_insert(ImageTag).values(new_records)
        insert_stmt = insert_stmt.on_conflict_do_nothing(
            index_elements=["image_id", "tag_id"]
        )
        await session.execute(insert_stmt)
        await session.flush()

        return len(new_records)


# Singleton instances
tag_repository = TagRepository()
image_tag_repository = ImageTagRepository()
