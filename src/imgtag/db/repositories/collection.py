"""Collection repository for collection-related database operations.

Provides collection CRUD and image association operations.
"""

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.db.repositories.base import BaseRepository
from imgtag.models.collection import Collection, ImageCollection
from imgtag.models.image import Image
from imgtag.models.tag import Tag


class CollectionRepository(BaseRepository[Collection]):
    """Repository for Collection model.

    Includes methods for:
    - Collection CRUD
    - Image associations
    - Random image selection
    """

    model = Collection

    async def create_collection(
        self,
        session: AsyncSession,
        name: str,
        *,
        description: Optional[str] = None,
        parent_id: Optional[int] = None,
        created_by: Optional[int] = None,
    ) -> Collection:
        """Create a new collection.

        Args:
            session: Database session.
            name: Collection name.
            description: Optional description.
            parent_id: Parent collection ID for nesting.
            created_by: User ID who created.

        Returns:
            Created Collection instance.
        """
        return await self.create(
            session,
            name=name,
            description=description,
            parent_id=parent_id,
            created_by=created_by,
        )

    async def get_all_with_counts(
        self,
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Get all collections with image counts.

        Args:
            session: Database session.

        Returns:
            List of collection dicts with image_count.
        """
        stmt = (
            select(
                Collection.id,
                Collection.name,
                Collection.description,
                Collection.parent_id,
                Collection.cover_image_id,
                Collection.sort_order,
                Collection.is_public,
                Collection.created_at,
                Collection.updated_at,
                func.count(ImageCollection.image_id).label("image_count"),
            )
            .outerjoin(ImageCollection, Collection.id == ImageCollection.collection_id)
            .group_by(Collection.id)
            .order_by(Collection.sort_order, Collection.name)
        )
        result = await session.execute(stmt)
        return [
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "parent_id": row.parent_id,
                "cover_image_id": row.cover_image_id,
                "sort_order": row.sort_order,
                "is_public": row.is_public,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "image_count": row.image_count,
            }
            for row in result
        ]

    async def update_collection(
        self,
        session: AsyncSession,
        collection: Collection,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        cover_image_id: Optional[int] = None,
    ) -> Collection:
        """Update collection fields.

        Args:
            session: Database session.
            collection: Collection to update.
            name: New name.
            description: New description.
            cover_image_id: New cover image ID.

        Returns:
            Updated Collection instance.
        """
        update_data = {"updated_at": datetime.now(timezone.utc)}
        if name is not None:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
        if cover_image_id is not None:
            update_data["cover_image_id"] = cover_image_id

        return await self.update(session, collection, **update_data)


class ImageCollectionRepository(BaseRepository[ImageCollection]):
    """Repository for ImageCollection association.

    Handles collection-image relationships.
    """

    model = ImageCollection

    async def add_image(
        self,
        session: AsyncSession,
        collection_id: int,
        image_id: int,
    ) -> ImageCollection:
        """Add image to collection.

        Args:
            session: Database session.
            collection_id: Collection ID.
            image_id: Image ID.

        Returns:
            Created ImageCollection association.
        """
        # Check if already exists
        existing = await self.get_by_fields(
            session,
            collection_id=collection_id,
            image_id=image_id,
        )
        if existing:
            return existing[0]

        return await self.create(
            session,
            collection_id=collection_id,
            image_id=image_id,
        )

    async def remove_image(
        self,
        session: AsyncSession,
        collection_id: int,
        image_id: int,
    ) -> bool:
        """Remove image from collection.

        Args:
            session: Database session.
            collection_id: Collection ID.
            image_id: Image ID.

        Returns:
            True if removed, False if not found.
        """
        from sqlalchemy import and_, delete as sa_delete

        stmt = sa_delete(ImageCollection).where(
            and_(
                ImageCollection.collection_id == collection_id,
                ImageCollection.image_id == image_id,
            )
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0

    async def get_by_fields(
        self,
        session: AsyncSession,
        **kwargs,
    ) -> Sequence[ImageCollection]:
        """Get associations by field values.

        Args:
            session: Database session.
            **kwargs: Field values to match.

        Returns:
            List of matching associations.
        """
        stmt = select(ImageCollection)
        for key, value in kwargs.items():
            stmt = stmt.where(getattr(ImageCollection, key) == value)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_collection_images(
        self,
        session: AsyncSession,
        collection_id: int,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Get images in a collection with pagination.

        Args:
            session: Database session.
            collection_id: Collection ID.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            Dict with images, total, limit, offset.
        """
        # Count total
        count_stmt = (
            select(func.count())
            .select_from(ImageCollection)
            .where(ImageCollection.collection_id == collection_id)
        )
        total = (await session.execute(count_stmt)).scalar() or 0

        # Get images
        stmt = (
            select(Image)
            .join(ImageCollection, Image.id == ImageCollection.image_id)
            .where(ImageCollection.collection_id == collection_id)
            .order_by(ImageCollection.added_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        images = result.scalars().all()

        return {
            "images": [
                {
                    "id": img.id,
                    "image_url": img.image_url,
                    "description": img.description,
                    "file_type": img.file_type,
                    "width": img.width,
                    "height": img.height,
                    "created_at": img.created_at,
                }
                for img in images
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def get_random_image(
        self,
        session: AsyncSession,
        collection_id: int,
        *,
        tags: Optional[list[str]] = None,
        include_children: bool = False,
    ) -> Optional[dict[str, Any]]:
        """Get random image from collection.

        Args:
            session: Database session.
            collection_id: Collection ID.
            tags: Optional tag filter.
            include_children: Include child collection images.

        Returns:
            Random image dict or None.
        """
        # Build collection IDs list
        collection_ids = [collection_id]

        if include_children:
            # Get child collections
            children_stmt = select(Collection.id).where(
                Collection.parent_id == collection_id
            )
            children_result = await session.execute(children_stmt)
            collection_ids.extend([row[0] for row in children_result])

        # Build query
        stmt = (
            select(Image)
            .join(ImageCollection, Image.id == ImageCollection.image_id)
            .where(ImageCollection.collection_id.in_(collection_ids))
        )

        # Add tag filter if provided
        if tags:
            from imgtag.models.tag import ImageTag

            tag_subquery = (
                select(ImageTag.image_id)
                .join(Tag, ImageTag.tag_id == Tag.id)
                .where(Tag.name.in_(tags))
                .group_by(ImageTag.image_id)
                .having(func.count(func.distinct(Tag.id)) == len(tags))
            )
            stmt = stmt.where(Image.id.in_(tag_subquery))

        # Random order
        stmt = stmt.order_by(func.random()).limit(1)

        result = await session.execute(stmt)
        image = result.scalar_one_or_none()

        if not image:
            return None

        return {
            "id": image.id,
            "image_url": image.image_url,
            "description": image.description,
            "file_type": image.file_type,
            "width": image.width,
            "height": image.height,
        }


# Singleton instances
collection_repository = CollectionRepository()
image_collection_repository = ImageCollectionRepository()
