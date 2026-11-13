"""Repository for storage endpoint operations.

Provides CRUD and specialized queries for storage_endpoints table.
"""

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.storage_constants import EndpointRole, StorageTaskType
from imgtag.core.storage_runtime import StorageOperationStopped, storage_attempt
from imgtag.db.repositories.base import BaseRepository
from imgtag.models.storage_endpoint import StorageEndpoint
from imgtag.models.task import Task


class StorageEndpointRepository(BaseRepository[StorageEndpoint]):
    """Repository for StorageEndpoint model."""

    model = StorageEndpoint

    async def lock_all(self, session):
        result = await session.execute(select(self.model).order_by(self.model.id).with_for_update()
                                       .execution_options(populate_existing=True))
        return list(result.scalars().all())

    async def guard_write(self, session, generations: dict[int, int]) -> None:
        """端点检查、任务资格检查与元数据写入必须处于同一个短事务。"""
        result = await session.execute(select(self.model).where(self.model.id.in_(generations))
            .order_by(self.model.id).with_for_update().execution_options(populate_existing=True))
        endpoints = {ep.id: ep for ep in result.scalars().all()}
        if any(ep_id not in endpoints or endpoints[ep_id].operation_generation != generation
               for ep_id, generation in generations.items()):
            raise StorageOperationStopped("端点已被清理，旧操作禁止回写")
        attempt = storage_attempt.get()
        if attempt:
            result = await session.execute(select(Task).where(Task.id == attempt[0]).with_for_update()
                                           .execution_options(populate_existing=True))
            task = result.scalar_one_or_none()
            if not task or task.status != "processing" or task.run_token != attempt[1]:
                raise StorageOperationStopped("任务已中断或由新的执行接管")

    async def clear_sync_dependencies(self, session, endpoint_id: int) -> None:
        await session.execute(update(self.model).where(self.model.sync_from_endpoint_id == endpoint_id)
            .values(sync_from_endpoint_id=None, auto_sync_enabled=False))

    async def has_cleanup_task(self, session, endpoint_id: int) -> bool:
        result = await session.execute(select(Task.id).where(
            Task.type.in_([StorageTaskType.DELETE.value, StorageTaskType.UNLINK.value]),
            or_(Task.status.in_(["pending", "processing"]),
                Task.payload["delete_in_flight"].as_boolean().is_(True)),
            Task.payload["endpoint_id"].as_integer() == endpoint_id,
        ).limit(1))
        return result.scalar_one_or_none() is not None

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
            if await self.has_cleanup_task(session, endpoint.id):
                return None, "存储端点有清理任务，请先完成或中断"
            return endpoint, None
        else:
            endpoint = await self.get_default_upload(session)
            if not endpoint:
                return None, "未配置可用的存储端点"
            if await self.has_cleanup_task(session, endpoint.id):
                return None, "默认存储端点有清理任务，请先完成或中断"
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
