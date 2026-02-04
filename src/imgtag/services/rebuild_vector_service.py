#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""向量重建入队辅助

统一封装 rebuild_vector 入队逻辑，避免在多个 endpoint 中重复 try/except 与字段口径漂移。
"""

from __future__ import annotations

from typing import Any

from imgtag.core.logging_config import get_logger
from imgtag.services.task_queue import task_queue
from imgtag.utils.ids import dedup_positive_ints_keep_order

logger = get_logger(__name__)

async def enqueue_rebuild_vector(
    image_ids: list[int],
    *,
    context: str,
    log: Any | None = None,
) -> tuple[bool, int, list[int]]:
    """将图片向量重建任务入队。

    Returns:
        (enqueued_ok, added_count, normalized_image_ids)
    """
    normalized = dedup_positive_ints_keep_order(image_ids)
    if not normalized:
        return True, 0, []

    _log = log or logger
    try:
        added = await task_queue.add_tasks(normalized, task_type="rebuild_vector")
        return True, int(added), normalized
    except Exception as e:
        _log.warning(f"{context} 触发向量重建失败: image_ids={normalized[:10]}, error={e}")
        return False, 0, normalized
