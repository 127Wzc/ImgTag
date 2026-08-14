from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from imgtag.services.subject_assignment_service import SubjectAssignmentService

SERVICE_MODULE = "imgtag.services.subject_assignment_service"


class DummyApproval:
    def __init__(self, payload, requester_id=None):
        self.payload = payload
        self.requester_id = requester_id


def _make_previous(
    subject_id: int,
    source: str,
    primary_tag_id: int,
    name: str = "旧主体",
    synced_primary_tag_id: int | None = None,
):
    return SimpleNamespace(
        subject_id=subject_id,
        source=source,
        state="confirmed",
        confidence=0.9,
        subject=SimpleNamespace(
            id=subject_id,
            name=name,
            primary_tag_id=primary_tag_id,
            is_active=True,
        ),
        synced_primary_tag_id=synced_primary_tag_id,
    )


def _patch_common_repos(monkeypatch, *, new_subject, previous):
    async def fake_get_image(session, image_id):
        _ = session
        return SimpleNamespace(id=image_id)

    async def fake_get_subject(session, subject_id):
        _ = session, subject_id
        return new_subject

    async def fake_get_primary(session, image_id):
        _ = session, image_id
        return previous

    monkeypatch.setattr(f"{SERVICE_MODULE}.image_repository.get_by_id", fake_get_image)
    monkeypatch.setattr(f"{SERVICE_MODULE}.image_repository.get_by_id_for_update", fake_get_image)
    monkeypatch.setattr(f"{SERVICE_MODULE}.subject_repository.get_by_id", fake_get_subject)
    monkeypatch.setattr(f"{SERVICE_MODULE}.image_subject_repository.get_primary", fake_get_primary)


@pytest.mark.asyncio
async def test_assign_auto_does_not_override_manual(monkeypatch) -> None:
    """自动结果不得覆盖人工确认的主体。"""
    service = SubjectAssignmentService()
    new_subject = SimpleNamespace(id=2, name="新主体", is_active=True, primary_tag_id=22)
    previous = _make_previous(subject_id=1, source="manual", primary_tag_id=11)
    _patch_common_repos(monkeypatch, new_subject=new_subject, previous=previous)

    async def fail_set_primary(session, **kwargs):
        raise AssertionError("auto 不应覆盖 manual 主体")

    monkeypatch.setattr(
        f"{SERVICE_MODULE}.image_subject_repository.set_primary_subject",
        fail_set_primary,
    )

    result = await service.assign_primary_subject(
        session=SimpleNamespace(flush=lambda: _async_none()),
        image_id=1,
        subject_id=2,
        actor_id=None,
        source="auto",
    )

    assert result["changed"] is False
    assert result["subject_id"] == 1
    assert result["source"] == "manual"


@pytest.mark.asyncio
async def test_assign_manual_syncs_tags_and_sample(monkeypatch) -> None:
    """人工纠正应移除旧主体标签、挂接新主体标签，并登记引用样本。"""
    service = SubjectAssignmentService()
    new_subject = SimpleNamespace(id=2, name="新主体", is_active=True, primary_tag_id=22)
    previous = _make_previous(
        subject_id=1,
        source="auto",
        primary_tag_id=11,
        synced_primary_tag_id=11,
    )
    _patch_common_repos(monkeypatch, new_subject=new_subject, previous=previous)

    calls: dict = {"set": [], "removed": [], "added": [], "samples": []}

    async def fake_set_primary(session, **kwargs):
        _ = session
        calls["set"].append(kwargs)
        return SimpleNamespace(
            confidence=kwargs["confidence"],
            source=kwargs["source"],
            state=kwargs["state"],
            is_primary=True,
        )

    async def fake_remove_tag(session, image_id, tag_id):
        _ = session, image_id
        calls["removed"].append(tag_id)
        return True

    async def fake_get_image_tag(session, image_id, tag_id):
        _ = session, image_id, tag_id
        return None

    async def fake_add_tag(session, image_id, tag_id, *, source="ai", sort_order=99, added_by=None):
        _ = session, image_id, sort_order, added_by
        calls["added"].append((tag_id, source))
        return SimpleNamespace()

    async def fake_create_sample(session, **kwargs):
        _ = session
        calls["samples"].append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(
        f"{SERVICE_MODULE}.image_subject_repository.set_primary_subject", fake_set_primary
    )
    monkeypatch.setattr(
        f"{SERVICE_MODULE}.image_tag_repository.remove_tag_from_image", fake_remove_tag
    )
    monkeypatch.setattr(f"{SERVICE_MODULE}.image_tag_repository.get_image_tag", fake_get_image_tag)
    monkeypatch.setattr(f"{SERVICE_MODULE}.image_tag_repository.add_tag_to_image", fake_add_tag)
    monkeypatch.setattr(
        f"{SERVICE_MODULE}.subject_sample_repository.create_sample", fake_create_sample
    )

    result = await service.assign_primary_subject(
        session=SimpleNamespace(flush=lambda: _async_none()),
        image_id=5,
        subject_id=2,
        actor_id=7,
        source="manual",
        add_sample=True,
        comment="纠正",
    )

    assert result["changed"] is True
    assert result["subject_id"] == 2
    assert calls["removed"] == [11]
    assert calls["added"] == [(22, "user")]
    sample = calls["samples"][0]
    assert sample["embedding"] is None
    assert sample["embedding_model"] == "reference"
    assert sample["image_id"] == 5


@pytest.mark.asyncio
async def test_switch_subject_keeps_preexisting_user_tag(monkeypatch) -> None:
    """旧主体标签并非主体流程添加时，切换主体不得删除该用户标签。"""
    service = SubjectAssignmentService()
    new_subject = SimpleNamespace(id=2, name="新主体", is_active=True, primary_tag_id=22)
    previous = _make_previous(subject_id=1, source="manual", primary_tag_id=11)
    _patch_common_repos(monkeypatch, new_subject=new_subject, previous=previous)

    removed: list[int] = []

    async def fake_set_primary(session, **kwargs):
        _ = session
        return SimpleNamespace(
            confidence=kwargs["confidence"],
            source=kwargs["source"],
            state=kwargs["state"],
            is_primary=True,
            synced_primary_tag_id=None,
        )

    async def fake_remove_tag(session, image_id, tag_id):
        _ = session, image_id
        removed.append(tag_id)

    async def fake_get_image_tag(session, image_id, tag_id):
        _ = session, image_id, tag_id
        return SimpleNamespace(source="user")

    monkeypatch.setattr(
        f"{SERVICE_MODULE}.image_subject_repository.set_primary_subject", fake_set_primary
    )
    monkeypatch.setattr(
        f"{SERVICE_MODULE}.image_tag_repository.remove_tag_from_image", fake_remove_tag
    )
    monkeypatch.setattr(f"{SERVICE_MODULE}.image_tag_repository.get_image_tag", fake_get_image_tag)

    await service.assign_primary_subject(
        session=SimpleNamespace(flush=lambda: _async_none()),
        image_id=5,
        subject_id=2,
        actor_id=7,
        source="manual",
    )

    assert removed == []


@pytest.mark.asyncio
async def test_create_subject_suggestion_dedup(monkeypatch) -> None:
    """同图片已有 pending 主体建议时应拒绝重复提审。"""
    service = SubjectAssignmentService()
    new_subject = SimpleNamespace(id=2, name="新主体", is_active=True, primary_tag_id=22)
    _patch_common_repos(monkeypatch, new_subject=new_subject, previous=None)

    async def fake_has_pending(session, *, type_, target_id):
        _ = session, type_, target_id
        return True

    monkeypatch.setattr(
        f"{SERVICE_MODULE}.approval_repository.has_pending_of_type", fake_has_pending
    )

    with pytest.raises(ValueError, match="待审批"):
        await service.create_subject_suggestion(
            session=None,  # type: ignore[arg-type]
            image_id=1,
            requester_id=9,
            subject_id=2,
        )


async def _async_none() -> None:
    return None


@pytest.mark.asyncio
async def test_create_subject_suggestion_maps_unique_conflict_to_business_error(monkeypatch) -> None:
    """数据库唯一索引在并发冲突时应返回可读业务错误。"""
    service = SubjectAssignmentService()
    new_subject = SimpleNamespace(id=2, name="新主体", is_active=True, primary_tag_id=22)
    _patch_common_repos(monkeypatch, new_subject=new_subject, previous=None)

    async def fake_has_pending(session, *, type_, target_id):
        _ = session, type_, target_id
        return False

    async def fake_create(session, **kwargs):
        _ = session, kwargs
        raise IntegrityError("insert approval", {}, RuntimeError("duplicate key"))

    class NestedTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeSession:
        def begin_nested(self):
            return NestedTransaction()

    monkeypatch.setattr(
        f"{SERVICE_MODULE}.approval_repository.has_pending_of_type", fake_has_pending
    )
    monkeypatch.setattr(f"{SERVICE_MODULE}.approval_repository.create", fake_create)

    with pytest.raises(ValueError, match="已有待审批"):
        await service.create_subject_suggestion(
            session=FakeSession(),  # type: ignore[arg-type]
            image_id=1,
            requester_id=9,
            subject_id=2,
        )


@pytest.mark.asyncio
async def test_apply_subject_suggestion_missing_image_id() -> None:
    service = SubjectAssignmentService()
    approval = DummyApproval(
        payload={
            "proposed_subject": {"subject_id": 1},
        },
        requester_id=100,
    )

    with pytest.raises(ValueError, match="image_id"):
        await service.apply_subject_suggestion(session=None, approval=approval)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_apply_subject_suggestion_calls_assign(monkeypatch) -> None:
    service = SubjectAssignmentService()
    approval = DummyApproval(
        payload={
            "image_id": 88,
            "proposed_subject": {"subject_id": 9},
            "confidence": 0.77,
            "comment": "管理员通过",
            "add_sample": True,
        },
        requester_id=12,
    )

    captured: dict = {}

    async def fake_assign_primary_subject(session, **kwargs):
        _ = session
        captured.update(kwargs)
        return {
            "subject_id": kwargs["subject_id"],
            "is_primary": True,
        }

    monkeypatch.setattr(service, "assign_primary_subject", fake_assign_primary_subject)

    image_id = await service.apply_subject_suggestion(session=None, approval=approval)  # type: ignore[arg-type]

    assert image_id == 88
    assert captured["image_id"] == 88
    assert captured["subject_id"] == 9
    assert captured["actor_id"] == 12
    assert captured["confidence"] == 0.77
    assert captured["source"] == "approval"
    assert captured["state"] == "confirmed"
    assert captured["add_sample"] is True
    assert captured["comment"] == "管理员通过"
