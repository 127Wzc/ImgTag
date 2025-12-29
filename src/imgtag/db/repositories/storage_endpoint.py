"""Repository for storage endpoint operations.

Provides CRUD and specialized queries for storage_endpoints table.
"""

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.db.repositories.base import BaseRepository
from imgtag.models.storage_endpoint import StorageEndpoint


class StorageEndpointRepository(BaseRepository[StorageEndpoint]):
    """Repository for StorageEndpoint model."""

    model = StorageEndpoint

    async def get_by_name(
        self,
        session: AsyncSession,
        name: str,
    ) -> Optional[StorageEndpoint]:
        """Get endpoint by unique name."""
        return await self.get_by_field(session, "name", name)

    async def get_enabled(
        self,
        session: AsyncSession,
    ) -> Sequence[StorageEndpoint]:
        """Get all enabled endpoints ordered by read priority."""
        stmt = (
            select(self.model)
            .where(self.model.is_enabled == True)
            .order_by(self.model.read_priority)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_default_upload(
        self,
        session: AsyncSession,
    ) -> Optional[StorageEndpoint]:
        """Get the default upload endpoint."""
        stmt = (
            select(self.model)
            .where(self.model.is_default_upload == True)
            .where(self.model.is_enabled == True)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_healthy_for_read(
        self,
        session: AsyncSession,
    ) -> Sequence[StorageEndpoint]:
        """Get healthy endpoints ordered by read priority."""
        stmt = (
            select(self.model)
            .where(self.model.is_enabled == True)
            .where(self.model.is_healthy == True)
            .order_by(self.model.read_priority)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_auto_sync_targets(
        self,
        session: AsyncSession,
        source_endpoint_id: int,
    ) -> Sequence[StorageEndpoint]:
        """Get endpoints that auto-sync from the given source."""
        stmt = (
            select(self.model)
            .where(self.model.auto_sync_enabled == True)
            .where(self.model.sync_from_endpoint_id == source_endpoint_id)
            .where(self.model.is_enabled == True)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def set_default_upload(
        self,
        session: AsyncSession,
        endpoint_id: int,
    ) -> None:
        """Set endpoint as default upload, clearing others."""
        # Clear existing default
        stmt = select(self.model).where(self.model.is_default_upload == True)
        result = await session.execute(stmt)
        for ep in result.scalars():
            ep.is_default_upload = False

        # Set new default
        endpoint = await self.get_by_id(session, endpoint_id)
        if endpoint:
            endpoint.is_default_upload = True
        await session.flush()

    async def update_health(
        self,
        session: AsyncSession,
        endpoint_id: int,
        is_healthy: bool,
        error: Optional[str] = None,
    ) -> None:
        """Update endpoint health status."""
        from datetime import datetime, timezone

        endpoint = await self.get_by_id(session, endpoint_id)
        if endpoint:
            endpoint.is_healthy = is_healthy
            endpoint.last_health_check = datetime.now(timezone.utc)
            endpoint.health_check_error = error if not is_healthy else None
            await session.flush()


# Singleton instance
storage_endpoint_repository = StorageEndpointRepository()
