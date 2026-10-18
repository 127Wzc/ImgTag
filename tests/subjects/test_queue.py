"""任务队列主体记忆判定层测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from imgtag.services.task_queue import task_queue


class _FakeSessionCtx:
    async def __aenter__(self):
        async def _commit():
            return None

        return SimpleNamespace(commit=_commit, flush=_commit)

    async def __aexit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def repo_defaults(monkeypatch):
    monkeypatch.setattr("imgtag.services.task_queue.image_repository.get_by_id_for_update", AsyncMock(return_value=SimpleNamespace(id=1)))
    monkeypatch.setattr("imgtag.services.task_queue.image_repository.get_image_tags_with_source", AsyncMock(return_value=[]))
    monkeypatch.setattr("imgtag.services.task_queue.subject_repository.list_matching_tags", AsyncMock(return_value=[]))
    monkeypatch.setattr("imgtag.services.task_queue.subject_repository.get_by_id", AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_confirmed_manual_subject_short_circuits_matcher(monkeypatch) -> None:
    """已有人工确认主体时：直接返回提示词约束，不执行自动匹配。"""
    monkeypatch.setattr(
        "imgtag.services.task_queue.async_session_maker", lambda: _FakeSessionCtx()
    )

    confirmed = SimpleNamespace(
        subject_id=3,
        source="manual",
        state="confirmed",
        confidence=None, updated_at="v1",
        subject=SimpleNamespace(id=3, name="张三", is_active=True, aliases=["阿三"], description="人物定义", updated_at="v1"),
    )
    match_calls: list = []

    async def fake_get_primary(session, image_id):
        _ = session, image_id
        return [confirmed]

    async def fake_match(**kwargs):
        match_calls.append(kwargs)
        return {"status": "no_match", "subject_id": None, "confidence": None}

    monkeypatch.setattr(
        "imgtag.db.repositories.image_subject_repository.get_current", fake_get_primary
    )
    monkeypatch.setattr(
        "imgtag.services.subject_memory_service.subject_memory_service.match_primary_subject",
        fake_match,
    )

    hints = await task_queue._resolve_subject_memory(
        image_id=1,
        file_content=b"fake",
        mime_type="image/jpeg",
    )

    assert hints[0]["name"] == "张三"
    assert hints[0]["definition"] == "人物定义"
    assert hints[0]["aliases"] == ["阿三"]
    assert hints[0]["status"] == "confirmed"
    assert match_calls == []


@pytest.mark.asyncio
async def test_low_conf_skips_when_pending_suggestion_exists(monkeypatch) -> None:
    """低置信命中但已有 pending 建议时：不重复创建审批。"""
    monkeypatch.setattr(
        "imgtag.services.task_queue.async_session_maker", lambda: _FakeSessionCtx()
    )

    async def fake_get_primary(session, image_id):
        _ = session, image_id
        return []

    async def fake_match(**kwargs):
        _ = kwargs
        return {
            "status": "low_conf",
            "subject_id": 8,
            "subject_name": "李四",
            "confidence": 0.45,
            "hint_text": None,
            "candidates": [],
        }

    created: list = []

    async def fake_has_pending(session, image_id):
        _ = session, image_id
        return True

    async def fake_create_suggestion(session, **kwargs):
        _ = session
        created.append(kwargs)
        return SimpleNamespace(id=1)

    monkeypatch.setattr(
        "imgtag.db.repositories.image_subject_repository.get_current", fake_get_primary
    )
    monkeypatch.setattr(
        "imgtag.services.subject_memory_service.subject_memory_service.match_primary_subject",
        fake_match,
    )
    monkeypatch.setattr(
        "imgtag.services.subject_assignment_service.subject_assignment_service.has_pending_subject_suggestion",
        fake_has_pending,
    )
    monkeypatch.setattr(
        "imgtag.services.subject_assignment_service.subject_assignment_service.create_subject_suggestion",
        fake_create_suggestion,
    )

    hints = await task_queue._resolve_subject_memory(
        image_id=2,
        file_content=b"fake",
        mime_type="image/jpeg",
    )

    assert hints == []
    assert created == []


@pytest.mark.asyncio
async def test_add_tasks_force_analyze_flag(monkeypatch) -> None:
    """force_analyze 应写入任务 payload；默认不写入。"""
    monkeypatch.setattr(
        "imgtag.services.task_queue.async_session_maker", lambda: _FakeSessionCtx()
    )
    # 避免触发后台队列处理
    monkeypatch.setattr(task_queue, "_running", True)

    created_payloads: list[dict] = []
    pending_calls: list[str] = []

    async def fake_get_pending(session, image_id, task_type):
        pending_calls.append(task_type)
        return []

    async def fake_create_task(session, *, task_id, task_type, payload):
        _ = session, task_id, task_type
        created_payloads.append(payload)
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(
        "imgtag.services.task_queue.task_repository.create_task", fake_create_task
    )
    monkeypatch.setattr("imgtag.services.task_queue.task_repository.list_active_for_image", fake_get_pending)

    added = await task_queue.add_tasks([101], force_analyze=True)
    assert added == 1
    assert created_payloads[0].get("force_analyze") is True

    added = await task_queue.add_tasks([102])
    assert added == 1
    assert "force_analyze" not in created_payloads[1]
    assert pending_calls == ["analyze_image", "analyze_image"]
