"""进程内事件唤醒存储调度，启动与五分钟兜底检查负责异常恢复。"""

import asyncio

from imgtag.core import storage_runtime
from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import StorageTaskType
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import task_repository
from imgtag.services.storage_deletion_service import storage_deletion_service
from imgtag.services.storage_sync_service import storage_sync_service
from imgtag.services.storage_unlink_service import storage_unlink_service
from imgtag.services.storage_task_control import storage_task_control

logger = get_logger(__name__)


async def recover_storage_tasks():
    scheduled = {}
    trigger = "应用启动"
    wakeup = asyncio.Event()
    storage_runtime.storage_wakeup = wakeup
    runners = {
        StorageTaskType.SYNC.value: storage_sync_service._process_sync_task,
        StorageTaskType.DELETE.value: storage_deletion_service._run_task,
        StorageTaskType.UNLINK.value: storage_unlink_service._run_task,
    }
    try:
        while True:
            # 扫描前清除信号，扫描期间的新通知会保留到下一轮，避免漏唤醒。
            wakeup.clear()
            try:
                logger.debug("存储任务调度检查开始（读取数据库）: trigger=%s", trigger)
                async with async_session_maker() as session:
                    tasks = await task_repository.get_recoverable_storage_tasks(session)
                dispatched = 0
                for task in tasks:
                    if task.type in runners and (task.id not in scheduled or scheduled[task.id].done()):
                        scheduled[task.id] = asyncio.create_task(runners[task.type](task.id))
                        dispatched += 1
                scheduled = {key: task for key, task in scheduled.items() if not task.done()}
                logger.debug("存储任务调度检查完成，查到待执行或待恢复任务 %s 个，新提交调度 %s 个；等待事件通知或 300 秒兜底检查",
                             len(tasks), dispatched)
            except Exception:
                logger.exception("存储任务调度检查失败，等待事件通知或下次兜底检查时重试")
            try:
                await asyncio.wait_for(wakeup.wait(), timeout=300)
                trigger = "任务事件通知"
            except asyncio.TimeoutError:
                trigger = "5 分钟兜底检查"
    finally:
        if storage_runtime.storage_wakeup is wakeup:
            storage_runtime.storage_wakeup = None
        for task in scheduled.values():
            task.cancel()
        await asyncio.gather(*scheduled.values(), return_exceptions=True)
        await storage_task_control.shutdown()
