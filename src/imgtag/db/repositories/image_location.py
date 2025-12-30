"""Repository for image location operations.

Provides CRUD and specialized queries for image_locations table.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Sequence

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.db.repositories.base import BaseRepository
from imgtag.models.image_location import ImageLocation


class ImageLocationRepository(BaseRepository[ImageLocation]):
    """Repository for ImageLocation model."""

    model = ImageLocation

    async def get_by_image_and_endpoint(
        self,
        session: AsyncSession,
        image_id: int,
        endpoint_id: int,
    ) -> Optional[ImageLocation]:
        """Get location for specific image and endpoint."""
        stmt = (
            select(self.model)
            .where(self.model.image_id == image_id)
            .where(self.model.endpoint_id == endpoint_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_image(
        self,
        session: AsyncSession,
        image_id: int,
    ) -> Sequence[ImageLocation]:
        """Get all locations for an image."""
        stmt = select(self.model).where(self.model.image_id == image_id)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_endpoint(
        self,
        session: AsyncSession,
        endpoint_id: int,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[ImageLocation]:
        """Get locations for an endpoint with optional pagination.
        
        Args:
            session: Database session.
            endpoint_id: Endpoint ID to filter by.
            limit: Maximum number of records (None = all).
            offset: Number of records to skip.
            
        Returns:
            Sequence of ImageLocation.
        """
        stmt = (
            select(self.model)
            .where(self.model.endpoint_id == endpoint_id)
            .offset(offset)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def iter_by_endpoint(
        self,
        session: AsyncSession,
        endpoint_id: int,
        batch_size: int = 1000,
    ) -> "AsyncIterator[ImageLocation]":
        """Iterate through all locations for an endpoint in batches.
        
        Memory-efficient async generator for large datasets.
        
        Args:
            session: Database session.
            endpoint_id: Endpoint ID to filter by.
            batch_size: Records per batch (default 1000).
            
        Yields:
            ImageLocation objects one at a time.
        """
        offset = 0
        while True:
            locations = await self.get_by_endpoint(
                session, endpoint_id, limit=batch_size, offset=offset
            )
            if not locations:
                break
            for loc in locations:
                yield loc
            if len(locations) < batch_size:
                break
            offset += batch_size

    async def get_by_image_ids(
        self,
        session: AsyncSession,
        image_ids: list[int],
    ) -> dict[int, list[ImageLocation]]:
        """Batch get all locations for multiple images.
        
        This is the preferred method for fetching locations for multiple images
        to avoid N+1 query problems.
        
        Args:
            session: Database session.
            image_ids: List of image IDs.
            
        Returns:
            Dict mapping image_id to list of ImageLocation.
        """
        if not image_ids:
            return {}
        
        stmt = select(self.model).where(self.model.image_id.in_(image_ids))
        result = await session.execute(stmt)
        locations = result.scalars().all()
        
        # Group by image_id
        locations_map: dict[int, list[ImageLocation]] = {img_id: [] for img_id in image_ids}
        for loc in locations:
            if loc.image_id in locations_map:
                locations_map[loc.image_id].append(loc)
        
        return locations_map

    async def get_primary_location(
        self,
        session: AsyncSession,
        image_id: int,
    ) -> Optional[ImageLocation]:
        """Get primary storage location for an image."""
        stmt = (
            select(self.model)
            .where(self.model.image_id == image_id)
            .where(self.model.is_primary == True)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_sync(
        self,
        session: AsyncSession,
        endpoint_id: Optional[int] = None,
        limit: int = 100,
    ) -> Sequence[ImageLocation]:
        """Get locations pending sync, optionally filtered by endpoint."""
        stmt = (
            select(self.model)
            .where(self.model.sync_status == "pending")
            .order_by(self.model.created_at)
            .limit(limit)
        )
        if endpoint_id:
            stmt = stmt.where(self.model.endpoint_id == endpoint_id)
        result = await session.execute(stmt)
        return result.scalars().all()

    async def mark_synced(
        self,
        session: AsyncSession,
        location_id: int,
    ) -> None:
        """Mark location as successfully synced."""
        stmt = (
            update(self.model)
            .where(self.model.id == location_id)
            .values(
                sync_status="synced",
                sync_error=None,
                synced_at=datetime.now(timezone.utc),
            )
        )
        await session.execute(stmt)
        await session.flush()

    async def mark_failed(
        self,
        session: AsyncSession,
        location_id: int,
        error: str,
    ) -> None:
        """Mark location as sync failed."""
        stmt = (
            update(self.model)
            .where(self.model.id == location_id)
            .values(sync_status="failed", sync_error=error)
        )
        await session.execute(stmt)
        await session.flush()

    async def count_by_endpoint(
        self,
        session: AsyncSession,
        endpoint_id: int,
    ) -> int:
        """Count locations for an endpoint."""
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.endpoint_id == endpoint_id)
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def count_by_image(
        self,
        session: AsyncSession,
        image_id: int,
    ) -> int:
        """Count locations for an image.
        
        Used to determine if an image will become orphan after removing a location.
        """
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.image_id == image_id)
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def create_pending(
        self,
        session: AsyncSession,
        image_id: int,
        endpoint_id: int,
        object_key: str,
    ) -> ImageLocation:
        """Create a pending sync location."""
        return await self.create(
            session,
            image_id=image_id,
            endpoint_id=endpoint_id,
            object_key=object_key,
            sync_status="pending",
            is_primary=False,
        )

    async def delete_by_endpoint(
        self,
        session: AsyncSession,
        endpoint_id: int,
    ) -> int:
        """Delete all locations for an endpoint.
        
        Used for soft delete (removing associations without deleting files).
        
        Args:
            session: Database session.
            endpoint_id: Endpoint ID to delete locations for.
            
        Returns:
            Number of deleted records.
        """
        from sqlalchemy import delete, func
        
        # First count for return value
        count = await self.count_by_endpoint(session, endpoint_id)
        
        # Delete all
        stmt = delete(self.model).where(self.model.endpoint_id == endpoint_id)
        await session.execute(stmt)
        await session.flush()
        
        return count


# Singleton instance
image_location_repository = ImageLocationRepository()
