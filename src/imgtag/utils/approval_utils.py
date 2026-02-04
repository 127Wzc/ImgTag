#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""审批相关工具函数。

用于收敛 approvals 中对 payload/target_ids 的兼容解析逻辑，避免在 endpoint/service 中重复实现。
"""

from __future__ import annotations

from typing import Any

from imgtag.core.logging_config import get_logger
from imgtag.utils.ids import to_positive_int

logger = get_logger(__name__)


def extract_image_id_from_approval(
    approval: Any,
    *,
    log: Any | None = None,
) -> int | None:
    """从 approval 中提取 image_id（用于预览与向量重建）。

    读取顺序：
    1) payload.image_id（payload 必须是 dict）
    2) target_ids[0]

    若存在但无法解析为正整数，则记录 warning 并尝试 fallback。
    """
    _log = log or logger

    payload = approval.payload if isinstance(getattr(approval, "payload", None), dict) else {}
    raw = payload.get("image_id")
    image_id = to_positive_int(raw)
    if raw is not None and image_id is None:
        _log.warning(f"审批记录 payload.image_id 非法: approval_id={getattr(approval, 'id', None)}, raw={raw}")
    if image_id is not None:
        return image_id

    target_raw = None
    target_ids = getattr(approval, "target_ids", None)
    if target_ids:
        target_raw = target_ids[0]
    target_id = to_positive_int(target_raw)
    if target_raw is not None and target_id is None:
        _log.warning(
            f"审批记录 target_ids[0] 非法: approval_id={getattr(approval, 'id', None)}, raw={target_raw}"
        )
    return target_id

