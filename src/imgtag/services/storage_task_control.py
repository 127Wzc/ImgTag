"""存储任务租约、中断及端点快照。取消结果由数据库决定，支持多进程。"""

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic

from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger
from imgtag.core.storage_runtime import storage_attempt, storage_progress, notify_storage_tasks
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import storage_endpoint_repository, task_repository
from imgtag.models.storage_endpoint import StorageEndpoint

logger = get_logger(__name__)

SNAPSHOT_FIELDS = (
    "id", "name", "provider", "endpoint_url", "region", "bucket_name", "path_style",
    "public_url_prefix", "public_url_include_bucket",
    "path_prefix",
    "operation_generation",
)


def snapshot_endpoint(endpoint: StorageEndpoint) -> dict:
    # 不把凭据复制到历史任务中，避免密钥轮换后留下不可解密的副本。
    return {key: getattr(endpoint, key) for key in SNAPSHOT_FIELDS}


def restore_endpoint(snapshot: dict) -> StorageEndpoint:
    return StorageEndpoint(**snapshot)


async def load_endpoint_snapshot(session, snapshot: dict | None, endpoint_id: int):
    current = await storage_endpoint_repository.get_by_id(session, endpoint_id)
    if not current or not snapshot:
        return current
    endpoint = restore_endpoint(snapshot)
    # 每次实际启动读取当前凭据；执行期间保留在内存快照中，后续编辑不改变本次请求。
    endpoint._access_key_id = current._access_key_id
    endpoint._secret_access_key = current._secret_access_key
    return endpoint


class StorageTaskControl:
    def __init__(self):
        self._running: dict[str, asyncio.Task] = {}
        self._controllers: set[asyncio.Task] = set()

    def interrupt_local(self, task_ids: list[str]) -> None:
        for task_id in task_ids:
            task = self._running.get(task_id)
            if task is not None:
                task.cancel()

    async def shutdown(self) -> None:
        controllers = list(self._controllers)
        for task in controllers:
            task.cancel()
        await asyncio.gather(*controllers, return_exceptions=True)

    async def run(self, task_id: str, operation: Callable[[], Awaitable[None]]) -> None:
        try:
            async with async_session_maker() as session:
                token = await task_repository.claim_storage_task(session, task_id)
                await session.commit()
        except Exception:
            logger.exception("存储任务领取失败，等待后续调度重试: task_id=%s", task_id)
            return
        if token is None:
            logger.debug("存储任务本次未取得执行资格，不启动执行器: task_id=%s", task_id)
            return
        context_token = storage_attempt.set((task_id, token))
        attempt = (task_id, token)
        storage_progress[attempt] = monotonic()
        child = asyncio.create_task(operation())
        controller = asyncio.current_task()
        if controller is not None:
            self._controllers.add(controller)
        self._running[task_id] = child
        heartbeat_interval = min(15, settings.STORAGE_TASK_LEASE_SECONDS / 3)
        logger.debug("存储任务执行器已启动，开始检查是否需要补写心跳: task_id=%s interval_seconds=%.1f",
                     task_id, heartbeat_interval)
        try:
            while not child.done():
                done, _ = await asyncio.wait({child}, timeout=heartbeat_interval)
                if not done:
                    if monotonic() - storage_progress[attempt] < heartbeat_interval:
                        logger.debug("存储任务近期进度已保存，跳过额外心跳写入（本次不访问数据库）: task_id=%s", task_id)
                        continue
                    async with async_session_maker() as session:
                        alive = await task_repository.heartbeat_storage_task(session, task_id, token)
                        await session.commit()
                    if alive:
                        storage_progress[attempt] = monotonic()
                        logger.debug("存储任务近期无新进度，已补写数据库心跳: task_id=%s interval_seconds=%.1f",
                                     task_id, heartbeat_interval)
                    else:
                        logger.debug("存储任务执行资格已失效，心跳未写入，停止当前执行器: task_id=%s", task_id)
                        child.cancel()
                        await asyncio.gather(child, return_exceptions=True)
                        return
            await child
        except asyncio.CancelledError:
            logger.debug("存储任务执行器收到中断信号，撤销回写资格并停止执行: task_id=%s", task_id)
            # 先撤销资格，再取消子任务，防止其 finally 或迟到结果继续回写。
            await self._fail_if_active(task_id, "执行已中断；未完成项目可重新发起")
            child.cancel()
            await asyncio.gather(child, return_exceptions=True)
        except Exception as error:
            child.cancel()
            await asyncio.gather(child, return_exceptions=True)
            logger.warning("存储任务执行异常，停止当前执行器: task_id=%s error=%s", task_id, error)
            await self._fail_if_active(task_id, str(error))
        finally:
            if self._running.get(task_id) is child:
                self._running.pop(task_id, None)
            if controller is not None:
                self._controllers.discard(controller)
            storage_progress.pop(attempt, None)
            storage_attempt.reset(context_token)
            logger.debug("存储任务执行器已退出，心跳检查已停止: task_id=%s", task_id)
            notify_storage_tasks()

    async def _fail_if_active(self, task_id: str, error: str) -> None:
        try:
            async with async_session_maker() as session:
                await task_repository.update_status(session, task_id, "failed", error=error)
                await session.commit()
        except Exception:
            logger.exception("存储任务 %s 无法记录中断状态，将在租约过期后重新接管", task_id)


storage_task_control = StorageTaskControl()
