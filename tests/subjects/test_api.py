"""主体接口：权限、参考图库与批量重分析确认。"""

import json
import math
import re
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import Select, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import TextualSelect

from imgtag.api.endpoints import images, subjects, subjects as api, tags, tasks as task_api
from imgtag.api.endpoints.auth import get_current_user
from imgtag.db import get_async_session
from imgtag.db.repositories import image_repository, subject_repository
from imgtag.models import Image, Tag
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


@pytest.mark.parametrize('path,payload', [('/images/1/subjects',{'subject_ids':[1],'reanalyze':False}),
    ('/images/1/subjects/primary',{'subject_id':1,'reanalyze':False})])
async def test_subject_association_requires_login_and_image_ownership(monkeypatch, path, payload):
    app = make_app()
    image = SimpleNamespace(id=1, uploaded_by=1)
    monkeypatch.setattr(images.image_repository, 'get_by_id', AsyncMock(return_value=image))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.put(path, json=payload)).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: {'id':2,'role':'user','permissions':15}
        assert (await client.put(path, json=payload)).status_code == 403


async def test_owner_cannot_register_subject_sample(monkeypatch):
    app = make_app()
    app.dependency_overrides[get_current_user] = lambda: {'id':1,'role':'user','permissions':15}
    monkeypatch.setattr(images.image_repository, 'get_by_id', AsyncMock(return_value=SimpleNamespace(id=1,uploaded_by=1)))
    assign = AsyncMock()
    monkeypatch.setattr(images.subject_assignment_service, 'assign_primary_subject', assign)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.put('/images/1/subjects/primary', json={'subject_id':1,'add_sample':True,'reanalyze':False})
        assert response.status_code == 403
    assign.assert_not_awaited()


@pytest.mark.parametrize('permissions,status', [(0, 403), (2, 200)])
async def test_subject_tag_rename_preserves_existing_tag_permissions(monkeypatch, permissions, status):
    app = FastAPI()
    app.include_router(tags.router, prefix='/tags')
    app.dependency_overrides[get_current_user] = lambda: {'id':1,'role':'user','permissions':permissions}
    session = SimpleNamespace(flush=AsyncMock())
    app.dependency_overrides[get_async_session] = lambda: session
    tag = SimpleNamespace(id=7, name='主体别名', level=2)
    monkeypatch.setattr(tags.tag_repository, 'get_by_id', AsyncMock(return_value=tag))
    monkeypatch.setattr(tags.tag_repository, 'exists', AsyncMock(return_value=False))
    sync = AsyncMock(return_value=1)
    monkeypatch.setattr(subject_repository, 'sync_tag_rename', sync)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.put('/tags/id/7', json={'name':'改名'})
        assert response.status_code == status, response.text
    if status == 200:
        assert tag.name == '改名'
        sync.assert_awaited_once_with(session, tag_id=7, new_name='改名')
    else:
        assert tag.name == '主体别名'
        sync.assert_not_awaited()


@pytest.fixture
def image_search_session(monkeypatch):
    connection = sqlite3.connect(':memory:')

    def cosine_distance(stored, query):
        left, right = json.loads(stored), json.loads(query)
        norm = math.hypot(*left) * math.hypot(*right)
        return 1 - sum(a * b for a, b in zip(left, right)) / norm if norm else None

    connection.create_function('cosine_distance', 2, cosine_distance)
    connection.executescript("""
        CREATE TABLE images (id INTEGER, description TEXT, original_url TEXT,
            embedding TEXT, is_public BOOLEAN, uploaded_by INTEGER);
        CREATE TABLE tags (id INTEGER, name TEXT);
        CREATE TABLE image_tags (image_id INTEGER, tag_id INTEGER);
        CREATE TABLE subjects (id INTEGER, primary_tag_id INTEGER,
            alias_tag_ids TEXT, is_active BOOLEAN);
        INSERT INTO tags VALUES (10,'茜特菈莉'),(11,'奶奶'),(12,'Citlali'),
            (20,'停用主体'),(21,'停用别名'),(30,'开心'),(40,'分类'),
            (50,'Doro'),(51,'doro'),(52,'多萝');
        INSERT INTO subjects VALUES (1,10,'[11,12]',1),(2,20,'[21]',0),(3,50,'[51,52]',1);
        INSERT INTO images VALUES
            (1,'主名标签',NULL,'[-1,0]',1,1),
            (2,'别名标签',NULL,'[-1,0]',1,1),
            (3,'私有',NULL,'[-1,0]',0,2),
            (4,'停用主体',NULL,'[-1,0]',1,1),
            (5,'描述含奶奶',NULL,'[-1,0]',1,1),
            (6,'主名称图片',NULL,'[-1,0]',1,1),
            (7,'小写别名图片',NULL,'[-1,0]',1,1),
            (8,'中文别名图片',NULL,'[-1,0]',1,1),
            (9,'私有主名称图片',NULL,'[-1,0]',0,2),
            (10,'多个身份标签',NULL,'[-1,0]',1,1);
        INSERT INTO image_tags VALUES
            (1,10),(1,12),(1,30),(1,40),(2,11),(3,10),(4,20),
            (6,50),(6,30),(6,40),(7,51),(8,52),(9,50),(10,50),(10,51);
    """)

    async def execute(statement, params=None):
        if isinstance(statement, (TextClause, TextualSelect)):
            compiled = statement.params(**params).compile(
                dialect=postgresql.dialect(paramstyle='named'),
                compile_kwargs={'render_postcompile': True},
            )
            sql = str(compiled)
            sql = sql.replace('i.embedding <=> :vector', 'cosine_distance(i.embedding, :vector)')
            cursor = connection.execute(adapt_sql(sql), compiled.params)
            return cursor
        if isinstance(statement, Select):
            entity = statement.column_descriptions[0].get('entity')
            if entity is Image and statement.column_descriptions[0]['expr'] is Image:
                statement = statement.with_only_columns(Image.id)
                sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
                ids = [row[0] for row in connection.execute(adapt_sql(sql))]
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: ids))
            if 'count(' in str(statement):
                sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
                value = connection.execute(adapt_sql(sql)).fetchone()[0]
                return SimpleNamespace(scalar=lambda: value)
        return []

    def adapt_sql(sql):
        sql = re.sub(
            r'(\w+\.\w+) = ANY \(subjects.alias_tag_ids\)',
            r'\1 IN (SELECT value FROM json_each(subjects.alias_tag_ids))', sql,
        )
        return sql.replace('ILIKE', 'LIKE').replace('%%', '%')

    monkeypatch.setattr(image_repository, 'get_by_ids', AsyncMock(return_value=[]))
    monkeypatch.setattr(images.storage_service, 'get_read_urls', AsyncMock(return_value={}))
    try:
        yield SimpleNamespace(execute=execute, connection=connection)
    finally:
        connection.close()


@pytest.mark.parametrize('filters,expected', [
    ({'keyword': '奶奶'}, [5, 2, 1]),
    ({'keyword': '奶'}, [5, 2, 1]),
    ({'keyword': 'cItLaLi'}, [2, 1]),
    ({'tags': ['奶奶']}, [2, 1]),
    ({'tags': ['茜特菈莉']}, [2, 1]),
    ({'tags': ['奶奶', '开心']}, [1]),
    ({'keyword': '奶奶', 'category_id': 40}, [1]),
    ({'keyword': '奶奶', 'visible_to_user_id': 2}, [5, 3, 2, 1]),
    ({'keyword': '奶奶', 'limit': 1, 'offset': 1}, [2]),
    ({'keyword': '停用别名'}, []),
    ({'keyword': '停用主体'}, [4]),
    ({'keyword': 'doro'}, [10, 8, 7, 6]),
    ({'keyword': '多萝', 'tags': ['开心']}, [6]),
    ({'keyword': 'doro', 'tags': ['Doro', 'doro']}, [10, 8, 7, 6]),
    ({'tags': ['doro']}, [10, 8, 7, 6]),
    ({'tags': ['Doro']}, [10, 8, 7, 6]),
    ({'tags': ['doro', 'doro']}, [10, 8, 7, 6]),
    ({'tags': ['Doro', 'doro', '开心']}, [6]),
    ({'keyword': 'doro', 'tags': ['不存在']}, []),
    ({'tags': ['Doro', 'doro', '不存在']}, []),
    ({'keyword': 'doro', 'category_id': 40}, [6]),
    ({'keyword': 'doro', 'visible_to_user_id': 2}, [10, 9, 8, 7, 6]),
    ({'keyword': "doro' OR 1=1 --", 'tags': ['doro']}, []),
    ({'keyword': 'doro', 'tags': ["doro' OR 1=1 --"]}, []),
])
async def test_image_search_expands_subject_identity_without_changing_filters(image_search_session, filters, expected):
    result = await image_repository.search_images(image_search_session, **filters)
    assert result['images'] == expected
    assert result['total'] == (3 if 'offset' in filters else len(expected))


@pytest.mark.parametrize('text,filters,expected', [
    ('奶奶', {}, [2, 1]),
    ('Citlali', {}, [2, 1]),
    ('奶奶', {'tags': ['奶奶', '开心']}, [1]),
    ('奶奶', {'category_id': 40}, [1]),
    ('奶奶', {'visible_to_user_id': 2}, [3, 2, 1]),
    ('奶奶', {'limit': 1}, [2]),
    ('停用别名', {}, []),
    ('doro', {}, [10, 8, 7, 6]),
    ('Doro', {}, [10, 8, 7, 6]),
    ('多萝', {'tags': ['Doro', 'doro', '开心']}, [6]),
    ('doro', {'tags': ['doro', 'doro']}, [10, 8, 7, 6]),
    ('doro', {'tags': ['Doro', 'doro', '不存在']}, []),
    ('doro', {'visible_to_user_id': 2}, [10, 9, 8, 7, 6]),
    ("doro' OR 1=1 --", {}, []),
    ('doro', {'tags': ["doro' OR 1=1 --"]}, []),
])
async def test_hybrid_search_scores_subject_alias_matches(image_search_session, text, filters, expected):
    result = await image_repository.hybrid_search(
        image_search_session, query_vector=[0.0, 1.0], query_text=text, **filters,
    )
    assert [row['id'] for row in result] == expected
    assert all(row['similarity'] == pytest.approx(0.3) for row in result)


async def test_search_tag_groups_only_expand_requested_names_independent_of_gallery_size(image_search_session):
    """物化集合只随本次匹配的同义标签增长，不随图片数或无关主体增长。"""
    session = image_search_session
    groups = image_repository._search_tag_groups(Tag.name.in_(['doro', '开心']), name='requested_groups')
    count = select(func.count()).select_from(groups)
    assert (await session.execute(count)).scalar() == 4
    session.connection.executemany(
        'INSERT INTO image_tags VALUES (?,?)',
        [(image_id, tag_id) for image_id in range(100, 1100) for tag_id in (50, 51, 52)],
    )
    # 无关标签和主体不应进入本次匹配集合。
    session.connection.executemany('INSERT INTO tags VALUES (?,?)', [(i, f'无关-{i}') for i in range(100, 200)])
    session.connection.execute("INSERT INTO subjects VALUES (4,100,'[101,102]',1)")
    assert (await session.execute(count)).scalar() == 4


async def test_shared_alias_does_not_transitively_expand_other_subjects(image_search_session):
    """共享别名只匹配直接包含它的主体，不递归把其他主体主名称混为同义词。"""
    session = image_search_session
    session.connection.execute("INSERT INTO tags VALUES (60,'其他主体')")
    session.connection.execute("INSERT INTO subjects VALUES (4,60,'[51]',1)")
    session.connection.execute("INSERT INTO images VALUES (11,'其他主体图片',NULL,'[-1,0]',1,1)")
    session.connection.execute('INSERT INTO image_tags VALUES (11,60)')
    direct = await image_repository.search_images(session, tags=['Doro'])
    assert direct['images'] == [10, 8, 7, 6]
    shared = await image_repository.search_images(session, tags=['doro'])
    assert shared['images'] == [11, 10, 8, 7, 6]
    both = await image_repository.hybrid_search(
        session, query_vector=[0.0, 1.0], query_text='doro', tags=['Doro', '其他主体'],
    )
    assert [row['id'] for row in both] == [10, 7]
