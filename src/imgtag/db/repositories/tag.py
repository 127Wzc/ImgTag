"""Tag repository for tag-related database operations.

Provides tag-specific queries including hierarchical tag support.
"""

from typing import Any, Optional, Sequence

from sqlalchemy import and_, func, select
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

    async def get_all_sorted(
        self,
        session: AsyncSession,
        *,
        limit: int = 100,
        sort_by: str = "usage_count",
    ) -> Sequence[dict[str, Any]]:
        """Get all tags sorted by usage or name.

        Args:
            session: Database session.
            limit: Maximum tags to return.
            sort_by: Sort field (usage_count, name).

        Returns:
            List of tag dicts with usage count.
        """
        stmt = (
            select(
                Tag.id,
                Tag.name,
                Tag.level,
                Tag.source,
                Tag.description,
                Tag.sort_order,
                Tag.created_at,
                func.count(ImageTag.image_id).label("usage_count"),
            )
            .outerjoin(ImageTag, Tag.id == ImageTag.tag_id)
            .group_by(Tag.id)
            .limit(limit)
        )

        if sort_by == "name":
            stmt = stmt.order_by(Tag.name)
        else:
            stmt = stmt.order_by(func.count(ImageTag.image_id).desc())

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
    ) -> ImageTag:
        """Add a tag to an image.

        Args:
            session: Database session.
            image_id: Image ID.
            tag_id: Tag ID.
            source: Tag source (ai/user/system).
            sort_order: Display order.

        Returns:
            Created ImageTag association.
        """
        return await self.create(
            session,
            image_id=image_id,
            tag_id=tag_id,
            source=source,
            sort_order=sort_order,
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
        from datetime import datetime, timezone

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

        # Remove tags not in new list
        new_tag_ids = {t.id for t in final_tags}
        tags_to_remove = set(current_tags.keys()) - new_tag_ids

        if tags_to_remove:
            from sqlalchemy import delete as sa_delete

            delete_stmt = sa_delete(ImageTag).where(
                and_(
                    ImageTag.image_id == image_id,
                    ImageTag.tag_id.in_(tags_to_remove),
                )
            )
            await session.execute(delete_stmt)

        await session.flush()
        return final_tags

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
        from sqlalchemy import delete as sa_delete

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
    ) -> int:
        """Add tags to multiple images (append mode).

        Uses bulk INSERT for efficiency.

        Args:
            session: Database session.
            image_ids: List of image IDs.
            tag_names: Tag names to add.
            source: Tag source.
            added_by: User ID.

        Returns:
            Number of new associations created.
        """
        if not image_ids or not tag_names:
            return 0

        from datetime import datetime, timezone
        from sqlalchemy.dialects.postgresql import insert as pg_insert

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
    ) -> int:
        """Replace all tags for multiple images.

        Deletes existing tags and inserts new ones in bulk.

        Args:
            session: Database session.
            image_ids: List of image IDs.
            tag_names: New tag names.
            source: Tag source.
            added_by: User ID.

        Returns:
            Number of new associations created.
        """
        if not image_ids:
            return 0

        from datetime import datetime, timezone
        from sqlalchemy import delete as sa_delete
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        # Delete existing tags for these images
        await session.execute(
            sa_delete(ImageTag).where(ImageTag.image_id.in_(image_ids))
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
