"""图片分析接口：单次补充要求、权限与任务响应契约。"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from pydantic import ValidationError
import httpx
import pytest

from imgtag.api.endpoints import images, mcp, queue, tasks as task_api
from imgtag.api.endpoints.auth import get_current_user
from imgtag.core.exceptions import EmbeddingAPIError
from imgtag.main import unhandled_exception_handler
from imgtag.models.task import Task
from imgtag.schemas.image import ImageCreateByUrl, TagWithSource
from imgtag.schemas.task import Task as TaskResponse


async def test_queue_api_preserves_custom_field_and_checks_permission_before_enqueue(monkeypatch):
    app = FastAPI(); app.include_router(queue.router, prefix='/queue')
    user = {'id': 1, 'role': 'admin', 'permissions': 0}
    app.dependency_overrides[get_current_user] = lambda: user
    enqueue = AsyncMock(return_value={'added': 1, 'task_ids': ['custom']})
    monkeypatch.setattr(queue.task_queue, 'enqueue_tasks', enqueue)
    monkeypatch.setattr(queue.task_queue, 'get_status', AsyncMock(return_value={'pending_count': 1}))
    monkeypatch.setattr(queue.task_queue, '_running', True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/queue/add', json={'image_ids': [18], 'force_analyze': True, 'analysis_instructions': '重点描述表情'})
        assert response.status_code == 200
        enqueue.assert_awaited_once_with([18], force_analyze=True, analysis_instructions='重点描述表情')
        enqueue.reset_mock()
        assert (await client.post('/queue/add', json={'image_ids': [18], 'analysis_instructions': '字' * 6001})).status_code == 422
        user['role'] = 'user'
        assert (await client.post('/queue/add', json={'image_ids': [18], 'analysis_instructions': '要求'})).status_code == 403
        enqueue.assert_not_awaited()


@pytest.mark.parametrize('model', [ImageCreateByUrl, mcp.AddImageArguments])
async def test_url_and_mcp_upload_inputs_support_bounded_optional_instructions(model):
    assert model(image_url='https://example.com/a.png', analysis_instructions='描述图中文字').analysis_instructions == '描述图中文字'
    assert model(image_url='https://example.com/a.png').analysis_instructions == ''
    with pytest.raises(ValidationError):
        model(image_url='https://example.com/a.png', analysis_instructions='字' * 6001)


async def test_upload_openapi_exposes_same_field_and_image_tag_marker():
    app = FastAPI(); app.include_router(images.router, prefix='/images')
    schema = app.openapi()
    body = schema['paths']['/images/upload']['post']['requestBody']['content']['multipart/form-data']['schema']['$ref'].rsplit('/', 1)[1]
    field = schema['components']['schemas'][body]['properties']['analysis_instructions']
    assert field['maxLength'] == 6000 and field['default'] == ''
    assert TagWithSource(id=1, name='菲比', is_subject=True).model_dump()['is_subject'] is True
    assert TagWithSource(id=2, name='紫色眼睛').is_subject is False


class LocalSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def make_app(role="admin"):
    app = FastAPI()
    app.include_router(task_api.router, prefix="/tasks")
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": role}
    return app


@pytest.fixture
def repository(monkeypatch):
    monkeypatch.setattr("imgtag.services.task_service.async_session_maker", LocalSession)
    detail = AsyncMock()
    listing = AsyncMock()
    monkeypatch.setattr("imgtag.services.task_service.task_repository.get_by_id", detail)
    monkeypatch.setattr("imgtag.services.task_service.task_repository.get_visible_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr("imgtag.services.task_service.task_repository.get_tasks", listing)
    return detail, listing


@pytest.mark.parametrize("task_type", ["analyze_image", "extract_subject", "rebuild_vector"])
@pytest.mark.parametrize("status", ["pending", "processing", "completed", "failed"])
@pytest.mark.parametrize("payload", [None, {"image_id": 18}])
async def test_list_and_detail_return_complete_timestamps(repository, task_type, status, payload):
    detail, listing = repository
    created = datetime(2026, 10, 18, 1, 0, tzinfo=timezone.utc)
    updated = datetime(2026, 10, 18, 1, 5, tzinfo=timezone.utc)
    task = Task(
        id="test-task", type=task_type, status=status, payload=payload,
        result={"version_id": 7, "pending_review": True} if status == "completed" else None,
        error="测试失败" if status == "failed" else None,
        created_at=created, updated_at=updated,
        completed_at=updated if status in ("completed", "failed") else None,
    )
    detail.return_value = task
    listing.return_value = ([task], 1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app()), base_url="http://test") as client:
        response = await client.get("/tasks/test-task")
        assert response.status_code == 200, response.text
        value = response.json()
        validated = TaskResponse.model_validate(value)
        assert validated.updated_at == updated
        assert validated.created_at == created
        assert validated.updated_at != validated.created_at
        assert validated.payload == payload
        assert validated.result == task.result
        assert validated.error == task.error
        assert validated.completed_at == task.completed_at
        response = await client.get("/tasks/")
        assert response.status_code == 200, response.text
        assert response.json()["data"] == [value]
        assert response.json()["total"] == 1
    assert listing.await_args.kwargs["include_extraction"] is True


async def test_detail_missing_task_remains_404(repository):
    repository[0].return_value = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app()), base_url="http://test") as client:
        assert (await client.get("/tasks/missing")).status_code == 404


async def test_extraction_detail_stays_admin_only(repository):
    repository[0].return_value = Task(
        id="private-task", type="extract_subject", status="pending", payload=None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app("user")), base_url="http://test") as client:
        assert (await client.get("/tasks/private-task")).status_code == 404


async def test_save_embedding_auth_failure_is_upstream_error_and_preserves_image(monkeypatch):
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.dependency_overrides[get_current_user] = lambda: {'id': 1, 'role': 'admin'}
    app.dependency_overrides[images.get_async_session] = lambda: object()
    image = SimpleNamespace(id=19, description='原描述')
    monkeypatch.setattr(images.image_repository, 'get_by_id_for_update', AsyncMock(return_value=image))
    monkeypatch.setattr(images.image_update_service, 'resolve_category', AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(images.image_tag_repository, 'get_image_tags', AsyncMock(return_value=[]))
    monkeypatch.setattr(images.embedding_service, 'get_embedding_combined', AsyncMock(side_effect=EmbeddingAPIError(
        '向量服务 API 密钥无效；当前网页登录仍有效（HTTP 401）', upstream_status=401)))
    write = AsyncMock()
    monkeypatch.setattr(images.image_repository, 'update_image', write)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
        response = await client.put('/images/19', json={'description': '新描述'})
    assert response.status_code == 502
    error = response.json()['error']
    assert error['code'] == 'EMBEDDING_API_ERROR' and error['upstream_status'] == 401
    assert '网页登录仍有效' in error['message']
    assert image.description == '原描述'
    write.assert_not_awaited()


@pytest.mark.parametrize('role', ['admin', 'user'])
async def test_prompt_defaults_are_read_only_admin_only_and_contain_no_secrets(monkeypatch, role):
    from imgtag.api.endpoints import config as config_api
    from imgtag.core.config_defaults import DEFAULT_CONFIG, DEFAULT_CATEGORY_PROMPTS
    from imgtag.db.repositories import config_repository
    app = FastAPI()
    app.include_router(config_api.router, prefix='/config')
    app.dependency_overrides[get_current_user] = lambda: {'id': 1, 'role': role}
    reads = AsyncMock()
    writes = AsyncMock()
    monkeypatch.setattr(config_repository, 'get_value', reads)
    monkeypatch.setattr(config_repository, 'set_value', writes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/config/prompt-defaults')
    if role == 'admin':
        assert response.status_code == 200
        assert response.json() == {'vision_prompt': DEFAULT_CONFIG['vision_prompt'], 'category_prompts': DEFAULT_CATEGORY_PROMPTS}
        assert 'vision_api_key' not in response.json()
        assert '主体: xxx。文字: xxx。心情/氛围: xxx。表述含义: xxx。' in response.json()['category_prompts']['meme']
    else:
        assert response.status_code == 403
    reads.assert_not_awaited()
    writes.assert_not_awaited()


def test_category_prompt_defaults_match_seeded_categories():
    import ast
    from pathlib import Path
    from imgtag.core.config_defaults import DEFAULT_CATEGORY_PROMPTS
    seed = ast.parse((Path(__file__).parents[2] / 'src/imgtag/alembic/versions/0001_initial.py').read_text())
    rows = next(ast.literal_eval(node.value) for node in ast.walk(seed)
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'categories' for t in node.targets))
    assert DEFAULT_CATEGORY_PROMPTS == {code: prompt for _, _, _, code, prompt in rows}


async def test_task_visibility_and_redaction_use_database_filter_before_pagination(monkeypatch):
    """用内存库执行真实查询，验证总数、分页、详情和旧任务默认拒绝。"""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from imgtag.services.task_service import task_service

    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE images (id INTEGER PRIMARY KEY, uploaded_by INTEGER)'))
        conn.execute(text('INSERT INTO images VALUES (1,1),(2,2)'))
        conn.execute(text('''CREATE TABLE tasks (id TEXT PRIMARY KEY, type TEXT, status TEXT,
            payload JSON, result JSON, error TEXT, created_at DATETIME, updated_at DATETIME, completed_at DATETIME)'''))
    with Session(engine) as sync:
        now = datetime.now(timezone.utc)
        for task_id, kind, payload in [('own-a','analyze_image',{'image_id':1}),
                ('own-b','rebuild_vector',{'image_id':1}), ('other','analyze_image',{'image_id':2}),
                ('deleted','analyze_image',{'image_id':99}), ('legacy','analyze_image',None),
                ('extract','extract_subject',{'image_id':1}), ('unknown','future_type',{'image_id':1})]:
            sync.add(Task(id=task_id, type=kind, status='failed', payload=payload,
                result={'analysis_input': {'private':'内部定义'}, 'analysis_raw_response':'内部响应', 'saved':False},
                error='内部错误地址', created_at=now, updated_at=now))
        sync.commit()

        class MemorySession:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def execute(self, stmt): return sync.execute(stmt)
            async def get(self, model, key): return sync.get(model, key)

        monkeypatch.setattr('imgtag.services.task_service.async_session_maker', MemorySession)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app('user')), base_url='http://test') as client:
            response = await client.get('/tasks/?size=1')
            assert response.status_code == 200 and response.json()['total'] == 2
            assert len(response.json()['data']) == 1
            second = await client.get('/tasks/?size=1&page=2')
            assert second.json()['data'][0]['id'] != response.json()['data'][0]['id']
            for task_id in ['own-a', 'own-b']:
                response = await client.get('/tasks/' + task_id)
                assert response.status_code == 200
                assert response.json()['result'] == {'saved':False}
                assert response.json()['payload'] == {'image_id':1}
                assert response.json()['error'] == '任务执行失败，请联系管理员查看详情'
                assert '内部' not in response.text
            for task_id in ['other','deleted','legacy','extract','unknown','missing']:
                assert (await client.get('/tasks/' + task_id)).status_code == 404
        admin = {'id':9,'role':'admin'}
        assert (await task_service.get_tasks(user=admin))['total'] == 7
        assert (await task_service.get_task('other', user=admin))['result']['analysis_input'] == {'private':'内部定义'}
    engine.dispose()
