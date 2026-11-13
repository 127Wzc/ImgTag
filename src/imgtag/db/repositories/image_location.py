"""Repository for image location operations.

Provides CRUD and specialized queries for image_locations table.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Sequence

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from imgtag.core.storage_constants import BATCH_CONFIG
from imgtag.core.storage_runtime import StorageOperationStopped
from imgtag.db.repositories.base import BaseRepository
from imgtag.db.repositories.storage_endpoint import storage_endpoint_repository
from imgtag.models.image import Image
from imgtag.models.image_location import ImageLocation
from imgtag.models.storage_endpoint import StorageEndpoint


class ImageLocationRepository(BaseRepository[ImageLocation]):
    """Repository for ImageLocation model."""

    model = ImageLocation

    async def get_files_for_images(self, session, image_ids: list[int], owner_id: int | None = None):
        """仅返回允许删除的图片所涉及的文件，不加载图片向量和其他元数据。"""
        stmt = select(self.model.endpoint_id, self.model.object_key).join(Image).where(Image.id.in_(image_ids))
        if owner_id is not None:
            stmt = stmt.where(Image.uploaded_by == owner_id)
        return (await session.execute(stmt)).all()

    async def get_missing_backup_batch(self, session, endpoint_id: int, after_image_id: int, limit: int):
        backed_up = select(self.model.image_id).where(
            self.model.endpoint_id == endpoint_id, self.model.sync_status == "synced"
        )
        result = await session.execute(select(self.model.image_id, self.model.endpoint_id)
            .join(StorageEndpoint, StorageEndpoint.id == self.model.endpoint_id)
            .where(self.model.image_id > after_image_id, self.model.image_id.not_in(backed_up),
                   self.model.is_primary.is_(True), self.model.sync_status == "synced",
                   StorageEndpoint.is_enabled.is_(True), StorageEndpoint.role == "primary")
            .order_by(self.model.image_id).limit(limit))
        return result.all()

    async def create(self, session, *, expected_generation: int | None = None, **values):
        endpoint_id = values["endpoint_id"]
        if expected_generation is None:
            endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
            if endpoint is None or not endpoint.is_enabled:
                raise StorageOperationStopped("端点不可用，禁止新增关联")
            expected_generation = endpoint.operation_generation or 0
        await storage_endpoint_repository.guard_write(session, {endpoint_id: expected_generation})
        if await storage_endpoint_repository.has_cleanup_task(session, endpoint_id):
            raise StorageOperationStopped("端点正在清理，禁止新增位置关联")
        return await super().create(session, **values)

    async def remove_locations(
        self, session, endpoint_id: int, location_ids: list[int] | None = None,
        *, delete_empty_images: bool = False,
    ) -> int:
        """移除位置并补选主位置；删除文件时同时删除已无任何位置的图片。"""
        condition = self.model.endpoint_id == endpoint_id
        if location_ids is not None:
            condition = condition & self.model.id.in_(location_ids)
        result = await session.execute(delete(self.model).where(condition).returning(self.model.image_id))
        image_ids = list(result.scalars().all())
        for offset in range(0, len(image_ids), BATCH_CONFIG.batch_size):
            affected_ids = image_ids[offset:offset + BATCH_CONFIG.batch_size]
            if delete_empty_images:
                # 与位置移除同一事务，仅处理本次受影响的图片；关联数据由外键级联清理。
                await session.execute(delete(Image).where(
                    Image.id.in_(affected_ids),
                    ~select(self.model.id).where(self.model.image_id == Image.id).exists(),
                ).execution_options(synchronize_session=False))
            primary = select(self.model.image_id).where(self.model.is_primary.is_(True)).subquery()
            candidates = select(func.min(self.model.id).label("id")).where(
                self.model.image_id.in_(affected_ids), self.model.sync_status == "synced",
                self.model.image_id.not_in(select(primary.c.image_id)),
            ).group_by(self.model.image_id).subquery()
            await session.execute(update(self.model).where(self.model.id.in_(select(candidates.c.id)))
                                  .values(is_primary=True).execution_options(synchronize_session=False))
        return len(image_ids)

    async def get_readable_by_image_ids(
        self, session: AsyncSession, image_ids: list[int],
    ) -> Sequence[tuple[ImageLocation, StorageEndpoint]]:
        """一次取得当前图片的可读位置和构建地址需要的端点字段。"""
        if not image_ids:
            return []
        result = await session.execute(
            select(ImageLocation, StorageEndpoint)
            .join(StorageEndpoint, StorageEndpoint.id == ImageLocation.endpoint_id)
            .where(ImageLocation.image_id.in_(image_ids),
                   StorageEndpoint.is_enabled.is_(True), StorageEndpoint.is_healthy.is_(True))
            .options(
                load_only(ImageLocation.id, ImageLocation.image_id, ImageLocation.endpoint_id,
                          ImageLocation.object_key, raiseload=True),
                load_only(StorageEndpoint.id, StorageEndpoint.provider, StorageEndpoint.endpoint_url,
                          StorageEndpoint.bucket_name, StorageEndpoint.path_prefix, StorageEndpoint.public_url_prefix,
                          StorageEndpoint.path_style,
                          StorageEndpoint.public_url_include_bucket,
                          StorageEndpoint.is_enabled, StorageEndpoint.read_priority, StorageEndpoint.read_weight,
                          raiseload=True),
            )
        )
        return result.all()

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

    async def count_by_object_key(
        self,
        session: AsyncSession,
        endpoint_id: int,
        object_key: str,
    ) -> int:
        """Count locations with same object_key on an endpoint.
        
        Used to check if file is referenced by multiple locations before deletion.
        If count > 1, the physical file should NOT be deleted because other
        locations still reference it.
        
        Args:
            session: Database session.
            endpoint_id: Endpoint ID to filter by.
            object_key: Object key to count references for.
            
        Returns:
            Number of locations referencing this object_key on this endpoint.
        """
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.endpoint_id == endpoint_id)
            .where(self.model.object_key == object_key)
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

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
