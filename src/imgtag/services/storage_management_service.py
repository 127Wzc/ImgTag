"""端点配置、角色切换与离线清理；事务只覆盖本地数据库。"""

from uuid import uuid4

from fastapi import HTTPException

from imgtag.core.storage_constants import StorageTaskType
from imgtag.core.storage_runtime import notify_storage_tasks
from imgtag.db.repositories import image_location_repository, storage_endpoint_repository, task_repository
from imgtag.services.storage_task_control import storage_task_control

STRATEGY_FIELDS = {"read_priority", "read_weight", "is_enabled", "role", "is_default_upload"}


class StorageManagementService:
    async def validate_create(self, session, data) -> None:
        endpoints = await storage_endpoint_repository.lock_all(session)
        if data.role == "backup" and data.is_default_upload:
            raise HTTPException(400, "备份端点不能设为默认上传端点")
        if data.role == "backup" and any(ep.role == "backup" for ep in endpoints):
            raise HTTPException(400, "已存在备份端点，系统只允许一个备份端点")

    async def update(self, session, endpoint_id: int, values: dict):
        endpoints = await storage_endpoint_repository.lock_all(session)
        endpoint = next((ep for ep in endpoints if ep.id == endpoint_id), None)
        if endpoint is None:
            raise HTTPException(404, "端点不存在")
        values = {key: value for key, value in values.items()
                  if not (key in {"access_key_id", "secret_access_key"} and not value)
                  and getattr(endpoint, key) != value}
        if endpoint_id == 1:
            allowed = {"bucket_name", "public_url_prefix", "read_priority", "read_weight", "is_default_upload"}
            values = {key: value for key, value in values.items() if key in allowed}
        active_sync = await task_repository.get_active_for_endpoint(session, endpoint_id, [StorageTaskType.SYNC.value])
        if active_sync and values.keys() - STRATEGY_FIELDS:
            raise HTTPException(409, "同步期间只能调整优先级、权重、启停及主备角色，请先中断同步再修改基础配置")
        if values.keys() & {"bucket_name", "path_prefix"}:
            count = await image_location_repository.count_by_endpoint(session, endpoint_id)
            if count:
                raise HTTPException(400, f"该端点有 {count} 张关联图片，不能修改存储目录或路径前缀")
        if values.get("role") == "backup":
            if endpoint_id == 1:
                raise HTTPException(400, "默认本地端点不能切换为备份")
            former_backup = next((ep for ep in endpoints if ep.id != endpoint_id and ep.role == "backup"), None)
            # 原备份转为主端点，切换在同一事务完成，不受健康或启停状态影响。
            for other in endpoints:
                if other.id != endpoint_id and other.role == "backup":
                    other.role = "primary"
            if endpoint.is_default_upload:
                replacement = former_backup if former_backup and former_backup.is_enabled else next(
                    (ep for ep in endpoints if ep.id != endpoint_id and ep.is_enabled and ep.role == "primary"), None)
                endpoint.is_default_upload = False
                if replacement:
                    replacement.is_default_upload = True
        if values.get("is_default_upload"):
            if values.get("role", endpoint.role) != "primary":
                raise HTTPException(400, "备份端点不能设为默认上传端点")
            for other in endpoints:
                other.is_default_upload = other.id == endpoint_id
        if values:
            await storage_endpoint_repository.update(session, endpoint, **values)
        await session.flush()
        return endpoint

    async def cancel(self, session, endpoint_id: int, task_id: str | None = None) -> list[str]:
        tasks = await task_repository.get_active_storage_for_endpoint(session, endpoint_id)
        ids = [task.id for task in tasks if task_id is None or task.id == task_id]
        for task in tasks:
            if task.id in ids:
                await task_repository.update_status(session, task.id, "cancelled", error="管理员强制中断")
        await session.commit()
        storage_task_control.interrupt_local(ids)
        notify_storage_tasks()
        return ids

    async def cancel_sync(self, session, task_id: str):
        task = await task_repository.get_by_id(session, task_id)
        if not task or task.type != StorageTaskType.SYNC.value:
            raise HTTPException(404, "同步任务不存在")
        if task.status in ("pending", "processing"):
            await task_repository.update_status(session, task_id, "cancelled", error="管理员强制中断")
            await session.commit()
            storage_task_control.interrupt_local([task_id])
            notify_storage_tasks()

    async def force_cleanup(self, session, endpoint_id: int, *, remove_endpoint: bool,
                            expected_name: str | None = None, require_empty: bool = False,
                            initiated_by: str = "system"):
        if endpoint_id == 1:
            raise HTTPException(400, "默认本地端点不能强制清理")
        endpoints = await storage_endpoint_repository.lock_all(session)
        endpoint = next((ep for ep in endpoints if ep.id == endpoint_id), None)
        if endpoint is None:
            raise HTTPException(404, "端点不存在或已经移除")
        if expected_name is not None and expected_name != endpoint.name:
            raise HTTPException(409, "端点名称已变化，请刷新后重新确认")
        if require_empty:
            if await image_location_repository.count_by_endpoint(session, endpoint_id):
                raise HTTPException(409, "端点仍有图片关联，请解除关联或使用强制本地清理")
            if await task_repository.get_active_for_endpoint(session, endpoint_id, StorageTaskType.all_values()):
                raise HTTPException(409, "端点有进行中的任务，请先中断")
        endpoint.operation_generation += 1
        ids = await task_repository.revoke_endpoint_tasks(session, endpoint_id)
        count = await image_location_repository.remove_locations(session, endpoint_id)
        if remove_endpoint:
            await storage_endpoint_repository.clear_sync_dependencies(session, endpoint_id)
        cleanup_id = str(uuid4())
        await task_repository.create_task(session, task_id=cleanup_id, task_type=StorageTaskType.CLEANUP.value,
            payload={"endpoint_id": endpoint_id, "endpoint_name": endpoint.name, "initiated_by": initiated_by,
                     "remove_endpoint": remove_endpoint, "total_count": count})
        await task_repository.update_status(session, cleanup_id, "completed", result={
            "success_count": count, "failed_count": 0, "cancelled_task_ids": ids,
        })
        if remove_endpoint:
            await session.delete(endpoint)
        await session.commit()
        storage_task_control.interrupt_local(ids)
        notify_storage_tasks()
        return {"task_id": cleanup_id, "locations_removed": count, "cancelled_task_ids": ids, "endpoint_removed": remove_endpoint,
                "message": "本地关联及端点配置已移除" if remove_endpoint else "本地关联已清理，端点配置保持不变"}


storage_management_service = StorageManagementService()
