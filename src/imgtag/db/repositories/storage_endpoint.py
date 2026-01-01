"""Repository for storage endpoint operations.

Provides CRUD and specialized queries for storage_endpoints table.
"""

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.storage_constants import EndpointRole
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

    async def get_backup_endpoints(
        self,
        session: AsyncSession,
    ) -> Sequence[StorageEndpoint]:
        """获取所有启用的备份端点。"""
        
        stmt = (
            select(self.model)
            .where(self.model.role == EndpointRole.BACKUP.value)
            .where(self.model.is_enabled == True)
            .where(self.model.is_healthy == True)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def resolve_upload_endpoint(
        self,
        session: AsyncSession,
        endpoint_id: Optional[int] = None,
    ) -> tuple[Optional[StorageEndpoint], Optional[str]]:
        """解析上传目标端点。
        
        如果 endpoint_id 为空，返回系统默认上传端点。
        如果 endpoint_id 指定，验证该端点是否可用于上传：
        - 必须存在且已启用
        - 不能是备份端点
        
        Args:
            session: 数据库会话
            endpoint_id: 可选的目标端点 ID
            
        Returns:
            tuple[endpoint, error_message]:
            - 成功: (StorageEndpoint, None)
            - 失败: (None, error_message)
        """
        
        if endpoint_id:
            endpoint = await self.get_by_id(session, endpoint_id)
            if not endpoint or not endpoint.is_enabled:
                return None, f"存储端点 {endpoint_id} 不可用"
            if endpoint.role == EndpointRole.BACKUP.value:
                return None, "不能直接上传到备份端点"
            return endpoint, None
        else:
            endpoint = await self.get_default_upload(session)
            if not endpoint:
                return None, "未配置可用的存储端点"
            return endpoint, None

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

        endpoint = await self.get_by_id(session, endpoint_id)
        if endpoint:
            endpoint.is_healthy = is_healthy
            endpoint.last_health_check = datetime.now(timezone.utc)
            endpoint.health_check_error = error if not is_healthy else None
            await session.flush()


# Singleton instance
storage_endpoint_repository = StorageEndpointRepository()
