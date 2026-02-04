#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""修改建议服务

用于“非上传者修改他人图片”场景：
- 普通成员提交修改建议（落库为 Approval）
- 管理员审批后落地修改（更新图片元信息并触发向量重建）
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.logging_config import get_logger
from imgtag.db.repositories import (
    approval_repository,
    image_repository,
    image_tag_repository,
)
from imgtag.models.approval import Approval
from imgtag.services.image_update_service import image_update_service

logger = get_logger(__name__)


SUGGEST_IMAGE_UPDATE_TYPE = "suggest_image_update"


class SuggestionService:
    """修改建议服务（无状态）。"""

    async def create_image_update_suggestion(
        self,
        session: AsyncSession,
        *,
        image_id: int,
        requester_id: int,
        description: str,
        category_id: int | None,
        normal_tag_ids: list[int],
        comment: str | None = None,
    ) -> Approval:
        """创建图片元信息修改建议（Approval）。"""
        image = await image_repository.get_with_tags(session, image_id)
        if not image:
            raise ValueError(f"图片 #{image_id} 不存在")

        # Base snapshot
        base_description = image.description or ""
        base_category = next((t for t in (image.tags or []) if t.level == 0), None)
        base_category_id = base_category.id if base_category else None
        base_category_name = base_category.name if base_category else None

        base_normal_tags = sorted(
            [t for t in (image.tags or []) if t.level == 2],
            key=lambda t: t.name,
        )
        base_normal_tag_ids = [t.id for t in base_normal_tags]
        base_normal_tags_payload = [{"id": t.id, "name": t.name} for t in base_normal_tags]

        # Proposed validation
        proposed_category_name = None
        if category_id is not None:
            if category_id == 0:
                category_id = None
            if category_id is not None:
                proposed_category_name = await image_update_service.validate_category_id(
                    session,
                    category_id=category_id,
                )

        normalized_tag_ids, normalized_tag_names = (
            await image_update_service.normalize_and_validate_normal_tag_ids(
                session,
                normal_tag_ids=normal_tag_ids or [],
            )
        )
        proposed_normal_tags_payload = [
            {"id": tid, "name": name}
            for tid, name in zip(normalized_tag_ids, normalized_tag_names)
        ]

        payload = {
            "image_id": image_id,
            "base": {
                "description": base_description,
                "category_id": base_category_id,
                "category_name": base_category_name,
                "normal_tag_ids": base_normal_tag_ids,
                "normal_tags": base_normal_tags_payload,
            },
            "proposed": {
                "description": description,
                "category_id": category_id,
                "category_name": proposed_category_name,
                "normal_tag_ids": normalized_tag_ids,
                "normal_tags": proposed_normal_tags_payload,
                "comment": comment,
            },
        }

        approval = await approval_repository.create(
            session,
            type=SUGGEST_IMAGE_UPDATE_TYPE,
            requester_id=requester_id,
            target_type="image",
            target_ids=[image_id],
            payload=payload,
        )

        logger.info(
            f"创建修改建议: approval_id={approval.id}, image_id={image_id}, requester_id={requester_id}"
        )
        return approval

    async def apply_image_update_suggestion(
        self,
        session: AsyncSession,
        *,
        approval: Approval,
    ) -> int:
        """执行图片元信息修改建议（落地到 Image/ImageTag）。"""
        payload = approval.payload if isinstance(approval.payload, dict) else {}
        image_id = payload.get("image_id")
        proposed = payload.get("proposed") or {}
        if not isinstance(proposed, dict):
            proposed = {}

        if not image_id:
            raise ValueError("审批 payload 缺少 image_id")

        image = await image_repository.get_by_id(session, int(image_id))
        if not image:
            raise ValueError(f"图片 #{image_id} 不存在")

        description = proposed.get("description", "")
        category_id = proposed.get("category_id")
        normal_tag_ids = proposed.get("normal_tag_ids") or []

        # 1) 更新描述（允许空串）
        await image_repository.update_image(
            session,
            image,
            description=description,
        )

        # 2) 更新主分类（保证唯一；允许清空）
        await image_tag_repository.set_image_category(
            session,
            int(image_id),
            int(category_id) if category_id else None,
            source="user",
            added_by=approval.requester_id,
        )

        # 3) 更新普通标签（仅 level=2）
        await image_tag_repository.set_image_tags_by_ids(
            session,
            int(image_id),
            [int(tid) for tid in normal_tag_ids if tid],
            source="user",
            added_by=approval.requester_id,
        )

        logger.info(f"修改建议已落地: approval_id={approval.id}, image_id={image_id}")
        return int(image_id)


suggestion_service = SuggestionService()
