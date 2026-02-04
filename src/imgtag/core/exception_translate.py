#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""异常翻译器

用于将底层技术异常统一翻译为对外 APIError（带错误码/友好文案），方便集中扩展维护。

约定：
- 本模块只做“异常类型 → APIError”的映射与必要的处置建议，不直接返回 Response。
- 日志在调用方统一记录，避免重复输出。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from asyncpg.exceptions import InvalidCachedStatementError

from imgtag.core.exceptions import APIError, DBSchemaChangedError, DBTimeoutError

LogLevel = Literal["debug", "info", "warning", "error"]


@dataclass(frozen=True)
class ExceptionTranslation:
    """异常翻译结果。"""

    api_error: APIError
    log_level: LogLevel = "error"
    dispose_engine: bool = False


def _iter_exception_chain(exc: BaseException) -> list[BaseException]:
    """尽可能遍历异常链，覆盖 SQLAlchemy 包装（orig）与 Python cause/context。"""
    seen: set[int] = set()
    queue: list[BaseException] = [exc]
    out: list[BaseException] = []

    while queue:
        cur = queue.pop(0)
        cur_id = id(cur)
        if cur_id in seen:
            continue
        seen.add(cur_id)
        out.append(cur)

        orig = getattr(cur, "orig", None)
        if isinstance(orig, BaseException):
            queue.append(orig)

        cause = getattr(cur, "__cause__", None)
        if isinstance(cause, BaseException):
            queue.append(cause)

        context = getattr(cur, "__context__", None)
        if isinstance(context, BaseException):
            queue.append(context)

    return out


def translate_exception(exc: Exception) -> ExceptionTranslation | None:
    """将异常翻译为对外 APIError。

    返回 None 表示“不识别”，由上层走默认 500 兜底。
    """
    # asyncpg prepared statement plan 失效（常见于运行时执行 ALTER TABLE/重建索引后）
    for e in _iter_exception_chain(exc):
        if isinstance(e, InvalidCachedStatementError):
            return ExceptionTranslation(
                api_error=DBSchemaChangedError(),
                log_level="warning",
                dispose_engine=True,
            )

    # 数据库连接/执行超时（常见于数据库不可用或网络抖动）
    for e in _iter_exception_chain(exc):
        if isinstance(e, (TimeoutError, SQLAlchemyTimeoutError)):
            return ExceptionTranslation(
                api_error=DBTimeoutError(),
                log_level="warning",
            )

    return None
