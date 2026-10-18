import asyncio
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI
from sqlalchemy.dialects import sqlite

import pytest
from sqlalchemy.exc import SQLAlchemyError

from imgtag.api.endpoints import vectors
from imgtag.api.endpoints.auth import get_current_user
from imgtag.db import get_async_session
from imgtag.db.repositories import image_repository
from imgtag.services import vector_rebuild_service as rebuild_module
from imgtag.services import vector_maintenance_service as maintenance_module
from imgtag.services.vector_maintenance_service import vector_maintenance_service as maintenance
from imgtag.services.vector_rebuild_service import VectorRebuildService


class Session:
    def __init__(self):
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def rebuild(monkeypatch):
    service = VectorRebuildService()
    monkeypatch.setattr(rebuild_module, "async_session_maker", Session)
    return service


@pytest.mark.asyncio
async def test_progress_counts_success_failure_skip_and_deleted_images(rebuild, monkeypatch):
    progress = []

    async def inputs(session):
        return [(1, "success", []), (2, "failure", []), (3, " ", []), (4, "deleted", [])]

    async def embed(text, tags):
        progress.append(rebuild.status["processed"])
        if text == "failure":
            raise ValueError("HTTP 400")
        return [0.1]

    async def update(session, image_id, embedding):
        return image_id != 4

    monkeypatch.setattr(rebuild_module.image_repository, "list_embedding_inputs", inputs)
    monkeypatch.setattr(rebuild_module.embedding_service, "get_embedding_combined", embed)
    monkeypatch.setattr(rebuild_module.image_repository, "set_embedding", update)
    status_reference = rebuild.status
    rebuild._reset(running=True)
    await rebuild.run()

    assert rebuild.status is status_reference
    assert progress == [0, 1, 3]
    assert rebuild.status["processed"] == rebuild.status["total"] == 4
    assert rebuild.status["succeeded"] == 1
    assert rebuild.status["failed"] == 1
    assert rebuild.status["skipped"] == 2
    assert rebuild.status["last_error"] == "HTTP 400"
    assert rebuild.status["is_running"] is False


@pytest.mark.asyncio
async def test_all_failures_still_reach_full_progress(rebuild, monkeypatch):
    async def inputs(session):
        return [(1, "a", []), (2, "b", []), (3, "c", [])]

    async def fail(text, tags):
        raise ValueError("HTTP 400")

    monkeypatch.setattr(rebuild_module.image_repository, "list_embedding_inputs", inputs)
    monkeypatch.setattr(rebuild_module.embedding_service, "get_embedding_combined", fail)
    rebuild._reset(running=True)
    await rebuild.run()

    assert rebuild.status["processed"] == rebuild.status["total"] == 3
    assert rebuild.status["failed"] == 3
    assert rebuild.status["succeeded"] == 0
    assert rebuild.status["is_running"] is False


@pytest.mark.asyncio
async def test_prepare_reserves_running_state_before_await(rebuild, monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def dimensions():
        entered.set()
        await release.wait()
        return 1024

    async def db_dimensions(session):
        return 1024

    monkeypatch.setattr(rebuild_module.embedding_service, "get_dimensions", dimensions)
    monkeypatch.setattr(rebuild_module.image_repository, "get_embedding_dimensions", db_dimensions)
    task = asyncio.create_task(rebuild.prepare(Session()))
    try:
        await entered.wait()
        assert rebuild.status["is_running"] is True
        with pytest.raises(ValueError, match="正在进行中"):
            await rebuild.prepare(Session())
    finally:
        release.set()
        assert await task == 1024


@pytest.mark.asyncio
async def test_preparation_failure_releases_state_and_rolls_back(rebuild, monkeypatch):
    async def dimensions():
        return 1024

    async def db_dimensions(session):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(rebuild_module.embedding_service, "get_dimensions", dimensions)
    monkeypatch.setattr(rebuild_module.image_repository, "get_embedding_dimensions", db_dimensions)
    session = Session()
    with pytest.raises(SQLAlchemyError):
        await rebuild.prepare(session)
    assert rebuild.status["is_running"] is False
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_listing_failure_is_visible_and_releases_state(rebuild, monkeypatch):
    async def inputs(session):
        raise SQLAlchemyError("list failed")

    monkeypatch.setattr(rebuild_module.image_repository, "list_embedding_inputs", inputs)
    rebuild._reset(running=True)
    await rebuild.run()
    assert rebuild.status["is_running"] is False
    assert "重建失败" in rebuild.status["message"]
    assert rebuild.status["last_error"] == "list failed"


async def test_anomaly_query_excludes_empty_inputs_and_paginates_before_loading():
    """仅适配 pgvector 函数，实际执行内容筛选、异常分类、计数和分页。"""
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.create_function('vector_dims', 1, lambda value: len(json.loads(value)) if value else None)
    # PostgreSQL 的 NaN 大于有效余弦距离范围上界；以 3 模拟该比较行为。
    connection.create_function('self_distance', 1, lambda value: 0 if value and any(json.loads(value)) else 3)
    connection.executescript("""
        CREATE TABLE images (id INTEGER PRIMARY KEY, description TEXT, embedding TEXT);
        CREATE TABLE image_tags (image_id INTEGER, tag_id INTEGER);
        CREATE TABLE tags (id INTEGER, name TEXT, level INTEGER);
        INSERT INTO images VALUES (1,'有描述',NULL),(2,'有描述','[0,0]'),
          (3,'正常','[1,0]'),(4,'','[0,0]'),(5,'',NULL),(6,'',NULL),(7,'',NULL),
          (8,'维度错误','[1,0,0]'),(9,'   ',NULL),(10,'',NULL);
        INSERT INTO tags VALUES (1,'主体',2),(2,'分辨率',1),(3,'分类',0),(4,'   ',2);
        INSERT INTO image_tags VALUES (5,1),(6,2),(7,3),(10,4);
    """)
    class MemorySession:
        async def execute(self, statement):
            sql = str(statement.compile(dialect=sqlite.dialect(), compile_kwargs={'literal_binds':True}))
            sql = sql.replace('images.embedding <=> images.embedding', 'self_distance(images.embedding)')
            rows = connection.execute(sql).fetchall()
            return SimpleNamespace(scalar_one=lambda: rows[0][0], mappings=lambda: SimpleNamespace(all=lambda: [dict(row) for row in rows]))
    try:
        rows, total = await image_repository.find_embedding_anomalies(MemorySession(), 2, limit=2, offset=0)
        assert total == 5
        assert [(row['id'],row['reason']) for row in rows] == [(1,'missing'),(2,'invalid')]
        rows, total = await image_repository.find_embedding_anomalies(MemorySession(), 2, limit=3, offset=2)
        assert total == 5
        assert [(row['id'],row['reason']) for row in rows] == [(5,'missing'),(7,'missing'),(8,'dimension_mismatch')]
        assert rows[-1]['actual_dimensions'] == 3
    finally:
        connection.close()


@pytest.mark.parametrize('method,path', [('GET','/vectors/anomalies'),('POST','/vectors/anomalies/1/rebuild')])
async def test_anomaly_operations_are_admin_only_before_access(monkeypatch, method, path):
    app = FastAPI()
    app.include_router(vectors.router, prefix='/vectors')
    app.dependency_overrides[get_async_session] = lambda: object()
    scan = AsyncMock()
    repair = AsyncMock()
    monkeypatch.setattr(maintenance, 'scan', scan)
    monkeypatch.setattr(maintenance, 'rebuild_image', repair)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.request(method, path)).status_code == 401
        app.dependency_overrides[get_current_user] = lambda: {'id':1,'role':'user','permissions':15}
        assert (await client.request(method, path)).status_code == 403
    scan.assert_not_awaited()
    repair.assert_not_awaited()


async def test_anomaly_scan_loads_only_page_and_does_not_call_models(monkeypatch):
    monkeypatch.setattr(maintenance_module.embedding_service, 'get_dimensions', AsyncMock(return_value=2))
    monkeypatch.setattr(image_repository, 'get_embedding_dimensions', AsyncMock(return_value=2))
    listing = AsyncMock(return_value=([{'id':7,'description':'有内容','reason':'missing','actual_dimensions':None}],25))
    monkeypatch.setattr(image_repository, 'find_embedding_anomalies', listing)
    images = AsyncMock(return_value=[SimpleNamespace(id=7)])
    monkeypatch.setattr(image_repository, 'get_by_ids', images)
    monkeypatch.setattr(maintenance_module.storage_service, 'get_read_urls_with_session', AsyncMock(return_value={7:'https://example.com/7'}))
    monkeypatch.setattr(image_repository, 'get_batch_image_tags_with_source', AsyncMock(return_value={7:[{'level':2,'name':'主体'},{'level':1,'name':'分辨率'}]}))
    embed = AsyncMock()
    monkeypatch.setattr(maintenance_module.embedding_service, 'get_embedding_combined', embed)
    result = await maintenance.scan(None, page=2, size=20)
    assert result['total'] == 25 and result['pages'] == 2
    assert result['data'][0]['tags'] == ['主体'] and result['data'][0]['image_url'].endswith('/7')
    listing.assert_awaited_once_with(None, 2, limit=20, offset=20)
    images.assert_awaited_once_with(None, [7])
    embed.assert_not_awaited()


@pytest.mark.parametrize('description,tags,db_dimensions,status', [
    ('有内容',[],2,202),('',[SimpleNamespace(level=2,name='标签')],2,202),
    ('   ',[SimpleNamespace(level=1,name='分辨率')],2,400),('有内容',[],3,409),
])
async def test_single_rebuild_only_enqueues_vector_work_and_checks_inputs(monkeypatch, description, tags, db_dimensions, status):
    app = FastAPI()
    app.include_router(vectors.router, prefix='/vectors')
    app.dependency_overrides[get_current_user] = lambda: {'id':1,'role':'admin'}
    session = SimpleNamespace(commit=AsyncMock())
    app.dependency_overrides[get_async_session] = lambda: session
    monkeypatch.setattr(image_repository, 'get_with_tags', AsyncMock(return_value=SimpleNamespace(id=7,description=description,tags=tags)))
    monkeypatch.setattr(image_repository, 'get_embedding_dimensions', AsyncMock(return_value=db_dimensions))
    monkeypatch.setattr(maintenance_module.embedding_service, 'get_dimensions', AsyncMock(return_value=2))
    queued = AsyncMock(return_value={'task_ids':['repair'], 'added':1})
    monkeypatch.setattr(maintenance_module.task_queue, 'enqueue_tasks', queued)
    monkeypatch.setattr(vectors.task_queue, 'start_processing', AsyncMock())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/vectors/anomalies/7/rebuild')
    assert response.status_code == status, response.text
    if status == 202:
        queued.assert_awaited_once_with([7], task_type='rebuild_vector', session=session)
        session.commit.assert_awaited_once()
        assert response.json()['task_ids'] == ['repair']
    else:
        queued.assert_not_awaited()
        session.commit.assert_not_awaited()
