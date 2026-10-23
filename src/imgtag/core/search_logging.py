"""搜索阶段耗时；仅 DEBUG 启用，禁止传入搜索原文、SQL 参数或凭据。"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter
from uuid import uuid4

from imgtag.core.logging_config import get_logger

logger = get_logger("imgtag.search")
_context: ContextVar[tuple[str, str] | None] = ContextVar("search_log_context", default=None)


@contextmanager
def search_stage(stage: str, **fields):
    """只记录受控的数量、状态、耗时；调用方可补充结果数量。"""
    context = _context.get()
    if context is None or not logger.isEnabledFor(logging.DEBUG):
        yield fields
        return
    started = perf_counter()
    status = "ok"
    try:
        yield fields
    except BaseException as exc:
        status = "error"
        fields["error_type"] = type(exc).__name__
        raise
    finally:
        details = " ".join(f"{key}={value}" for key, value in fields.items())
        logger.debug(
            "搜索执行 trace=%s kind=%s stage=%s status=%s elapsed_ms=%.2f%s",
            context[0], context[1], stage, status, (perf_counter() - started) * 1000,
            f" {details}" if details else "",
        )


def traced_search(kind: str):
    """一次搜索共用编号；嵌套服务/仓库调用沿用入口编号，退出后恢复上下文。"""
    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            if _context.get() is not None or not logger.isEnabledFor(logging.DEBUG):
                return await function(*args, **kwargs)
            token = _context.set((uuid4().hex[:12], kind))
            try:
                logger.debug("搜索开始 trace=%s kind=%s", _context.get()[0], kind)
                with search_stage("total"):
                    return await function(*args, **kwargs)
            finally:
                _context.reset(token)
        return wrapped
    return decorate
