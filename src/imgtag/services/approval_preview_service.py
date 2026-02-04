#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""审批预览构建服务

为审批列表（approvals）批量构建图片预览信息，减少前端 N+1 请求。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.logging_config import get_logger
from imgtag.db.repositories import image_repository
from imgtag.services.storage_service import storage_service
from imgtag.utils.approval_utils import extract_image_id_from_approval
from imgtag.utils.ids import dedup_positive_ints_keep_order

logger = get_logger(__name__)


class ApprovalPreviewService:
    """审批预览服务（无状态）。"""

    async def build_preview_map(
        self,
        session: AsyncSession,
        *,
        approvals: list[Any],
        log: Any | None = None,
    ) -> dict[int, dict[str, Any]]:
        """为审批列表构建预览信息（按 approval_id 映射）。"""
        _log = log or logger

        image_ids: list[int] = []
        approval_to_image: dict[int, int] = {}

        for a in approvals:
            image_id = extract_image_id_from_approval(a, log=_log)
            if not image_id:
                continue
            approval_id = int(getattr(a, "id"))
            approval_to_image[approval_id] = int(image_id)
            image_ids.append(int(image_id))

        image_ids = dedup_positive_ints_keep_order(image_ids)
        if not image_ids:
            return {}

        # DB 侧信息：上传者/用户名
        uploader_map = await image_repository.get_uploader_preview_map(session, image_ids)

        # 存储侧信息：签名 URL（允许降级）
        url_map: dict[int, str] = {}
        try:
            images = await image_repository.get_by_ids(session, image_ids)
            url_map = await storage_service.get_read_urls_with_session(session, list(images))
        except Exception as e:
            _log.warning(f"构建审批预览 URL 失败，将降级为空: error={e}")
            url_map = {}

        result: dict[int, dict[str, Any]] = {}
        for approval_id, image_id in approval_to_image.items():
            uploader = uploader_map.get(int(image_id)) or {}
            result[int(approval_id)] = {
                "image_id": int(image_id),
                "image_url": url_map.get(int(image_id), "") or "",
                "uploaded_by": uploader.get("uploaded_by"),
                "uploaded_by_username": uploader.get("uploaded_by_username"),
            }

        return result


approval_preview_service = ApprovalPreviewService()

