#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""主体纠正与审批落地服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.logging_config import get_logger
from imgtag.db.repositories import (
    approval_repository,
    image_repository,
    image_subject_repository,
    image_tag_repository,
    subject_repository,
    subject_sample_repository,
)
from imgtag.models.approval import Approval
from imgtag.models.subject import ImageSubject, Subject

logger = get_logger(__name__)

SUGGEST_SUBJECT_ASSIGNMENT_TYPE = "suggest_subject_assignment"

# 人工确认来源：自动匹配结果不得覆盖
PROTECTED_ASSIGNMENT_SOURCES = ("manual", "approval")

# V1 样本仅登记来源图片引用，真实向量由后续识别器接入时回填
SAMPLE_REFERENCE_MODEL = "reference"


class SubjectAssignmentService:
    """主体纠正服务（无状态）。"""

    async def _get_valid_image_and_subject(
        self,
        session: AsyncSession,
        *,
        image_id: int,
        subject_id: int,
    ) -> tuple[Any, Any]:
        # 锁住图片父行，避免首次并发设置主体时两边都插入 primary 记录。
        image = await image_repository.get_by_id_for_update(session, image_id)
        if not image:
            raise ValueError(f"图片 #{image_id} 不存在")

        subject = await subject_repository.get_by_id(session, subject_id)
        if not subject:
            raise ValueError(f"主体 #{subject_id} 不存在")
        if not subject.is_active:
            raise ValueError(f"主体 #{subject_id} 已停用")

        return image, subject

    @staticmethod
    def _assignment_to_dict(
        *,
        subject_id: int,
        subject_name: str,
        confidence: Any,
        source: str,
        state: str,
        is_primary: bool,
        changed: bool,
    ) -> dict[str, Any]:
        return {
            "subject_id": subject_id,
            "subject_name": subject_name,
            "confidence": float(confidence) if confidence is not None else None,
            "source": source,
            "state": state,
            "is_primary": is_primary,
            "changed": changed,
        }

    async def _sync_primary_tag(
        self,
        session: AsyncSession,
        *,
        image_id: int,
        new_subject: Subject,
        previous: ImageSubject | None,
        actor_id: int | None,
        source: str,
    ) -> bool | None:
        """主体落地后同步图片标签：挂接新主体的主名称标签，移除旧主体的主名称标签。

        标签来源规则：
        - 人工/审批 → source="user"
        - 自动命中 → source="system"
        两者均不会被 AI 重分析清除（set_image_tags 仅清除 source="ai"）。

        Returns:
            True 表示本次由主体流程新增标签；False 表示标签原本已存在；
            None 表示同一主体的幂等重复设置，应保留既有归属记录。
        """
        new_tag_id = int(new_subject.primary_tag_id)
        tag_source = "system" if source == "auto" else "user"

        if (
            previous is not None
            and previous.subject is not None
            and int(previous.subject_id) != int(new_subject.id)
        ):
            old_tag_id = int(previous.subject.primary_tag_id)
            # 仅移除先前明确由主体流程添加的标签，绝不删除用户原有标签。
            if (
                old_tag_id != new_tag_id
                and getattr(previous, "synced_primary_tag_id", None) == old_tag_id
            ):
                await image_tag_repository.remove_tag_from_image(session, image_id, old_tag_id)

        existing = await image_tag_repository.get_image_tag(session, image_id, new_tag_id)
        if existing is None:
            await image_tag_repository.add_tag_to_image(
                session,
                image_id,
                new_tag_id,
                source=tag_source,
                added_by=actor_id,
            )
            return True
        elif existing.source == "ai":
            # 已作为 AI 标签存在时升级来源，避免后续 AI 重分析时被清除
            existing.source = tag_source
            await session.flush()
        if previous is not None and int(previous.subject_id) == int(new_subject.id):
            return None
        return False

    async def assign_primary_subject(
        self,
        session: AsyncSession,
        *,
        image_id: int,
        subject_id: int,
        actor_id: int | None,
        confidence: float | None = None,
        source: str = "manual",
        state: str = "confirmed",
        add_sample: bool = False,
        comment: str | None = None,
    ) -> dict[str, Any]:
        _, subject = await self._get_valid_image_and_subject(
            session,
            image_id=image_id,
            subject_id=subject_id,
        )

        previous = await image_subject_repository.get_primary(session, image_id)

        # 来源优先级：自动结果不得覆盖人工/审批确认的主体
        if (
            source == "auto"
            and previous is not None
            and previous.source in PROTECTED_ASSIGNMENT_SOURCES
        ):
            logger.info(
                f"跳过自动主体写入（已有人工确认）: image_id={image_id}, "
                f"existing_subject_id={previous.subject_id}, auto_subject_id={subject_id}"
            )
            return self._assignment_to_dict(
                subject_id=int(previous.subject_id),
                subject_name=previous.subject.name if previous.subject else "",
                confidence=previous.confidence,
                source=previous.source,
                state=previous.state,
                is_primary=True,
                changed=False,
            )

        assignment = await image_subject_repository.set_primary_subject(
            session,
            image_id=image_id,
            subject_id=subject_id,
            confidence=confidence,
            source=source,
            state=state,
            created_by=actor_id,
        )

        tag_added_by_subject = await self._sync_primary_tag(
            session,
            image_id=image_id,
            new_subject=subject,
            previous=previous,
            actor_id=actor_id,
            source=source,
        )
        if tag_added_by_subject is not None:
            assignment.synced_primary_tag_id = (
                int(subject.primary_tag_id) if tag_added_by_subject else None
            )
            await session.flush()

        if add_sample:
            await subject_sample_repository.create_sample(
                session,
                subject_id=subject.id,
                image_id=image_id,
                embedding_model=SAMPLE_REFERENCE_MODEL,
                embedding=None,
                metadata={"comment": comment or "", "source": source},
                created_by=actor_id,
            )

        return self._assignment_to_dict(
            subject_id=subject.id,
            subject_name=subject.name,
            confidence=assignment.confidence,
            source=assignment.source,
            state=assignment.state,
            is_primary=assignment.is_primary,
            changed=True,
        )

    async def has_pending_subject_suggestion(
        self,
        session: AsyncSession,
        image_id: int,
    ) -> bool:
        """查询图片是否已有待审批的主体建议（用于去重）。"""
        return await approval_repository.has_pending_of_type(
            session,
            type_=SUGGEST_SUBJECT_ASSIGNMENT_TYPE,
            target_id=image_id,
        )

    async def create_subject_suggestion(
        self,
        session: AsyncSession,
        *,
        image_id: int,
        requester_id: int | None,
        subject_id: int,
        confidence: float | None = None,
        comment: str | None = None,
        add_sample: bool = False,
    ) -> Approval:
        _, subject = await self._get_valid_image_and_subject(
            session,
            image_id=image_id,
            subject_id=subject_id,
        )

        if await self.has_pending_subject_suggestion(session, image_id):
            raise ValueError("该图片已有待审批的主体建议，请等待管理员处理")

        current = await image_subject_repository.get_primary(session, image_id)
        base_subject = None
        if current and current.subject:
            base_subject = {
                "subject_id": current.subject_id,
                "subject_name": current.subject.name,
                "confidence": float(current.confidence) if current.confidence is not None else None,
            }

        payload = {
            "image_id": image_id,
            "base_subject": base_subject,
            "proposed_subject": {
                "subject_id": subject.id,
                "subject_name": subject.name,
            },
            "confidence": confidence,
            "comment": comment,
            "add_sample": bool(add_sample),
        }

        # 应用层预检查无法消除并发窗口；数据库部分唯一索引是最终约束。
        try:
            async with session.begin_nested():
                return await approval_repository.create(
                    session,
                    type=SUGGEST_SUBJECT_ASSIGNMENT_TYPE,
                    requester_id=requester_id,
                    target_type="image",
                    target_ids=[image_id],
                    payload=payload,
                )
        except IntegrityError as e:
            raise ValueError("该图片已有待审批的主体建议，请等待管理员处理") from e

    async def apply_subject_suggestion(
        self,
        session: AsyncSession,
        *,
        approval: Approval,
    ) -> int:
        payload = approval.payload if isinstance(approval.payload, dict) else {}
        image_id = int(payload.get("image_id") or 0)
        proposed = payload.get("proposed_subject") if isinstance(payload.get("proposed_subject"), dict) else {}
        subject_id = int((proposed or {}).get("subject_id") or 0)

        if image_id <= 0:
            raise ValueError("审批 payload 缺少 image_id")
        if subject_id <= 0:
            raise ValueError("审批 payload 缺少 proposed_subject.subject_id")

        confidence_raw = payload.get("confidence")
        confidence = float(confidence_raw) if confidence_raw is not None else None
        comment = payload.get("comment")
        add_sample = bool(payload.get("add_sample", False))

        await self.assign_primary_subject(
            session,
            image_id=image_id,
            subject_id=subject_id,
            actor_id=approval.requester_id,
            confidence=confidence,
            source="approval",
            state="confirmed",
            add_sample=add_sample,
            comment=comment if isinstance(comment, str) else None,
        )
        return image_id


subject_assignment_service = SubjectAssignmentService()
