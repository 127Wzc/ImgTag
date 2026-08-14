#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""主体匹配占位实现（V1）。"""

from __future__ import annotations

from typing import Any


class SubjectMatcherStub:
    """始终返回 NO_MATCH，用于后续无缝替换真实识别器。"""

    async def match_primary_subject(
        self,
        *,
        image_id: int,
        image_data: bytes,
        mime_type: str,
        max_candidates: int = 3,
    ) -> dict[str, Any]:
        _ = image_id, image_data, mime_type, max_candidates
        return {
            "status": "no_match",
            "confidence": None,
            "subject_id": None,
            "subject_name": None,
            "candidates": [],
            "reason": "stub_no_match",
        }


subject_matcher_stub = SubjectMatcherStub()
