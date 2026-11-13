"""存储任务的执行资格；上下文随子任务传播，不保存凭据。"""

import asyncio
from contextvars import ContextVar
from time import monotonic


class StorageOperationStopped(RuntimeError):
    """任务取消或端点已清理，禁止继续回写。"""


storage_attempt: ContextVar[tuple[str, str] | None] = ContextVar("storage_attempt", default=None)


# 仅在当前进程中唤醒调度；数据库仍是任务与恢复状态的唯一持久来源。
storage_wakeup: asyncio.Event | None = None
storage_progress: dict[tuple[str, str], float] = {}


def notify_storage_tasks() -> None:
    if storage_wakeup is not None:
        storage_wakeup.set()


def record_storage_progress(task_id: str) -> None:
    """只在事务成功提交后调用，旧执行器不能重新注册活跃记录。"""
    attempt = storage_attempt.get()
    if attempt is not None and attempt[0] == task_id and attempt in storage_progress:
        storage_progress[attempt] = monotonic()
