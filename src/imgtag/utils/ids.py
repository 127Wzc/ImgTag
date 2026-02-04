#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""ID 归一化工具

用于统一处理“可能来自请求/DB payload 的 ID 值”，提供：
- 转换为正整数（不可转换/<=0 返回 None）
- 保序去重并过滤非法值
"""

from __future__ import annotations

from typing import Any, Iterable


def to_positive_int(value: Any) -> int | None:
    """将任意值转换为正整数。

    - 不可转换（TypeError/ValueError）返回 None
    - <= 0 返回 None
    """
    if value is None:
        return None
    # 避免 bool 被当作 0/1 的 ID
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, float) and not value.is_integer():
            return None
        iv = int(value)
    except (TypeError, ValueError):
        return None
    if iv <= 0:
        return None
    return iv


def dedup_positive_ints_keep_order(values: Iterable[Any] | None) -> list[int]:
    """保序去重并过滤非法 ID（仅保留正整数）。"""
    if not values:
        return []

    seen: set[int] = set()
    result: list[int] = []
    for v in values:
        iv = to_positive_int(v)
        if iv is None or iv in seen:
            continue
        seen.add(iv)
        result.append(iv)
    return result
