"""主体上下文、定义发布、版本对比与三条历史保留。"""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import importlib
import json

from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
import httpx
import pytest

from imgtag.api.endpoints import subjects as subject_api
from imgtag.db.repositories import image_subject_repository, subject_repository, task_repository
from imgtag.db.repositories.subject_definition import SubjectDefinitionRepository, subject_definition_repository, subject_template_repository
from imgtag.models.subject import SubjectDefinitionVersion
from imgtag.schemas.subject import SubjectExtractionRequest
from imgtag.services.subject_analysis_service import review_subject_analysis
from imgtag.services.subject_context_service import subject_context_service
from imgtag.services.subject_extraction_service import identity_snapshot, subject_extraction_service
from imgtag.services.vision_service import ImageAnalysisResult, VisionService


CONTEXTS = [
    {"subject_id": 1, "name": "菲比", "aliases": ["Phoebe", "鸣潮菲比"], "status": "confirmed", "version": "v1"},
    {"subject_id": 2, "name": "糯糯", "aliases": [], "status": "confirmed", "version": "v1"},
]


def test_multiple_instances_keep_one_identity_tag():
    analysis = ImageAnalysisResult(tags=["菲比", "Phoebe", "鸣潮菲比表情包", "游泳", "糯糯"], description="多个菲比与糯糯",
        subject_checks=[{"subject_id": 1, "status": "supported", "evidence": "可见金发紫眼和蓝色发饰组合"}, {"subject_id": 2, "status": "supported", "evidence": "灰蓝发与红白衣装组合"}],
        subject_observations=[{"subject_id": 1, "position": "前景", "appearance": "金发紫眼，套着泳圈", "multiple": True},
                              {"subject_id": 1, "position": "后排", "appearance": "戴着泳镜"},
                              {"subject_id": 2, "position": "左侧", "appearance": "灰蓝发"}])
    report = review_subject_analysis(analysis, CONTEXTS)
    assert analysis.tags == ["游泳", "菲比", "糯糯"]
    assert len(report["observations"]) == 3
    assert report["observations"][0]["multiple"]


@pytest.mark.parametrize("status", ["conflict", "uncertain"])
def test_wrong_association_does_not_force_identity_or_mutate_user_link(status):
    contexts = deepcopy(CONTEXTS[:1])
    contexts[0]["status"] = "candidate"
    analysis = ImageAnalysisResult(tags=["菲比", "Phoebe", "皱眉"], description="菲比的粉发形象",
        subject_checks=[{"subject_id": 1, "status": status, "evidence": "画面粉发，身份线索不足"}],
        subject_observations=[{"position": "中央", "appearance": "粉发紫眼的角色皱眉"}])
    report = review_subject_analysis(analysis, contexts)
    assert "菲比" not in analysis.description
    assert analysis.tags == ["皱眉"]
    assert report["checks"][0]["status"] == status
    assert contexts[0]["status"] == "candidate"


def test_unchecked_context_is_uncertain_and_unknown_ids_are_rejected():
    a = ImageAnalysisResult(tags=["菲比"], description="菲比")
    report = review_subject_analysis(a, [{**CONTEXTS[0], "status": "candidate"}])
    assert report["checks"][0]["status"] == "uncertain"
    assert "菲比" not in a.description and not a.tags
    a.subject_checks = [{"subject_id": 99, "status": "supported"}]
    with pytest.raises(ValueError, match="未知"):
        review_subject_analysis(a, CONTEXTS[:1])


async def test_current_associations_and_tag_candidates_merge_without_alias_duplicates(monkeypatch):
    one = SimpleNamespace(id=1, name="菲比", aliases=["Phoebe"], description="金发紫眼", is_active=True,
                          updated_at="v1", definition_revision=2, primary_tag_id=10, alias_tag_ids=[11])
    two = SimpleNamespace(id=2, name="糯糯", aliases=[], description="灰蓝发", is_active=True,
                          updated_at="v1", definition_revision=1, primary_tag_id=20, alias_tag_ids=[])
    monkeypatch.setattr(image_subject_repository, "get_current", AsyncMock(return_value=[
        SimpleNamespace(subject_id=1, subject=one, state="confirmed", source="manual", updated_at="v1")]))
    monkeypatch.setattr("imgtag.services.subject_context_service.image_repository.get_image_tags_with_source",
                        AsyncMock(return_value=[{"id": 11, "level": 2, "source": "ai"}, {"id": 20, "level": 2, "source": "ai"}]))
    monkeypatch.setattr(subject_repository, "list_matching_tags", AsyncMock(return_value=[one, two]))
    result = await subject_context_service.resolve(None, 10)
    assert [(c["subject_id"], c["status"]) for c in result] == [(1, "confirmed"), (2, "candidate")]


def extraction_result():
    return {"analysis_context": "金发紫眼，服饰可能简化", "distinguishing_features": [
        {"feature": "金发", "image_ids": [10], "scope": "单图可见"}],
        "observed_variations": [], "confusions": [], "unresolved": [], "proposed_changes": []}


def test_extraction_rejects_negative_or_unknown_evidence():
    samples = [{"image_id": 10, "role": "positive"}, {"image_id": 20, "role": "negative"}]
    r = extraction_result()
    subject_extraction_service.validate_result(r, samples)
    for wrong in [20, 99]:
        r["distinguishing_features"][0]["image_ids"] = [wrong]
        with pytest.raises(ValueError, match="反例"):
            subject_extraction_service.validate_result(r, samples)


def make_subject(revision=2):
    return SimpleNamespace(id=1, name="菲比", aliases=["Phoebe"], description="旧定义",
                          is_active=True, definition_revision=revision, primary_tag_id=100)


async def test_input_snapshot_keeps_template_edits_separate_from_identity(monkeypatch):
    monkeypatch.setattr("imgtag.services.subject_extraction_service.config_repository.get_value", AsyncMock(return_value=None))
    subject = make_subject()
    monkeypatch.setattr(subject_repository, "eligible_reference_ids", AsyncMock(return_value={10}))
    template = SimpleNamespace(id=5, name="角色", content="模板原文", is_active=True, updated_at="v1")
    monkeypatch.setattr(subject_repository, "get_by_id", AsyncMock(return_value=subject))
    monkeypatch.setattr(subject_template_repository, "get_by_id", AsyncMock(return_value=template))
    monkeypatch.setattr("imgtag.services.subject_extraction_service.image_repository.get_by_id",
                        AsyncMock(return_value=SimpleNamespace(file_type="png", file_hash="hash")))
    request = SubjectExtractionRequest(samples=[{"image_id": 10, "role": "positive"}],
        rules=[{"template_id": 5, "text": "本次编辑"}], custom_supplement="比较发饰", identity_background="用户确认鸣潮")
    snapshot = await subject_extraction_service.build_input(None, 1, request)
    template.content = "日后修改"
    assert snapshot["rules"][0]["template_content"] == "模板原文"
    assert snapshot["rules"][0]["text"] == "本次编辑"
    assert "比较发饰" in snapshot["prompt"] and "用户确认鸣潮" in snapshot["prompt"]
    assert "分类" not in snapshot["subject"]["description"]


async def test_multi_replace_removes_only_workflow_owned_tags(monkeypatch):
    from imgtag.services.subject_assignment_service import subject_assignment_service
    image = SimpleNamespace(subject_analysis={"old": True}, subject_selection_explicit=False)
    previous = [SimpleNamespace(subject_id=1, synced_primary_tag_id=10),
                SimpleNamespace(subject_id=2, synced_primary_tag_id=None)]
    new = SimpleNamespace(id=3, primary_tag_id=30, name="新角色", is_active=True)
    row = SimpleNamespace(subject_id=3, confidence=None, source="manual", state="confirmed", is_primary=True)
    monkeypatch.setattr("imgtag.services.subject_assignment_service.image_repository.get_by_id_for_update", AsyncMock(return_value=image))
    monkeypatch.setattr(subject_repository, "get_by_id", AsyncMock(return_value=new))
    monkeypatch.setattr(image_subject_repository, "get_current", AsyncMock(return_value=previous))
    replace = AsyncMock(return_value=[row])
    monkeypatch.setattr(image_subject_repository, "replace_current", replace)
    remove = AsyncMock()
    monkeypatch.setattr("imgtag.services.subject_assignment_service.image_tag_repository.remove_tag_from_image", remove)
    monkeypatch.setattr(subject_assignment_service, "_sync_primary_tag", AsyncMock(return_value=True))
    session = SimpleNamespace(flush=AsyncMock())
    await subject_assignment_service.assign_subjects(session, image_id=7, subject_ids=[3, 3], primary_id=3, actor_id=9)
    remove.assert_awaited_once_with(session, 7, 10)
    assert replace.await_args.args[2] == [3]
    assert row.synced_primary_tag_id == 30
    assert image.subject_selection_explicit is True and image.subject_analysis is None


async def test_explicit_clear_does_not_reconfirm_preserved_user_alias(monkeypatch):
    subject = SimpleNamespace(id=1, name="菲比", aliases=[], description="角色", is_active=True,
                             updated_at="v1", primary_tag_id=10, alias_tag_ids=[])
    monkeypatch.setattr(image_subject_repository, "get_current", AsyncMock(return_value=[]))
    monkeypatch.setattr(image_subject_repository, "has_explicit_selection", AsyncMock(return_value=True))
    monkeypatch.setattr("imgtag.services.subject_context_service.image_repository.get_image_tags_with_source",
                        AsyncMock(return_value=[{"id": 10, "source": "user", "level": 2}]))
    monkeypatch.setattr(subject_repository, "list_matching_tags", AsyncMock(return_value=[subject]))
    assign = AsyncMock()
    monkeypatch.setattr("imgtag.services.subject_context_service.subject_assignment_service.assign_primary_subject", assign)
    contexts = await subject_context_service.resolve(None, 10, assign_from_tags=True)
    assert contexts[0]["status"] == "candidate"
    assign.assert_not_awaited()


async def test_multimodal_extraction_logs_text_and_labels_before_sending(monkeypatch, caplog):
    service = VisionService()
    monkeypatch.setattr(service, "_get_api_config", AsyncMock(return_value=("https://vision.test/v1", "secret-test-only", "test-model")))
    monkeypatch.setattr(service, "_compress_image", lambda data, size: (data, "image/jpeg"))
    requests = []
    observer = AsyncMock()
    def respond(request):
        assert observer.await_count == 1
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(extraction_result(), ensure_ascii=False)}}]})
    original_client = httpx.AsyncClient
    module = importlib.import_module("imgtag.services.vision_service")
    monkeypatch.setattr(module.httpx, "AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    samples = [{"data": b"image", "sha256": "hash", "label": {"image_id": 10, "role": "positive", "target": "左侧"}}]
    result, metadata = await service.extract_subject("独立的提炼规则与用户本次补充", samples, observer=observer)
    content = requests[0]["messages"][0]["content"]
    assert content[0]["text"] == "独立的提炼规则与用户本次补充"
    assert json.loads(content[1]["text"])["target"] == "左侧"
    assert content[2]["type"] == "image_url"
    assert "secret-test-only" not in json.dumps(metadata)
    logged = next(row.getMessage() for row in caplog.records if row.msg == "主体提炼输入: %s")
    assert "独立的提炼规则" in logged and "data:image" not in logged
    assert "secret-test-only" not in logged
    assert result["analysis_context"] == extraction_result()["analysis_context"]


async def test_recovered_extraction_returns_applied_result_without_model_call(monkeypatch):
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
    monkeypatch.setattr("imgtag.services.subject_extraction_service.async_session_maker", Session)
    monkeypatch.setattr(task_repository, "get_by_id", AsyncMock(return_value=SimpleNamespace(result={"subject_id": 1, "applied": True})))
    model = AsyncMock()
    monkeypatch.setattr("imgtag.services.subject_extraction_service.vision_service.extract_subject", model)
    result = await subject_extraction_service.process("recovered", {"snapshot": {}})
    assert result == {"subject_id": 1, "applied": True}
    model.assert_not_awaited()


async def test_template_routes_and_extraction_require_admin(monkeypatch):
    from fastapi import FastAPI
    from imgtag.api.endpoints.auth import get_current_user
    from imgtag.api.endpoints.subjects import router
    from imgtag.db import get_async_session
    app = FastAPI()
    app.include_router(router, prefix="/subjects")
    user = {"id": 1, "role": "admin", "permissions": 15}
    app.dependency_overrides[get_current_user] = lambda: user
    async def session(): yield SimpleNamespace()
    app.dependency_overrides[get_async_session] = session
    monkeypatch.setattr(subject_template_repository, "list_templates", AsyncMock(return_value=[]))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get('/subjects/templates')).status_code == 200
        user['role'] = 'user'
        assert (await client.get('/subjects/templates')).status_code == 403
        response = await client.post('/subjects/1/extract', json={"samples": [{"image_id": 1, "role": "positive"}]})
        assert response.status_code == 403


async def test_multiple_subject_write_allows_owner_but_checks_ai_permission(monkeypatch):
    from fastapi import FastAPI
    from imgtag.api.endpoints.auth import get_current_user
    from imgtag.api.endpoints.images import router
    from imgtag.db import get_async_session
    from imgtag.services.subject_assignment_service import subject_assignment_service
    from imgtag.services.task_queue import task_queue
    app = FastAPI()
    app.include_router(router, prefix="/images")
    user = {"id": 3, "role": "user", "permissions": 0}
    image = SimpleNamespace(uploaded_by=9)
    app.dependency_overrides[get_current_user] = lambda: user
    fake_session = SimpleNamespace()
    async def session(): yield fake_session
    app.dependency_overrides[get_async_session] = session
    monkeypatch.setattr("imgtag.api.endpoints.images.image_repository.get_by_id", AsyncMock(return_value=image))
    assign = AsyncMock(return_value=[])
    monkeypatch.setattr(subject_assignment_service, "assign_subjects", assign)
    enqueue = AsyncMock(return_value=1)
    monkeypatch.setattr(task_queue, "add_tasks", enqueue)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.put('/images/1/subjects', json={"subject_ids": [1, 2], "reanalyze": False})).status_code == 403
        image.uploaded_by = 3
        assert (await client.put('/images/1/subjects', json={"subject_ids": [1, 2]})).status_code == 403
        assert (await client.put('/images/1/subjects', json={"subject_ids": [1, 2], "reanalyze": False})).status_code == 200
        user['role'] = 'admin'
        assert (await client.put('/images/1/subjects', json={"subject_ids": [1, 2], "reanalyze": False})).status_code == 200
    assert assign.await_count == 2
    assert enqueue.await_args.kwargs['session'] is fake_session
    assert enqueue.await_args.kwargs['task_type'] == 'rebuild_vector'


async def test_extraction_task_logs_are_admin_only(monkeypatch):
    from imgtag.api.endpoints import tasks
    listing = AsyncMock(return_value={"tasks": [], "total": 0})
    monkeypatch.setattr(tasks.task_service, "get_tasks", listing)
    await tasks.get_tasks(page=1, size=50, status=None, user={"id": 3, "role": "user"})
    assert listing.await_args.kwargs['user'] == {'id': 3, 'role': 'user'}
    monkeypatch.setattr(tasks.task_service, "get_task", AsyncMock(return_value={"type": "extract_subject", "payload": {"snapshot": "private"}}))
    with pytest.raises(HTTPException) as e:
        await tasks.get_task('extract-task', user={"role": "user"})
    assert e.value.status_code == 403
    assert (await tasks.get_task('extract-task', user={"role": "admin"}))['type'] == 'extract_subject'


class LocalAsyncSession:
    """小数据测试适配器；生产实现仍使用 AsyncSession。"""

    def __init__(self, session):
        self.sync = session

    def add(self, row):
        self.sync.add(row)

    async def flush(self):
        self.sync.flush()

    async def refresh(self, row):
        self.sync.refresh(row)

    async def delete(self, row):
        self.sync.delete(row)

    async def execute(self, statement):
        return self.sync.execute(statement)


@pytest.fixture
def local_session():
    engine = create_engine("sqlite://")
    with Session(engine, expire_on_commit=False) as session:
        # 只建本次测试的表，避免依赖 PostgreSQL 的向量、ARRAY 等类型。
        session.execute(text("""CREATE TABLE subject_definition_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id INTEGER NOT NULL,
            state TEXT NOT NULL, definition TEXT NOT NULL, recognition_notes TEXT NOT NULL DEFAULT '',
            edit_revision INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL, input_snapshot TEXT NOT NULL,
            base_revision INTEGER NOT NULL, published_revision INTEGER, created_by INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, published_at DATETIME
        )"""))
        session.commit()
        yield LocalAsyncSession(session)
    engine.dispose()


def seed(session, count, subject_id=1):
    rows = []
    for i in range(count):
        row = SubjectDefinitionVersion(
            subject_id=subject_id, state="history",
            definition=f"定义{i}", payload={}, input_snapshot={}, base_revision=0,
            published_revision=i if i % 2 else None,
            # 同一时间生成也应稳定按版本ID保留最近记录。
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session.sync.add(row)
        rows.append(row)
    session.sync.flush()
    return rows


def retained_ids(session, subject_id=1):
    return session.sync.execute(select(SubjectDefinitionVersion.id)
        .where(SubjectDefinitionVersion.subject_id == subject_id)
        .order_by(SubjectDefinitionVersion.id)).scalars().all()


@pytest.mark.parametrize("count", [0, 1, 3, 4, 8])
async def test_three_backups_do_not_affect_other_subjects(local_session, count):
    rows = seed(local_session, count)
    other = seed(local_session, 5, subject_id=2)
    await SubjectDefinitionRepository().prune_history(local_session, 1)
    assert retained_ids(local_session) == [row.id for row in rows[-3:]]
    assert retained_ids(local_session, 2) == [row.id for row in other]


@pytest.mark.parametrize("state", ["history"])
async def test_new_backup_prunes_oldest(local_session, state):
    old = seed(local_session, 3)
    row = await SubjectDefinitionRepository().create(local_session, subject_id=1,
        state=state, definition="新内容", payload={}, input_snapshot={}, base_revision=0)
    assert retained_ids(local_session) == [old[1].id, old[2].id, row.id]


async def test_listing_prunes_existing_excess_and_cannot_page_into_deleted_versions(local_session, monkeypatch):
    rows = seed(local_session, 7)
    repo = SubjectDefinitionRepository()
    monkeypatch.setattr(repo, "lock_subject", AsyncMock(return_value=SimpleNamespace(id=1)))
    result = await repo.list_versions(local_session, 1)
    assert [row.id for row in result] == [row.id for row in reversed(rows[-3:])]
    assert await repo.list_versions(local_session, 1, offset=3) == []
    assert retained_ids(local_session) == [row.id for row in rows[-3:]]


async def test_cleanup_rolls_back_with_enclosing_transaction(local_session):
    rows = seed(local_session, 6)
    local_session.sync.commit()
    await SubjectDefinitionRepository().prune_history(local_session, 1)
    assert len(retained_ids(local_session)) == 3
    local_session.sync.rollback()
    assert retained_ids(local_session) == [row.id for row in rows]




async def test_subject_keeps_current_plus_three_previous_definitions(local_session, monkeypatch):
    from imgtag.schemas.subject import SaveSubjectContent
    subject = SimpleNamespace(id=1, name='菲比', aliases=[], description='定义0', recognition_notes='备注0',
                              definition_revision=1, is_active=True)
    monkeypatch.setattr(subject_definition_repository, 'lock_subject', AsyncMock(return_value=subject))
    for i in range(1, 6):
        await subject_extraction_service.save_current(local_session, 1,
            SaveSubjectContent(definition=f'定义{i}', recognition_notes=f'备注{i}', expected_revision=i), 1)
    rows = await subject_definition_repository.list_versions(local_session, 1)
    assert subject.description == '定义5' and subject.recognition_notes == '备注5'
    assert [r.definition for r in rows] == ['定义4', '定义3', '定义2']
    assert [r.recognition_notes for r in rows] == ['备注4', '备注3', '备注2']
    assert all(r.state == 'history' for r in rows)


@pytest.mark.parametrize('current_description', ['当前描述', ''])
async def test_restore_oldest_subject_backup_survives_pruning_and_saves_current(local_session, monkeypatch, current_description):
    rows = seed(local_session, 3)
    subject = SimpleNamespace(id=1, name='菲比', aliases=[], description=current_description, recognition_notes='',
                              definition_revision=7, is_active=True)
    oldest_id = rows[0].id
    rows[0].recognition_notes = '旧识别备注'
    monkeypatch.setattr(subject_definition_repository, 'lock_subject', AsyncMock(return_value=subject))
    await subject_extraction_service.restore(local_session, 1, oldest_id, 7, None)
    assert subject.description == '定义0' and subject.recognition_notes == '旧识别备注'
    assert subject.definition_revision == 8
    history = await subject_definition_repository.list_versions(local_session, 1)
    assert len(history) == 3 and oldest_id not in [row.id for row in history]
    assert history[0].definition == current_description and history[0].recognition_notes == ''
    assert [row.definition for row in history[1:]] == ['定义2', '定义1']


@pytest.mark.parametrize('failure', ['stale', 'missing', 'other_subject'])
async def test_subject_restore_rejects_stale_missing_or_foreign_backups(local_session, monkeypatch, failure):
    rows = seed(local_session, 1, subject_id=2 if failure == 'other_subject' else 1)
    subject = SimpleNamespace(id=1, definition_revision=7, description='当前')
    monkeypatch.setattr(subject_definition_repository, 'lock_subject', AsyncMock(return_value=subject))
    before = retained_ids(local_session)
    with pytest.raises(HTTPException) as error:
        await subject_extraction_service.restore(local_session, 1, 999 if failure == 'missing' else rows[0].id,
                                                 6 if failure == 'stale' else 7, None)
    assert error.value.status_code == (409 if failure == 'stale' else 404)
    assert subject.description == '当前' and subject.definition_revision == 7
    assert retained_ids(local_session) == before


async def test_delete_subject_history_only_removes_selected_backup(local_session, monkeypatch):
    rows = seed(local_session, 3)
    other = seed(local_session, 1, subject_id=2)
    subject = SimpleNamespace(id=1, description='当前描述', recognition_notes='当前备注', definition_revision=7)
    monkeypatch.setattr(subject_definition_repository, 'lock_subject', AsyncMock(return_value=subject))
    await subject_extraction_service.delete_history(local_session, 1, rows[1].id)
    assert retained_ids(local_session) == [rows[0].id, rows[2].id]
    assert retained_ids(local_session, 2) == [other[0].id]
    assert subject.description == '当前描述' and subject.recognition_notes == '当前备注' and subject.definition_revision == 7
    for version_id in [rows[1].id, other[0].id]:
        with pytest.raises(HTTPException) as error:
            await subject_extraction_service.delete_history(local_session, 1, version_id)
        assert error.value.status_code == 404
    assert retained_ids(local_session) == [rows[0].id, rows[2].id]
