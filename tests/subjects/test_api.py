"""主体接口：权限、参考图库与批量重分析确认。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
import httpx
import pytest

from imgtag.api.endpoints import images, subjects, subjects as api, tasks as task_api
from imgtag.api.endpoints.auth import get_current_user
from imgtag.db import get_async_session
from imgtag.db.repositories import subject_repository
from imgtag.services.subject_gallery_service import subject_gallery_service as gallery


OPERATIONS = [
    ("GET", "/subjects/", None),
    ("GET", "/subjects/1", None),
    ("POST", "/subjects/", {"category_tag_id": 1, "primary_tag_id": 2}),
    ("PATCH", "/subjects/1", {"description": "定义"}),
    ("GET", "/subjects/extraction-settings", None),
    ("GET", "/subjects/templates", None),
    ("POST", "/subjects/templates", {"name": "规则", "content": "提炼共同特征"}),
    ("PATCH", "/subjects/templates/1", {"name": "规则", "content": "提炼共同特征"}),
    ("POST", "/subjects/1/extract/preview", {"samples": [{"image_id": 1}]}),
    ("POST", "/subjects/1/extract", {"samples": [{"image_id": 1}]}),
    ("GET", "/subjects/1/extract/task", None),
    ("GET", "/subjects/1/versions", None),
    ("DELETE", "/subjects/1/versions/1", None),
    ("POST", "/subjects/1/versions/1/restore", {"expected_revision": 0}),
    ("PUT", "/subjects/1/definition/current", {"definition": "定义", "expected_revision": 0}),
    ("GET", "/subjects/1/reanalyze", None),
    ("POST", "/subjects/1/reanalyze", None),
    ("PUT", "/images/1/subjects", {"subject_ids": [1], "primary_subject_id": 1}),
    ("PUT", "/images/1/subjects/primary", {"subject_id": 1}),
    ("POST", "/images/1/subjects/suggest", {"subject_id": 1}),
]


def make_app():
    app = FastAPI()
    app.include_router(subjects.router, prefix="/subjects")
    app.include_router(images.router, prefix="/images")
    app.dependency_overrides[get_async_session] = lambda: None
    return app


@pytest.mark.parametrize("method,path,payload", OPERATIONS)
@pytest.mark.parametrize("identity", ["anonymous", "owner", "full_permission_user"])
async def test_all_subject_operations_reject_non_admin_before_data_access(monkeypatch, method, path, payload, identity):
    app = make_app()
    # 图片属于 id=1；普通用户拥有全部权限位也不等于管理员角色。
    if identity != "anonymous":
        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1 if identity == "owner" else 2,
            "role": "user", "permissions": 15,
        }
    read_image = AsyncMock(side_effect=AssertionError("鉴权应早于数据读取"))
    enqueue = AsyncMock(side_effect=AssertionError("无权请求不得创建提炼任务"))
    monkeypatch.setattr(images.image_repository, "get_by_id", read_image)
    monkeypatch.setattr(subjects.subject_extraction_service, "enqueue", enqueue)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, json=payload)
    assert response.status_code == (401 if identity == "anonymous" else 403), response.text
    read_image.assert_not_awaited()
    enqueue.assert_not_awaited()


async def test_admin_can_assign_subjects_to_another_users_image(monkeypatch):
    app = make_app()
    app.dependency_overrides[get_current_user] = lambda: {"id": 9, "role": "admin", "permissions": 0}
    monkeypatch.setattr(images.image_repository, "get_by_id", AsyncMock(return_value=SimpleNamespace(id=1, uploaded_by=1)))
    assign = AsyncMock(return_value=[{"subject_id": 1, "subject_name": "菲比"}])
    queued = AsyncMock(return_value=1)
    monkeypatch.setattr(images.subject_assignment_service, "assign_subjects", assign)
    monkeypatch.setattr(images.task_queue, "add_tasks", queued)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put("/images/1/subjects", json={"subject_ids": [1], "primary_subject_id": 1, "reanalyze": True})
    assert response.status_code == 200, response.text
    assert response.json()["assignments"][0]["subject_name"] == "菲比"
    assert assign.await_args.kwargs["actor_id"] == 9
    assert queued.await_args.kwargs["force_analyze"] is True


async def test_readonly_image_result_keeps_subject_names(monkeypatch):
    app = make_app()
    image = SimpleNamespace(
        id=1, file_hash="example", file_type="png", file_size=100, width=100, height=100,
        original_url=None, description="菲比的表情包", is_public=True, created_at=None,
        updated_at=None, uploaded_by=1, uploader=None,
    )
    monkeypatch.setattr(images.image_repository, "get_with_tags", AsyncMock(return_value=image))
    monkeypatch.setattr(images.image_repository, "get_image_tags_with_source", AsyncMock(return_value=[]))
    monkeypatch.setattr(images, "_get_display_url", AsyncMock(return_value="https://example.com/sample.png"))
    monkeypatch.setattr(images.image_subject_repository, "list_by_image_ids", AsyncMock(return_value={
        1: [{"subject_id": 1, "subject_name": "菲比", "is_primary": True}],
    }))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/images/1")
    assert response.status_code == 200, response.text
    assert response.json()["subjects"][0]["subject_name"] == "菲比"


@pytest.fixture
def setup_api(monkeypatch):
    app = FastAPI()
    app.include_router(api.router, prefix='/subjects')
    user = {'id': 1, 'role': 'admin'}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_async_session] = lambda: None
    monkeypatch.setattr(subject_repository, 'get_by_id', AsyncMock(return_value=SimpleNamespace(id=7, is_active=True)))
    count = AsyncMock(return_value={7: 42})
    images = AsyncMock(return_value=list(range(1, 43)))
    enqueue = AsyncMock(return_value={'added': 40, 'upgraded': 1, 'existing': 1})
    monkeypatch.setattr(subject_repository, 'count_current_images', count)
    monkeypatch.setattr(subject_repository, 'list_image_ids', images)
    monkeypatch.setattr(api.task_queue, 'enqueue_tasks', enqueue)
    return app, user, count, images, enqueue


async def test_preview_reports_current_association_count_without_enqueuing(setup_api):
    app, _, count, images, enqueue = setup_api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/subjects/7/reanalyze')
    assert response.status_code == 200 and response.json() == {'count': 42, 'is_active': True}
    count.assert_awaited_once_with(None, [7])
    images.assert_not_awaited()
    enqueue.assert_not_awaited()


@pytest.mark.parametrize('confirmed', [41, 43])
async def test_changed_association_count_requires_new_confirmation_before_any_task(setup_api, confirmed):
    app, _, _, _, enqueue = setup_api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post(f'/subjects/7/reanalyze?expected_count={confirmed}')
    assert response.status_code == 409 and '当前42张' in response.json()['detail']
    enqueue.assert_not_awaited()


async def test_matching_count_enqueues_exact_current_ids_and_returns_actual_task_counts(setup_api):
    app, _, _, _, enqueue = setup_api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/subjects/7/reanalyze?expected_count=42')
    assert response.status_code == 200 and response.json() == {'added': 40, 'upgraded': 1, 'existing': 1}
    enqueue.assert_awaited_once_with(list(range(1, 43)), force_analyze=True)


async def test_ordinary_user_cannot_preview_or_submit_batch_reanalysis(setup_api):
    app, user, count, images, enqueue = setup_api
    user['role'] = 'user'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/subjects/7/reanalyze')).status_code == 403
        assert (await client.post('/subjects/7/reanalyze?expected_count=42')).status_code == 403
    count.assert_not_awaited(); images.assert_not_awaited(); enqueue.assert_not_awaited()


async def test_reference_images_requires_admin_and_bounds_page_size(monkeypatch):
    app = FastAPI(); app.include_router(api.router, prefix='/subjects')
    user = {'id': 1, 'role': 'user'}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_async_session] = lambda: None
    read = AsyncMock(return_value={'data': [], 'total': 0, 'page': 2, 'size': 12})
    monkeypatch.setattr(gallery, 'reference_images', read)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/subjects/7/reference-images')).status_code == 403
        read.assert_not_awaited()
        user['role'] = 'admin'
        assert (await client.get('/subjects/7/reference-images?size=61')).status_code == 422
        response = await client.get('/subjects/7/reference-images?page=2&size=12&keyword=菲比')
        assert response.status_code == 200
        read.assert_awaited_once_with(None, 7, page=2, size=12, keyword='菲比')


@pytest.mark.parametrize('role,status', [('admin', 400), ('user', 403)])
async def test_failed_extraction_cannot_replay_old_references_from_task_retry(monkeypatch, role, status):
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False

    monkeypatch.setattr(task_api, 'async_session_maker', Session)
    monkeypatch.setattr(task_api.task_repository, 'get_by_id', AsyncMock(return_value=SimpleNamespace(type='extract_subject', status='failed')))
    retry = AsyncMock()
    monkeypatch.setattr(task_api.task_queue, 'retry_task', retry)
    with pytest.raises(HTTPException) as error:
        await task_api.retry_task('failed-extraction', {'role': role})
    assert error.value.status_code == status
    if role == 'admin': assert '重新选择参考图' in error.value.detail
    retry.assert_not_awaited()
