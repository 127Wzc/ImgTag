#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""主体记忆匹配服务。"""

from __future__ import annotations

from typing import Any

from imgtag.core.config_cache import config_cache
from imgtag.core.logging_config import get_logger
from imgtag.services.subject_matcher_stub import subject_matcher_stub

logger = get_logger(__name__)


def build_subject_hint(subject_name: str) -> str:
    """构造注入视觉提示词的主体约束文案（人工确认与高置信命中共用同一口径）。"""
    return f"已确认主体：{subject_name}。请保持主体一致，不要猜测其他主体。"


class SubjectMemoryService:
    """主体记忆判定层（V1: stub backend）。"""

    async def _get_bool(self, key: str, default: str = "false") -> bool:
        value = await config_cache.get(key, default)
        return str(value or default).lower() == "true"

    async def _get_int(self, key: str, default: int) -> int:
        value = await config_cache.get(key, str(default))
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    async def _get_float(self, key: str, default: float) -> float:
        value = await config_cache.get(key, str(default))
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    async def match_primary_subject(
        self,
        *,
        image_id: int,
        image_data: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        enabled = await self._get_bool("subject_memory_enabled", "true")
        if not enabled:
            return {
                "status": "disabled",
                "subject_id": None,
                "subject_name": None,
                "confidence": None,
                "hint_text": None,
                "candidates": [],
            }

        backend = (await config_cache.get("subject_matcher_backend", "stub") or "stub").strip().lower()
        max_candidates = max(1, await self._get_int("subject_max_candidates", 3))
        high_th = await self._get_float("subject_high_threshold", 0.50)
        low_th = await self._get_float("subject_low_threshold", 0.40)
        auto_apply_high = await self._get_bool("subject_auto_apply_high_conf", "true")

        if backend != "stub":
            logger.warning(f"未支持的 subject matcher backend={backend}，降级为 stub")

        raw = await subject_matcher_stub.match_primary_subject(
            image_id=image_id,
            image_data=image_data,
            mime_type=mime_type,
            max_candidates=max_candidates,
        )
        confidence = raw.get("confidence")
        if confidence is None:
            decision = "no_match"
        elif confidence >= high_th:
            decision = "high_conf" if auto_apply_high else "high_conf_manual"
        elif confidence >= low_th:
            decision = "low_conf"
        else:
            decision = "no_match"

        hint_text = None
        if decision in ("high_conf", "high_conf_manual"):
            subject_name = raw.get("subject_name")
            if subject_name:
                hint_text = build_subject_hint(str(subject_name))

        return {
            "status": decision,
            "subject_id": raw.get("subject_id"),
            "subject_name": raw.get("subject_name"),
            "confidence": confidence,
            "hint_text": hint_text,
            "candidates": raw.get("candidates", []),
            "reason": raw.get("reason", ""),
        }


subject_memory_service = SubjectMemoryService()
