import asyncio
import hashlib
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from importlib import import_module
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, HTTPException
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import Boolean, Column, DefaultClause, Integer, JSON, MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from imgtag.api.endpoints import images as image_api, storage_endpoints, tasks as task_api
from imgtag.api.endpoints.auth import get_current_user
from imgtag.core.config import Settings
from imgtag.core.storage_constants import StorageTaskType
from imgtag.core.storage_runtime import StorageOperationStopped, storage_attempt
from imgtag.db.repositories import image_location_repository, storage_endpoint_repository, task_repository
from imgtag.models.image_location import ImageLocation
from imgtag.models.storage_endpoint import StorageEndpoint
from imgtag.models.task import Task
from imgtag.schemas.storage import EndpointCreate, EndpointUpdate
from imgtag.services.base_storage_task import TaskProgress
from imgtag.services.storage_deletion_service import StorageDeletionService
from imgtag.services.storage_management_service import storage_management_service
from imgtag.services.storage_service import StorageService, storage_service
from imgtag.services.storage_task_control import load_endpoint_snapshot, snapshot_endpoint
from imgtag.services.storage_unlink_service import StorageUnlinkService

sync_module = import_module("imgtag.services.storage_sync_service")
storage_module = import_module("imgtag.services.storage_service")


def test_pool_settings_from_environment(monkeypatch):
    monkeypatch.setenv('DB_POOL_SIZE', '3')
    monkeypatch.setenv('DB_MAX_OVERFLOW', '1')
    monkeypatch.setenv('DB_POOL_PRE_PING', 'false')
    config = Settings(_env_file=None)
    assert (config.DB_POOL_SIZE, config.DB_MAX_OVERFLOW, config.DB_POOL_PRE_PING) == (3, 1, False)
    monkeypatch.setenv('DB_POOL_SIZE', '0')
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("path_style", [True, False])
async def test_read_urls_use_one_query_on_existing_session_without_loading_credentials(monkeypatch, path_style):
    service = StorageService()
    first = SimpleNamespace(id=1, provider='local', bucket_name='uploads', path_prefix='gallery',
                            public_url_prefix='https://cdn.example', endpoint_url=None,
                            is_enabled=True, read_priority=0, read_weight=1)
    second = SimpleNamespace(id=2, provider='s3', bucket_name='backup', path_prefix='',
                             public_url_prefix=None, endpoint_url='https://storage.example',
                             path_style=path_style, is_enabled=True, read_priority=10, read_weight=1)
    locations = [
        (SimpleNamespace(id=1, image_id=7, endpoint_id=1, object_key='photo.jpg'), first),
        (SimpleNamespace(id=2, image_id=7, endpoint_id=2, object_key='photo.jpg'), second),
        (SimpleNamespace(id=3, image_id=8, endpoint_id=2, object_key='other.jpg'), second),
    ]
    execute = AsyncMock(return_value=SimpleNamespace(all=lambda: locations))
    session = SimpleNamespace(execute=execute)
    monkeypatch.setattr(storage_module, 'async_session_maker', lambda: pytest.fail('不能嵌套借连接'))
    urls = await service.get_read_urls_by_ids(session, [7, 8, 9, 7])
    remote_url = ('https://storage.example/backup/other.jpg' if path_style
                  else 'https://backup.storage.example/other.jpg')
    assert urls == {7: 'https://cdn.example/data/uploads/gallery/photo.jpg',
                    8: remote_url, 9: ''}
    execute.assert_awaited_once()
    sql = str(execute.await_args.args[0])
    assert 'JOIN storage_endpoints' in sql and 'is_healthy IS true' in sql and 'is_enabled IS true' in sql
    assert 'secret_access_key' not in sql and 'access_key_id' not in sql and 'images.embedding' not in sql
    assert 'storage_endpoints.path_style' in sql
    assert 'storage_endpoints.public_url_include_bucket' in sql
    assert (await service.get_read_urls_with_session(session, [])) == {}
    execute.assert_awaited_once()


@pytest.mark.parametrize("path_style", [True, False])
@pytest.mark.parametrize(
    "provider, endpoint_url, public_url_prefix, path_prefix, expected",
    [
        ('s3', 'https://s3.example.com/', None, '',
         ('https://s3.example.com/photos/example.jpg', 'https://photos.s3.example.com/example.jpg')),
        ('s3', 'http://storage.example:9000/s3///', None, '/images/gallery/',
         ('http://storage.example:9000/s3/photos/images/gallery/example.jpg',
          'http://photos.storage.example:9000/s3/images/gallery/example.jpg')),
        ('s3', 'https://s3.example.com', 'https://cdn.example.com/assets/', '/images/',
         ('https://cdn.example.com/assets/images/example.jpg',) * 2),
        ('s3', 'https://s3.example.com', 'https://cdn.example.com/photos/', '',
         ('https://cdn.example.com/photos/example.jpg',) * 2),
        ('local', None, None, '/images/',
         ('/data/photos/images/example.jpg',) * 2),
        ('local', None, 'https://cdn.example.com/', '',
         ('https://cdn.example.com/data/photos/example.jpg',) * 2),
        ('s3', None, None, '', ('', '')),
    ],
)
def test_storage_read_url_addressing(
    path_style, provider, endpoint_url, public_url_prefix, path_prefix, expected,
):
    endpoint = SimpleNamespace(
        provider=provider, endpoint_url=endpoint_url, public_url_prefix=public_url_prefix,
        bucket_name='photos', path_prefix=path_prefix, path_style=path_style,
        public_url_include_bucket=False,
    )
    assert StorageService()._build_url(endpoint, 'example.jpg') == expected[0 if path_style else 1]


@pytest.mark.parametrize("path_style", [True, False])
@pytest.mark.parametrize("public_url_prefix", ['https://imgtag.r2.example.com/', 'https://pub-example.r2.dev/'])
@pytest.mark.parametrize("path_prefix", ['', '/images/'])
async def test_r2_public_read_urls_do_not_repeat_bucket(path_style, public_url_prefix, path_prefix):
    endpoint = SimpleNamespace(
        id=2, provider='s3', endpoint_url='https://account.r2.cloudflarestorage.com',
        public_url_prefix=public_url_prefix, bucket_name='imgtag', path_prefix=path_prefix,
        public_url_include_bucket=False,
        path_style=path_style, is_enabled=True, read_priority=100, read_weight=1,
    )
    location = SimpleNamespace(id=1, image_id=7, endpoint_id=2, object_key='landscape/aa/photo.jpg')
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(location, endpoint)])))
    prefix = 'images/' if path_prefix else ''
    assert await StorageService().get_read_urls_by_ids(session, [7]) == {
        7: f'{public_url_prefix}{prefix}landscape/aa/photo.jpg',
    }
    session.execute.assert_awaited_once()


@pytest.mark.parametrize('path_style', [True, False])
@pytest.mark.parametrize('public_url_prefix, include_bucket, expected', [
    ('https://storage.example/', True, 'https://storage.example/photos/images/other/photo.jpg'),
    ('https://cdn.example/', False, 'https://cdn.example/images/other/photo.jpg'),
    ('https://cdn.example/photos/', False, 'https://cdn.example/photos/images/other/photo.jpg'),
    ('https://pub-example.r2.dev/', False, 'https://pub-example.r2.dev/images/other/photo.jpg'),
])
async def test_public_url_bucket_modes_in_batch_reads(path_style, public_url_prefix, include_bucket, expected):
    endpoint = SimpleNamespace(
        id=2, provider='s3', endpoint_url='https://storage.example',
        bucket_name='photos', path_prefix='/images/', path_style=path_style,
        public_url_prefix=public_url_prefix, public_url_include_bucket=include_bucket,
        is_enabled=True, read_priority=100, read_weight=1,
    )
    location = SimpleNamespace(id=1, image_id=7, endpoint_id=2, object_key='other/photo.jpg')
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(location, endpoint)])))
    assert await StorageService().get_read_urls_by_ids(session, [7]) == {7: expected}


@pytest.fixture
def storage_endpoint_api(monkeypatch):
    app = FastAPI()
    app.include_router(storage_endpoints.router, prefix='/storage')
    session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock(), flush=AsyncMock())
    endpoint = StorageEndpoint(
        id=2, name='storage', provider='s3', endpoint_url='https://storage.example',
        region='auto', bucket_name='photos', path_style=True, path_prefix='images',
        public_url_prefix='https://cdn.example', public_url_include_bucket=True,
        role='primary', is_enabled=True, is_default_upload=False, auto_sync_enabled=False,
        read_priority=100, read_weight=1, is_healthy=True, operation_generation=0,
    )
    app.dependency_overrides[storage_endpoints.require_admin] = lambda: {'id': 1, 'role': 'admin'}
    app.dependency_overrides[storage_endpoints.get_async_session] = lambda: session

    async def create(session, **values):
        for key, value in values.items():
            setattr(endpoint, key, value)
        return endpoint

    async def update(session, record, **values):
        for key, value in values.items():
            setattr(record, key, value)
        return record

    repo = storage_endpoints.storage_endpoint_repository
    monkeypatch.setattr(repo, 'create', AsyncMock(side_effect=create))
    monkeypatch.setattr(repo, 'update', AsyncMock(side_effect=update))
    monkeypatch.setattr(repo, 'get_by_name', AsyncMock(return_value=None))
    monkeypatch.setattr(repo, 'get_by_id', AsyncMock(return_value=endpoint))
    monkeypatch.setattr(repo, 'get_all', AsyncMock(return_value=[endpoint]))
    monkeypatch.setattr(repo, 'get_enabled', AsyncMock(return_value=[endpoint]))
    monkeypatch.setattr(repo, 'lock_all', AsyncMock(return_value=[endpoint]))
    monkeypatch.setattr(storage_endpoints.image_location_repository, 'count_by_endpoint', AsyncMock(return_value=4))
    monkeypatch.setattr(storage_endpoints.task_repository, 'get_active_for_endpoint', AsyncMock(return_value=None))
    monkeypatch.setattr(storage_endpoints.task_repository, 'get_active_storage_for_endpoint', AsyncMock(return_value=[]))
    return app, repo


@pytest.mark.parametrize('include_bucket', [True, False])
async def test_public_url_mode_persists_through_endpoint_api(storage_endpoint_api, include_bucket):
    app, repo = storage_endpoint_api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        created = await client.post('/storage/endpoints', json={
            'name': 'storage', 'provider': 's3', 'public_url_include_bucket': include_bucket,
        })
        assert created.status_code == 200, created.text
        assert created.json()['public_url_include_bucket'] is include_bucket
        assert repo.create.await_args.kwargs['public_url_include_bucket'] is include_bucket
        for path in ['/storage/endpoints', '/storage/endpoints?enabled_only=true', '/storage/endpoints/2']:
            response = await client.get(path)
            assert response.status_code == 200, response.text
            data = response.json()
            assert (data[0] if isinstance(data, list) else data)['public_url_include_bucket'] is include_bucket
        updated = await client.put('/storage/endpoints/2', json={'public_url_include_bucket': not include_bucket})
        assert updated.status_code == 200, updated.text
        assert updated.json()['public_url_include_bucket'] is not include_bucket
        assert repo.update.await_args.kwargs == {'public_url_include_bucket': not include_bucket}
        # 旧客户端不传新字段时，不能把已经选择的桶专属模式重置为默认值。
        unchanged = await client.put('/storage/endpoints/2', json={'name': 'renamed'})
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()['public_url_include_bucket'] is not include_bucket
        assert repo.update.await_args.kwargs == {'name': 'renamed'}


def test_public_url_mode_defaults_and_rejects_null():
    assert EndpointCreate(name='storage', provider='s3').public_url_include_bucket is True
    assert 'public_url_include_bucket' not in EndpointUpdate(name='renamed').model_dump(exclude_unset=True)
    for schema, values in [(EndpointCreate, {'name': 'storage', 'provider': 's3'}), (EndpointUpdate, {})]:
        with pytest.raises(ValidationError):
            schema(**values, public_url_include_bucket=None)


def test_public_url_mode_migration_keeps_existing_bucket_paths():
    migration = import_module('imgtag.alembic.versions.0009_public_url_addressing')
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE storage_endpoints (id INTEGER PRIMARY KEY)'))
            connection.execute(text('INSERT INTO storage_endpoints (id) VALUES (1)'))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                assert connection.execute(text('SELECT public_url_include_bucket FROM storage_endpoints WHERE id=1')).scalar_one() == 1
                connection.execute(text('INSERT INTO storage_endpoints (id) VALUES (2)'))
                assert connection.execute(text('SELECT public_url_include_bucket FROM storage_endpoints WHERE id=2')).scalar_one() == 1
                connection.execute(text('UPDATE storage_endpoints SET public_url_include_bucket=false WHERE id=2'))
                assert connection.execute(text('SELECT public_url_include_bucket FROM storage_endpoints WHERE id=2')).scalar_one() == 0
                migration.downgrade()
            assert [column['name'] for column in inspect(connection).get_columns('storage_endpoints')] == ['id']
            assert connection.execute(text('SELECT count(*) FROM storage_endpoints')).scalar_one() == 2
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_transient_errors_retry_but_authentication_does_not(monkeypatch):
    monkeypatch.setattr(sync_module.settings, 'STORAGE_SYNC_DB_MAX_ATTEMPTS', 3)
    sleep = AsyncMock()
    monkeypatch.setattr(sync_module.asyncio, 'sleep', sleep)
    error = DBAPIError(None, None, RuntimeError('(EMAXCONNSESSION) max clients reached'))
    operation = AsyncMock(side_effect=[error, error, 'ok'])
    assert await sync_module.retry_sync_db(operation)() == 'ok'
    assert operation.await_count == 3
    assert sleep.await_count == 2
    assert sleep.await_args_list[1].args[0] > sleep.await_args_list[0].args[0]

    denied = AsyncMock(side_effect=ValueError('invalid password'))
    with pytest.raises(ValueError):
        await sync_module.retry_sync_db(denied)()
    assert denied.await_count == 1


@pytest.mark.asyncio
async def test_retry_has_a_finite_limit(monkeypatch):
    monkeypatch.setattr(sync_module.settings, 'STORAGE_SYNC_DB_MAX_ATTEMPTS', 2)
    monkeypatch.setattr(sync_module.asyncio, 'sleep', AsyncMock())
    operation = AsyncMock(side_effect=RuntimeError('EMAXCONNSESSION'))
    with pytest.raises(RuntimeError):
        await sync_module.retry_sync_db(operation)()
    assert operation.await_count == 2


@pytest.mark.asyncio
async def test_missing_local_file_restored_without_holding_db_connection(monkeypatch):
    active = 0
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def sessions():
        nonlocal active
        active += 1
        try:
            yield session
        finally:
            active -= 1

    monkeypatch.setattr(sync_module, 'async_session_maker', sessions)
    monkeypatch.setattr(sync_module.storage_endpoint_repository, 'guard_write', AsyncMock())
    source = SimpleNamespace(object_key='landscape/aa/test.jpg', category_code='landscape')
    target = SimpleNamespace(id=9, sync_status='synced')
    monkeypatch.setattr(sync_module.image_location_repository, 'get_by_image_and_endpoint',
                        AsyncMock(side_effect=[source, target, target, target]))
    save = AsyncMock(side_effect=[RuntimeError('EMAXCONNSESSION'), None])
    monkeypatch.setattr(sync_module.image_location_repository, 'mark_synced', save)
    monkeypatch.setattr(sync_module.asyncio, 'sleep', AsyncMock())

    async def missing(*args):
        assert active == 0
        return False

    async def download(*args):
        assert active == 0
        return b'image'

    async def upload(*args):
        assert active == 0
        return True

    monkeypatch.setattr(sync_module.storage_service, 'file_exists', missing)
    fetch = AsyncMock(side_effect=download)
    put = AsyncMock(side_effect=upload)
    monkeypatch.setattr(sync_module.storage_service, 'download_from_endpoint', fetch)
    monkeypatch.setattr(sync_module.storage_service, 'upload_to_endpoint', put)
    service = sync_module.StorageSyncService()
    assert await service._sync_single_image(1, SimpleNamespace(id=1), SimpleNamespace(id=2), False)
    assert save.await_count == 2
    assert fetch.await_count == put.await_count == 1
    assert active == 0


@pytest.mark.asyncio
async def test_local_existence_and_atomic_replacement(tmp_path, monkeypatch):
    service = StorageService()
    endpoint = SimpleNamespace(provider='local', bucket_name=str(tmp_path), path_prefix='prefix')
    assert not await service.file_exists('photo.jpg', endpoint)
    path = tmp_path / 'prefix' / 'photo.jpg'
    path.parent.mkdir()
    path.touch()
    assert not await service.file_exists('photo.jpg', endpoint)
    path.unlink()
    path.mkdir()
    assert not await service.file_exists('photo.jpg', endpoint)
    path.rmdir()
    path.write_bytes(b'original')
    assert not await service.file_exists('photo.jpg', endpoint)  # 历史非哈希文件不能跳过校验
    assert await service._upload_local(b'new', 'photo.jpg', endpoint)
    assert path.read_bytes() == b'new'

    def fail_replace(*args):
        raise OSError('disk failure')

    monkeypatch.setattr(import_module('imgtag.services.storage_service').os, 'replace', fail_replace)
    with pytest.raises(OSError):
        await service._upload_local(b'incomplete', 'photo.jpg', endpoint)
    assert path.read_bytes() == b'new'
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.asyncio
async def test_partial_failure_is_not_completed(monkeypatch):
    @asynccontextmanager
    async def sessions():
        yield SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(sync_module, 'async_session_maker', sessions)
    update = AsyncMock()
    monkeypatch.setattr(sync_module.task_repository, 'update_status', update)
    await sync_module.StorageSyncService()._update_progress('task', 9, 1, [], final=True)
    assert update.await_args.args[2] == 'failed'
    assert update.await_args.kwargs['result']['success_count'] == 9


@pytest.mark.asyncio
@pytest.mark.parametrize("algorithm", ["md5", "sha256"])
async def test_local_hash_checks_actual_bytes(tmp_path, algorithm):
    service = StorageService()
    content = b"image contents" * 100000
    digest = hashlib.new(algorithm, content).hexdigest()
    key = f"landscape/aa/{digest.upper()}.jpg"
    endpoint = SimpleNamespace(provider="local", bucket_name=str(tmp_path), path_prefix="prefix")
    path = tmp_path / "prefix" / key
    path.parent.mkdir(parents=True)
    assert not await service.file_exists(key, endpoint)
    path.write_bytes(content)
    assert await service.file_exists(key, endpoint)
    path.write_bytes(b"x" + content[1:])  # 长度一致的损坏也必须识别
    assert not await service.file_exists(key, endpoint)
    assert await service.verify_content_hash(content, key)
    assert not await service.verify_content_hash(b"corrupt", key)


@pytest.mark.asyncio
@pytest.mark.parametrize("source_corrupt", [False, True])
async def test_sync_repairs_corruption_or_rejects_bad_source(tmp_path, monkeypatch, source_corrupt):
    content = b"original image"
    key = f"{hashlib.md5(content).hexdigest()}.jpg"
    target = SimpleNamespace(id=2, provider="local", bucket_name=str(tmp_path), path_prefix="")
    path = tmp_path / key
    path.write_bytes(b"damaged image")
    service = sync_module.StorageSyncService()
    @asynccontextmanager
    async def sessions():
        yield SimpleNamespace()
    monkeypatch.setattr(sync_module, 'async_session_maker', sessions)
    monkeypatch.setattr(sync_module.storage_endpoint_repository, 'guard_write', AsyncMock())
    monkeypatch.setattr(service, '_load_sync_locations', AsyncMock(return_value=(key, None, True)))
    save = AsyncMock()
    monkeypatch.setattr(service, '_save_sync_location', save)
    fetch = AsyncMock(return_value=b"bad source" if source_corrupt else content)
    monkeypatch.setattr(sync_module.storage_service, 'download_from_endpoint', fetch)
    result = await service._sync_single_image(1, SimpleNamespace(id=1), target, False)
    assert result is not source_corrupt
    assert path.read_bytes() == (b"damaged image" if source_corrupt else content)
    assert save.await_count == (0 if source_corrupt else 1)
    if not source_corrupt:
        fetch.reset_mock()
        assert await service._sync_single_image(1, SimpleNamespace(id=1), target, False)
        fetch.assert_not_awaited()


@pytest.fixture
def storage_database(monkeypatch):
    """真实 SQL 的内存库；仅替换异步适配层，不连接外部服务。"""

    engine = create_engine('sqlite://')
    metadata = MetaData()
    Table('images', metadata, Column('id', Integer, primary_key=True), Column('uploaded_by', Integer))
    for model in (StorageEndpoint, ImageLocation, Task):
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
            elif isinstance(column.type, Boolean) and column.server_default is not None:
                column.server_default = DefaultClause(text('1' if str(column.server_default.arg) == 'true' else '0'))
    metadata.create_all(engine)

    class AsyncAdapter:
        def __init__(self):
            self.sync = Session(engine, expire_on_commit=False)
        def add(self, item):
            self.sync.add(item)
        async def execute(self, *args, **kwargs):
            return self.sync.execute(*args, **kwargs)
        async def get(self, *args, **kwargs):
            return self.sync.get(*args, **kwargs)
        async def flush(self):
            self.sync.flush()
        async def commit(self):
            self.sync.commit()
        async def rollback(self):
            self.sync.rollback()
        async def refresh(self, item):
            self.sync.refresh(item)
        async def delete(self, item):
            self.sync.delete(item)

    @asynccontextmanager
    async def sessions():
        current = AsyncAdapter()
        try:
            yield current
        finally:
            current.sync.close()

    for name in ('base_storage_task', 'storage_task_control', 'storage_sync_service',
                 'storage_unlink_service', 'storage_deletion_service'):
        monkeypatch.setattr(import_module(f'imgtag.services.{name}'), 'async_session_maker', sessions)
    with engine.begin() as conn:
        conn.execute(metadata.tables['images'].insert(), [{'id': i} for i in range(1, 8)])
    with Session(engine) as session:
        session.add_all([
            StorageEndpoint(id=1, name='local', provider='local', role='primary', is_enabled=True),
            StorageEndpoint(id=2, name='primary', provider='s3', endpoint_url='https://offline.invalid',
                            role='primary', is_enabled=True, is_default_upload=True),
            StorageEndpoint(id=3, name='backup', provider='s3', role='backup', is_enabled=True,
                            sync_from_endpoint_id=2, auto_sync_enabled=True),
        ])
        session.add_all([
            ImageLocation(id=1, image_id=1, endpoint_id=2, object_key='one.jpg', is_primary=True),
            ImageLocation(id=2, image_id=1, endpoint_id=3, object_key='one.jpg'),
            ImageLocation(id=3, image_id=2, endpoint_id=2, object_key='two.jpg', is_primary=True),
        ])
        session.commit()
    yield sessions
    engine.dispose()


async def test_storage_task_query_includes_source_target_and_unlink(storage_database):
    async with storage_database() as session:
        session.sync.add_all([
            Task(id='sync', type='storage_sync', status='pending', payload={'source_endpoint_id': 2, 'target_endpoint_id': 3}),
            Task(id='unlink', type='storage_unlink', status='processing', payload={'endpoint_id': 2}),
        ])
        await session.commit()
        assert {t.id for t in await task_repository.get_active_storage_for_endpoint(session, 2)} == {'sync', 'unlink'}
        assert [t.id for t in await task_repository.get_active_storage_for_endpoint(session, 3)] == ['sync']
        assert await task_repository.get_active_for_endpoint(session, 2, ['storage_sync']) is not None


async def test_sync_locks_only_changed_basic_fields_and_role_swap_is_atomic(storage_database):
    async with storage_database() as session:
        session.sync.add(Task(id='sync', type='storage_sync', status='pending', payload={'source_endpoint_id': 2, 'target_endpoint_id': 3}))
        await session.commit()
        with pytest.raises(HTTPException) as denied:
            await storage_management_service.update(session, 2, {'name': 'changed'})
        assert denied.value.status_code == 409
        endpoint = await storage_management_service.update(session, 2, {
            'name': 'primary', 'read_weight': 7, 'read_priority': 3, 'is_enabled': False,
            'role': 'backup', 'is_default_upload': False,
        })
        await session.commit()
        assert (endpoint.read_weight, endpoint.read_priority, endpoint.is_enabled, endpoint.role) == (7, 3, False, 'backup')
        assert (await session.get(StorageEndpoint, 3)).role == 'primary'
        assert (await session.get(StorageEndpoint, 3)).is_default_upload is True
        task = await session.get(Task, 'sync')
        assert task.payload == {'source_endpoint_id': 2, 'target_endpoint_id': 3}


async def test_non_sync_task_allows_basic_edits_and_preserves_snapshot(storage_database):
    async with storage_database() as session:
        endpoint = await session.get(StorageEndpoint, 2)
        endpoint.secret_access_key = 'synthetic-secret'
        snapshot = snapshot_endpoint(endpoint)
        assert 'synthetic-secret' not in str(snapshot)
        assert '_secret_access_key' not in snapshot
        session.sync.add(Task(id='unlink', type='storage_unlink', status='processing', payload={'endpoint_id': 2}))
        await session.commit()
        running = await load_endpoint_snapshot(session, snapshot, 2)
        await storage_management_service.update(session, 2, {'name': 'renamed', 'endpoint_url': 'https://new.invalid', 'secret_access_key': 'new-synthetic'})
        await session.commit()
        assert running.endpoint_url == 'https://offline.invalid'
        assert running.secret_access_key == 'synthetic-secret'
        assert (await session.get(StorageEndpoint, 2)).secret_access_key == 'new-synthetic'
        assert await task_repository.get_active_for_endpoint(session, 2, ['storage_sync']) is None


@pytest.mark.parametrize('remove_endpoint', [False, True])
async def test_force_cleanup_is_offline_and_preserves_images_other_copies(storage_database, monkeypatch, remove_endpoint):
    for name in ('upload_to_endpoint', 'download_from_endpoint', 'delete_from_endpoint', 'file_exists'):
        monkeypatch.setattr(storage_service, name, AsyncMock(side_effect=AssertionError('离线清理禁止访问远程')))
    async with storage_database() as session:
        session.sync.add_all([
            Task(id='sync', type='storage_sync', status='processing', payload={'source_endpoint_id': 2, 'target_endpoint_id': 3}),
            Task(id='unlink', type='storage_unlink', status='pending', payload={'endpoint_id': 2}),
        ])
        await session.commit()
        result = await storage_management_service.force_cleanup(session, 2, remove_endpoint=remove_endpoint, expected_name='primary')
        assert result['locations_removed'] == 2
        assert set(result['cancelled_task_ids']) == {'sync', 'unlink'}
    async with storage_database() as session:
        assert session.sync.execute(text('SELECT count(*) FROM images')).scalar_one() == 7
        remaining = session.sync.execute(select(ImageLocation)).scalars().all()
        assert [(loc.endpoint_id, loc.image_id, loc.is_primary) for loc in remaining] == [(3, 1, True)]
        assert [task.status for task in session.sync.execute(select(Task).where(Task.id.in_(['sync', 'unlink']))).scalars()] == ['cancelled', 'cancelled']
        other = await session.get(StorageEndpoint, 3)
        assert other.sync_from_endpoint_id == (None if remove_endpoint else 2)
        assert other.auto_sync_enabled is (not remove_endpoint)
        endpoint = await session.get(StorageEndpoint, 2)
        if remove_endpoint:
            assert endpoint is None
        else:
            assert endpoint.is_enabled and endpoint.is_default_upload and endpoint.operation_generation == 1
        with pytest.raises(StorageOperationStopped):
            await storage_endpoint_repository.guard_write(session, {2: 0, 3: 0})
        assert not await task_repository.update_status(session, 'sync', 'completed')
        await session.commit()


async def test_force_cleanup_rollback_keeps_all_associations(storage_database, monkeypatch):
    monkeypatch.setattr(image_location_repository, 'remove_locations', AsyncMock(side_effect=RuntimeError('synthetic DB failure')))
    async with storage_database() as session:
        session.sync.add(Task(id='sync', type='storage_sync', status='pending', payload={'source_endpoint_id': 2}))
        await session.commit()
        with pytest.raises(RuntimeError):
            await storage_management_service.force_cleanup(session, 2, remove_endpoint=True)
    async with storage_database() as session:
        assert (await session.get(StorageEndpoint, 2)).operation_generation == 0
        assert (await session.get(Task, 'sync')).status == 'pending'
        assert session.sync.execute(text('SELECT count(*) FROM image_locations')).scalar_one() == 3


async def test_expired_lease_rejects_old_attempt_and_cancelled_cannot_restart(storage_database):
    async with storage_database() as session:
        session.sync.add(Task(id='sync', type='storage_sync', status='pending', payload={}))
        await session.commit()
        first = await task_repository.claim_storage_task(session, 'sync')
        await session.commit()
        assert await task_repository.claim_storage_task(session, 'sync') is None
        task = await session.get(Task, 'sync')
        task.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        await session.commit()
        second = await task_repository.claim_storage_task(session, 'sync')
        await session.commit()
        assert first != second
        marker = storage_attempt.set(('sync', first))
        try:
            with pytest.raises(StorageOperationStopped):
                await storage_endpoint_repository.guard_write(session, {2: 0})
            assert not await task_repository.update_status(session, 'sync', 'completed')
        finally:
            storage_attempt.reset(marker)
        assert await task_repository.update_status(session, 'sync', 'cancelled')
        await session.commit()
        assert await task_repository.claim_storage_task(session, 'sync') is None
        assert not await task_repository.update_status(session, 'sync', 'processing')


async def test_running_task_cancel_rejects_even_late_write(storage_database, monkeypatch):
    control_module = import_module('imgtag.services.storage_task_control')
    control = control_module.storage_task_control
    started, rejected = asyncio.Event(), asyncio.Event()
    async with storage_database() as session:
        session.sync.add(Task(id='sync', type='storage_sync', status='pending', payload={'source_endpoint_id': 2, 'target_endpoint_id': 3}))
        await session.commit()

    async def operation():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            async with storage_database() as session:
                with pytest.raises(StorageOperationStopped):
                    await image_location_repository.create(session, image_id=2, endpoint_id=3,
                        expected_generation=0, object_key='late.jpg')
                rejected.set()

    running = asyncio.create_task(control.run('sync', operation))
    await asyncio.wait_for(started.wait(), 2)
    async with storage_database() as session:
        assert await storage_management_service.cancel(session, 2) == ['sync']
    await asyncio.wait_for(running, 2)
    assert rejected.is_set()
    async with storage_database() as session:
        assert (await session.get(Task, 'sync')).status == 'cancelled'
        assert session.sync.execute(text('SELECT count(*) FROM image_locations')).scalar_one() == 3


@pytest.mark.parametrize("service_class", [StorageUnlinkService, StorageDeletionService])
async def test_cleanup_timeout_preserves_failed_locations_and_committed_success(storage_database, monkeypatch, service_class):
    service = service_class()
    monkeypatch.setattr(service, 'BATCH_CONFIG', replace(service.BATCH_CONFIG, rate_limit_seconds=0))
    monkeypatch.setattr(sync_module.settings, 'STORAGE_ITEM_TIMEOUT', 0.01)
    monkeypatch.setattr(sync_module.settings, 'STORAGE_MAX_CONSECUTIVE_FAILURES', 2)
    async with storage_database() as session:
        session.sync.add(ImageLocation(id=4, image_id=3, endpoint_id=2, object_key='three.jpg'))
        endpoint = await session.get(StorageEndpoint, 2)
        session.sync.add(Task(id='unlink', type=service.TASK_TYPE.value, status='pending', payload={
            'endpoint_id': 2, 'total_count': 3, 'delete_files': True, 'endpoint_snapshot': snapshot_endpoint(endpoint),
        }))
        await session.commit()
    async def process(item, context):
        if item.get('location_id', item.get('id')) == 1:
            return True, None
        await asyncio.Event().wait()
    monkeypatch.setattr(service, 'process_single_item', process)
    await service._run_task('unlink')
    async with storage_database() as session:
        task = await session.get(Task, 'unlink')
        assert task.status == 'failed'
        assert (task.result['success_count'], task.result['failed_count']) == (1, 2)
        assert session.sync.execute(text('SELECT id FROM image_locations WHERE endpoint_id=2 ORDER BY id')).scalars().all() == [3, 4]
        assert session.sync.execute(text('SELECT count(*) FROM images')).scalar_one() == 7


async def test_storage_request_timeout_and_boto_limits(monkeypatch):
    endpoint = StorageEndpoint(id=2, name='remote', provider='s3', bucket_name='photos', path_prefix='', path_style=True)
    put = SimpleNamespace(put_object=lambda **kwargs: None, close=Mock())
    client = Mock(return_value=put)
    monkeypatch.setattr(storage_module.boto3, 'client', client)
    service = StorageService()
    assert await service.upload_to_endpoint(b'image', 'one.jpg', endpoint)
    config = client.call_args.kwargs['config']
    assert config.connect_timeout == 5 and config.read_timeout == 30
    assert config.retries['total_max_attempts'] == 2
    monkeypatch.setattr(sync_module.settings, 'STORAGE_ITEM_TIMEOUT', 0.01)
    async def hanging(*args):
        await asyncio.Event().wait()
    monkeypatch.setattr(service, '_upload_s3', hanging)
    assert not await service.upload_to_endpoint(b'image', 'one.jpg', endpoint)
    service.close()


def test_storage_task_control_migration_preserves_existing_data():
    migration = import_module('imgtag.alembic.versions.0010_storage_task_control')
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE storage_endpoints (id INTEGER PRIMARY KEY)'))
            connection.execute(text('CREATE TABLE tasks (id TEXT PRIMARY KEY)'))
            connection.execute(text('INSERT INTO storage_endpoints (id) VALUES (2)'))
            connection.execute(text("INSERT INTO tasks (id) VALUES ('legacy')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                assert connection.execute(text('SELECT operation_generation FROM storage_endpoints')).scalar_one() == 0
                assert connection.execute(text('SELECT run_token, heartbeat_at FROM tasks')).one() == (None, None)
                migration.downgrade()
            assert [c['name'] for c in inspect(connection).get_columns('tasks')] == ['id']
            assert connection.execute(text('SELECT count(*) FROM storage_endpoints')).scalar_one() == 1
    finally:
        engine.dispose()


@pytest.fixture
def storage_http(storage_database):
    app = FastAPI()
    app.include_router(storage_endpoints.router, prefix='/storage')
    async def session_dependency():
        async with storage_database() as session:
            yield session
    app.dependency_overrides[storage_endpoints.get_async_session] = session_dependency
    app.dependency_overrides[storage_endpoints.require_admin] = lambda: {'id': 1, 'username': 'test-admin', 'role': 'admin'}
    return app


async def test_offline_storage_api_edit_cancel_and_cleanup(storage_http, storage_database):
    async with storage_database() as session:
        session.sync.add(Task(id='sync', type='storage_sync', status='pending', payload={
            'source_endpoint_id': 2, 'target_endpoint_id': 3, 'batch_size': 4,
        }))
        await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=storage_http), base_url='http://test') as client:
        listed = await client.get('/storage/endpoints')
        assert listed.status_code == 200
        assert all(ep['has_active_sync'] for ep in listed.json() if ep['id'] in (2, 3))
        assert next(ep for ep in listed.json() if ep['id'] == 2)['active_task']['total_count'] == 4
        assert (await client.put('/storage/endpoints/3', json={'name': 'blocked'})).status_code == 409
        changed = await client.put('/storage/endpoints/2', json={'read_priority': 2, 'read_weight': 5, 'is_enabled': False})
        assert changed.status_code == 200 and changed.json()['read_weight'] == 5
        assert (await client.post('/storage/endpoints/3/cancel-tasks')).json()['cancelled_task_ids'] == ['sync']
        renamed = await client.put('/storage/endpoints/2', json={'name': 'offline-renamed'})
        assert renamed.status_code == 200
        assert (await client.post('/storage/endpoints/2/force-cleanup', json={'endpoint_name': 'offline-renamed'})).status_code == 400
        assert (await client.post('/storage/endpoints/2/force-cleanup', json={'confirm': True, 'endpoint_name': 'stale'})).status_code == 409
        removed = await client.post('/storage/endpoints/2/force-cleanup', json={'confirm': True, 'endpoint_name': 'offline-renamed'})
        assert removed.status_code == 200, removed.text
        assert removed.json()['endpoint_removed'] is True
        assert (await client.get('/storage/endpoints/2')).status_code == 404
        protected = await client.post('/storage/endpoints/1/force-cleanup', json={'confirm': True, 'endpoint_name': 'local'})
        assert protected.status_code == 400


async def test_storage_maintenance_api_requires_admin(storage_http):
    def denied():
        raise HTTPException(403, '管理员权限')
    storage_http.dependency_overrides[storage_endpoints.require_admin] = denied
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=storage_http), base_url='http://test') as client:
        assert (await client.post('/storage/endpoints/2/cancel-tasks')).status_code == 403
        assert (await client.post('/storage/endpoints/2/force-cleanup', json={'confirm': True, 'endpoint_name': 'primary'})).status_code == 403


async def test_active_storage_task_record_cannot_be_deleted_as_cancellation(storage_database):
    async with storage_database() as session:
        session.sync.add_all([
            Task(id='active', type='storage_sync', status='processing', payload={}),
            Task(id='cancelled', type='storage_sync', status='cancelled', payload={}),
        ])
        await session.commit()
        assert await task_repository.batch_delete(session, ['active', 'cancelled']) == 1
        await session.commit()
        assert await session.get(Task, 'active') is not None


async def test_old_upload_cannot_recreate_links_after_clear_and_reenable(storage_database):
    async with storage_database() as session:
        await storage_management_service.force_cleanup(session, 2, remove_endpoint=False)
        await storage_management_service.update(session, 2, {'is_enabled': True})
        await session.commit()
        with pytest.raises(StorageOperationStopped):
            await image_location_repository.create(session, image_id=2, endpoint_id=2,
                expected_generation=0, object_key='late.jpg')
        current = await image_location_repository.create(session, image_id=2, endpoint_id=2,
            expected_generation=1, object_key='new.jpg')
        await session.commit()
        assert current.object_key == 'new.jpg'


async def test_shutdown_revokes_task_before_cancelling_child(storage_database):
    control = import_module('imgtag.services.storage_task_control').StorageTaskControl()
    started, rejected = asyncio.Event(), asyncio.Event()
    async with storage_database() as session:
        session.add(Task(id='shutdown', type='storage_sync', status='pending', payload={}))
        await session.commit()
    async def operation():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            async with storage_database() as session:
                with pytest.raises(StorageOperationStopped):
                    await storage_endpoint_repository.guard_write(session, {2: 0})
                rejected.set()
    running = asyncio.create_task(control.run('shutdown', operation))
    await asyncio.wait_for(started.wait(), 2)
    await asyncio.wait_for(control.shutdown(), 2)
    await running
    assert rejected.is_set()
    async with storage_database() as session:
        assert (await session.get(Task, 'shutdown')).status == 'failed'


@pytest.mark.parametrize('service_class', [StorageUnlinkService, StorageDeletionService])
async def test_cleanup_deletes_shared_file_only_for_last_reference(storage_database, monkeypatch, tmp_path, service_class):
    service = service_class()
    path = tmp_path / 'one.jpg'
    path.write_bytes(b'shared image')
    async with storage_database() as session:
        (await session.get(ImageLocation, 3)).object_key = 'one.jpg'
        session.add(Task(id='first-pass', type=service.TASK_TYPE.value, status='pending',
                         payload={'endpoint_id': 2, 'delete_files': True}))
        await session.commit()

    allow_delete = False
    async def delete_file(key, endpoint):
        async with storage_database() as session:
            assert await image_location_repository.count_by_object_key(session, 2, key) == 1
        assert path.exists()
        if allow_delete:
            path.unlink()
        return allow_delete

    delete = AsyncMock(side_effect=delete_file)
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', delete)
    await service._run_task('first-pass')
    assert path.exists() and delete.await_count == 1
    async with storage_database() as session:
        first = await session.get(Task, 'first-pass')
        assert first.status == 'failed' and first.result['success_count'] == 1
        assert await image_location_repository.count_by_object_key(session, 2, 'one.jpg') == 1
        assert session.sync.execute(text('SELECT id FROM images WHERE id IN (1, 2) ORDER BY id')).scalars().all() == [1, 2]
        session.add(Task(id='second-pass', type=service.TASK_TYPE.value, status='pending',
                         payload={'endpoint_id': 2, 'delete_files': True}))
        await session.commit()
    allow_delete = True
    await service._run_task('second-pass')
    assert not path.exists() and delete.await_count == 2
    async with storage_database() as session:
        assert await image_location_repository.count_by_object_key(session, 2, 'one.jpg') == 0
        assert session.sync.execute(text('SELECT id FROM images ORDER BY id')).scalars().all() == [1, 3, 4, 5, 6, 7]


@pytest.mark.parametrize('service_class, delete_files', [
    (StorageUnlinkService, False), (StorageUnlinkService, True), (StorageDeletionService, True),
])
@pytest.mark.parametrize('delete_succeeds', [False, True])
async def test_cleanup_removes_empty_images_only_when_deleting_files(
    storage_database, monkeypatch, service_class, delete_files, delete_succeeds,
):
    service = service_class()
    monkeypatch.setattr(service, 'BATCH_CONFIG', replace(service.BATCH_CONFIG, rate_limit_seconds=0))
    deletion = AsyncMock(return_value=delete_succeeds)
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', deletion)
    async with storage_database() as session:
        # 禁用的端点仍然有副本，不能因当前不可读而删除图库记录。
        (await session.get(StorageEndpoint, 3)).is_enabled = False
        session.add(Task(id='cleanup-images', type=service.TASK_TYPE.value, status='pending',
                         payload={'endpoint_id': 2, 'delete_files': delete_files}))
        await session.commit()
    await service._run_task('cleanup-images')
    async with storage_database() as session:
        removed = delete_files and delete_succeeds
        assert session.sync.execute(text('SELECT id FROM images ORDER BY id')).scalars().all() == (
            [1, 3, 4, 5, 6, 7] if removed else list(range(1, 8)))
        task = await session.get(Task, 'cleanup-images')
        assert task.status == ('failed' if delete_files and not delete_succeeds else 'completed')
        assert await image_location_repository.count_by_endpoint(session, 2) == (
            2 if delete_files and not delete_succeeds else 0)
        remaining = await session.get(ImageLocation, 2)
        assert remaining.image_id == 1
        if not delete_files or delete_succeeds:
            assert remaining.is_primary
    assert deletion.await_count == (2 if delete_files else 0)


async def test_cleanup_empty_image_deletion_cascades_related_records(storage_database, monkeypatch):
    async with storage_database() as session:
        await session.execute(text('PRAGMA foreign_keys=ON'))
        # 使用真实外键验证既有级联规则，不连接外部数据库。
        for table in ('image_tags', 'image_collections', 'image_subjects', 'image_analysis_versions'):
            await session.execute(text(f'CREATE TABLE {table} (image_id INTEGER REFERENCES images(id) ON DELETE CASCADE)'))
            await session.execute(text(f'INSERT INTO {table} (image_id) VALUES (1), (2)'))
        session.add(Task(id='cascade-images', type='storage_unlink', status='pending',
                         payload={'endpoint_id': 2, 'delete_files': True}))
        await session.commit()
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', AsyncMock(return_value=True))
    await StorageUnlinkService()._run_task('cascade-images')
    async with storage_database() as session:
        assert (await session.get(Task, 'cascade-images')).status == 'completed'
        for table in ('image_tags', 'image_collections', 'image_subjects', 'image_analysis_versions'):
            assert session.sync.execute(text(f'SELECT image_id FROM {table}')).scalars().all() == [1]


@pytest.mark.parametrize('service_class', [StorageUnlinkService, StorageDeletionService])
async def test_concurrent_endpoint_cleanup_deletes_image_after_last_copy(
    storage_database, monkeypatch, service_class,
):
    service = service_class()
    monkeypatch.setattr(service, 'BATCH_CONFIG', replace(service.BATCH_CONFIG, rate_limit_seconds=0))
    started = {2: asyncio.Event(), 3: asyncio.Event()}
    release = {2: asyncio.Event(), 3: asyncio.Event()}
    async def delete_file(key, endpoint):
        started[endpoint.id].set()
        await release[endpoint.id].wait()
        return True
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', delete_file)
    async with storage_database() as session:
        for endpoint_id in (2, 3):
            session.add(Task(id=f'concurrent-{endpoint_id}', type=service.TASK_TYPE.value, status='pending',
                             payload={'endpoint_id': endpoint_id, 'delete_files': True}))
        await session.commit()
    workers = [asyncio.create_task(service._run_task(f'concurrent-{ep}')) for ep in (2, 3)]
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), 2)
        release[2].set()
        await asyncio.wait_for(asyncio.shield(workers[0]), 2)
        async with storage_database() as session:
            assert session.sync.execute(text('SELECT id FROM images WHERE id=1')).scalar_one() == 1
            assert await image_location_repository.count_by_image(session, 1) == 1
        release[3].set()
        await asyncio.wait_for(asyncio.shield(workers[1]), 2)
        async with storage_database() as session:
            assert session.sync.execute(text('SELECT id FROM images ORDER BY id')).scalars().all() == [3, 4, 5, 6, 7]
            assert await image_location_repository.count_by_image(session, 1) == 0
            for endpoint_id in (2, 3):
                assert (await session.get(Task, f'concurrent-{endpoint_id}')).status == 'completed'
    finally:
        for event in release.values():
            event.set()
        await asyncio.gather(*workers, return_exceptions=True)


@pytest.mark.parametrize('service_class', [StorageUnlinkService, StorageDeletionService])
async def test_late_remote_cleanup_cannot_delete_images_after_local_cleanup(
    storage_database, monkeypatch, service_class,
):
    ready, release = asyncio.Event(), asyncio.Event()
    async def delete_file(key, endpoint):
        ready.set()
        await release.wait()
        return True
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', delete_file)
    # 模拟旧任务仍运行于另一个进程：本地中断信号无法直接取消它。
    control = import_module('imgtag.services.storage_task_control').storage_task_control
    monkeypatch.setattr(control, 'interrupt_local', lambda task_ids: None)
    async with storage_database() as session:
        session.add(Task(id='late-cleanup', type=service_class.TASK_TYPE.value, status='pending',
                         payload={'endpoint_id': 2, 'delete_files': True}))
        await session.commit()
    worker = asyncio.create_task(service_class()._run_task('late-cleanup'))
    try:
        await asyncio.wait_for(ready.wait(), 2)
        async with storage_database() as session:
            await storage_management_service.force_cleanup(session, 2, remove_endpoint=False)
        release.set()
        await asyncio.wait_for(asyncio.shield(worker), 2)
        async with storage_database() as session:
            assert (await session.get(Task, 'late-cleanup')).status == 'cancelled'
            assert session.sync.execute(text('SELECT id FROM images ORDER BY id')).scalars().all() == list(range(1, 8))
            assert await image_location_repository.count_by_endpoint(session, 2) == 0
            assert not await storage_endpoint_repository.has_cleanup_task(session, 2)
    finally:
        release.set()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.fixture
async def batch_deletion_database(storage_database):
    async with storage_database() as session:
        await session.execute(text('PRAGMA foreign_keys=ON'))
        await session.execute(text('CREATE TABLE image_tags (image_id INTEGER REFERENCES images(id) ON DELETE CASCADE, tag_id INTEGER)'))
        await session.execute(text('UPDATE images SET uploaded_by=CASE WHEN id=2 THEN 10 ELSE 20 END'))
        await session.commit()
    return storage_database


@pytest.mark.parametrize('delete_files', [False, True])
async def test_batch_delete_filters_ownership_and_persists_only_target_files(batch_deletion_database, monkeypatch, delete_files):
    deletion = AsyncMock(return_value=True)
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', deletion)
    async with batch_deletion_database() as session:
        result = await image_api.batch_delete_images(image_api.BatchDeleteRequest(
            image_ids=[1, 2, 7], delete_files=delete_files),
            user={'id': 10, 'username': 'owner', 'role': 'user'}, session=session)
        assert (result['success_count'], result['fail_count'], result['files_scheduled']) == (1, 2, int(delete_files))
        assert session.sync.execute(text('SELECT id FROM images ORDER BY id')).scalars().all() == [1, 3, 4, 5, 6, 7]
        assert await session.get(ImageLocation, 3) is None
        assert await session.get(ImageLocation, 1) is not None
        assert len(result['task_ids']) == int(delete_files)
        if delete_files:
            task = await session.get(Task, result['task_ids'][0])
            assert task.status == 'pending' and task.type == 'storage_delete'
            assert task.payload['endpoint_id'] == 2 and task.payload['object_keys'] == ['two.jpg']
    deletion.assert_not_awaited()
    if delete_files:
        await StorageDeletionService()._run_task(result['task_ids'][0])
        deletion.assert_awaited_once()
        assert deletion.await_args.args[0] == 'two.jpg'
        async with batch_deletion_database() as session:
            assert (await session.get(Task, result['task_ids'][0])).status == 'completed'


async def test_batch_delete_preserves_file_uploaded_and_registered_before_enqueue(batch_deletion_database, monkeypatch):
    async with batch_deletion_database() as session:
        await image_location_repository.create(session, image_id=3, endpoint_id=2, object_key='two.jpg')
        await session.commit()
        result = await StorageDeletionService().delete_images(session, [2], owner_id=None,
            delete_files=True, initiated_by='admin')
    deletion = AsyncMock(return_value=True)
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', deletion)
    await StorageDeletionService()._run_task(result['task_ids'][0])
    deletion.assert_not_awaited()
    async with batch_deletion_database() as session:
        assert await image_location_repository.count_by_object_key(session, 2, 'two.jpg') == 1
        assert session.sync.execute(text('SELECT id FROM images WHERE id=3')).scalar_one() == 3


async def test_batch_delete_rejects_late_upload_and_allows_fresh_upload_after_completion(batch_deletion_database, monkeypatch):
    ready, finish_upload = asyncio.Event(), asyncio.Event()
    objects = {'two.jpg'}
    async with batch_deletion_database() as session:
        old_endpoint, error = await storage_endpoint_repository.resolve_upload_endpoint(session, 2)
        assert not error
        old_generation = old_endpoint.operation_generation

    async def old_upload():
        ready.set()
        await finish_upload.wait()
        objects.add('two.jpg')
        async with batch_deletion_database() as session:
            with pytest.raises(StorageOperationStopped):
                await image_location_repository.create(session, image_id=3, endpoint_id=2,
                    expected_generation=old_generation, object_key='two.jpg')

    async def delete_file(key, endpoint):
        objects.discard(key)
        return True
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', delete_file)
    upload = asyncio.create_task(old_upload())
    try:
        await asyncio.wait_for(ready.wait(), 2)
        async with batch_deletion_database() as session:
            result = await StorageDeletionService().delete_images(session, [2], owner_id=None,
                delete_files=True, initiated_by='admin')
            endpoint, error = await storage_endpoint_repository.resolve_upload_endpoint(session, 2)
            assert endpoint is None and error
        finish_upload.set()
        await asyncio.wait_for(asyncio.shield(upload), 2)
        task_id = result['task_ids'][0]
        await StorageDeletionService()._run_task(task_id)
        assert 'two.jpg' not in objects
        async with batch_deletion_database() as session:
            endpoint, error = await storage_endpoint_repository.resolve_upload_endpoint(session, 2)
            assert endpoint and not error
            objects.add('two.jpg')
            await image_location_repository.create(session, image_id=3, endpoint_id=2,
                expected_generation=endpoint.operation_generation, object_key='two.jpg')
            await session.commit()
        # 结束的旧任务不能再次领取并误删刚上传的文件。
        await StorageDeletionService()._run_task(task_id)
        assert 'two.jpg' in objects
    finally:
        finish_upload.set()
        await asyncio.gather(upload, return_exceptions=True)


async def test_batch_delete_conflict_rolls_back_all_endpoint_tasks_and_images(batch_deletion_database):
    async with batch_deletion_database() as session:
        session.add(Task(id='conflict', type='storage_sync', status='pending',
                         payload={'source_endpoint_id': 1, 'target_endpoint_id': 3}))
        await session.commit()
        # 图片 1 涉及端点 2、3；端点 2 先登记后，端点 3 冲突也必须全部回滚。
        with pytest.raises(HTTPException) as error:
            await image_api.batch_delete_images(image_api.BatchDeleteRequest(image_ids=[1], delete_files=True),
                user={'id': 1, 'role': 'admin'}, session=session)
        assert error.value.status_code == 409
    async with batch_deletion_database() as session:
        assert session.sync.execute(text('SELECT id FROM images WHERE id=1')).scalar_one() == 1
        assert await image_location_repository.count_by_image(session, 1) == 2
        assert {task.id for task in session.sync.execute(select(Task)).scalars()} == {'conflict'}
        assert (await session.get(StorageEndpoint, 2)).operation_generation == 0


async def test_batch_delete_cannot_interrupt_running_sync(batch_deletion_database, monkeypatch):
    ready, release = asyncio.Event(), asyncio.Event()
    async def download(*args):
        ready.set()
        await release.wait()
        return b'image'
    monkeypatch.setattr(storage_service, 'download_from_endpoint', download)
    monkeypatch.setattr(storage_service, 'verify_content_hash', AsyncMock(return_value=True))
    monkeypatch.setattr(storage_service, 'upload_to_endpoint', AsyncMock(return_value=True))
    task_ids = await sync_module.StorageSyncService().start_batch_sync(2, 3, [2])
    worker = asyncio.create_task(sync_module.StorageSyncService()._process_sync_task(task_ids[0]))
    try:
        await asyncio.wait_for(ready.wait(), 2)
        async with batch_deletion_database() as session:
            with pytest.raises(HTTPException) as error:
                await image_api.batch_delete_images(image_api.BatchDeleteRequest(image_ids=[2], delete_files=True),
                    user={'id': 1, 'role': 'admin'}, session=session)
            assert error.value.status_code == 409
        release.set()
        await asyncio.wait_for(asyncio.shield(worker), 2)
        async with batch_deletion_database() as session:
            assert (await session.get(Task, task_ids[0])).status == 'completed'
            assert await image_location_repository.count_by_image(session, 2) == 2
    finally:
        release.set()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
async def test_batch_delete_blocks_upload_and_sync_until_remote_delete_drains(batch_deletion_database, monkeypatch, stop):
    service = StorageDeletionService()
    io_service = StorageService()
    ready, release = asyncio.Event(), Event()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(storage_module, 'async_session_maker', batch_deletion_database)
    class Client:
        def delete_object(self, **kwargs):
            loop.call_soon_threadsafe(ready.set)
            assert release.wait(4)
        def close(self): pass
    monkeypatch.setattr(storage_module.boto3, 'client', Mock(return_value=Client()))
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', io_service.delete_from_endpoint)
    async with batch_deletion_database() as session:
        result = await service.delete_images(session, [2], owner_id=None, delete_files=True, initiated_by='admin')
    task_id = result['task_ids'][0]
    with pytest.raises(ValueError):
        await sync_module.StorageSyncService().start_batch_sync(1, 2, [3])
    if stop == 'timeout':
        monkeypatch.setattr(storage_module.settings, 'STORAGE_ITEM_TIMEOUT', 0.03)
    worker = asyncio.create_task(service._run_task(task_id))
    try:
        await asyncio.wait_for(ready.wait(), 2)
        if stop == 'cancel':
            async with batch_deletion_database() as session:
                assert await storage_management_service.cancel(session, 2) == [task_id]
        await asyncio.wait_for(asyncio.shield(worker), 2)
        async with batch_deletion_database() as session:
            assert (await session.get(Task, task_id)).status == ('cancelled' if stop == 'cancel' else 'failed')
            assert await storage_endpoint_repository.has_cleanup_task(session, 2)
            endpoint, error = await storage_endpoint_repository.resolve_upload_endpoint(session, 2)
            assert endpoint is None and error
            with pytest.raises(StorageOperationStopped):
                await image_location_repository.create(session, image_id=3, endpoint_id=2,
                    expected_generation=1, object_key='two.jpg')
        with pytest.raises(ValueError):
            await sync_module.StorageSyncService().start_batch_sync(1, 2, [3])
        release.set()
        await asyncio.wait_for(asyncio.gather(*io_service._pending_deletes), 2)
        async with batch_deletion_database() as session:
            endpoint, error = await storage_endpoint_repository.resolve_upload_endpoint(session, 2)
            assert endpoint and not error
        assert await sync_module.StorageSyncService().start_batch_sync(1, 2, [3])
    finally:
        release.set()
        await asyncio.gather(worker, *io_service._pending_deletes, return_exceptions=True)
        io_service.close()


async def test_batch_delete_recovery_resumes_remaining_keys_without_double_counting(batch_deletion_database, monkeypatch):
    service = StorageDeletionService()
    monkeypatch.setattr(service, 'BATCH_CONFIG', replace(service.BATCH_CONFIG, rate_limit_seconds=0))
    deletion = AsyncMock(return_value=True)
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', deletion)
    async with batch_deletion_database() as session:
        result = await service.delete_images(session, [1, 2], owner_id=None, delete_files=True, initiated_by='admin')
        task_id = result['task_ids'][0]
        token = await task_repository.claim_storage_task(session, task_id)
        await session.commit()
        payload = dict((await session.get(Task, task_id)).payload)
    context = await service.build_context(task_id, payload)
    marker = storage_attempt.set((task_id, token))
    try:
        await service._process_items((await service.get_items_to_process(context))[:1],
            TaskProgress(task_id=task_id, task_type=StorageTaskType.DELETE, total_count=2), context)
    finally:
        storage_attempt.reset(marker)
    async with batch_deletion_database() as session:
        task = await session.get(Task, task_id)
        assert task.payload['object_keys'] == ['two.jpg'] and task.result['success_count'] == 1
        task.heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        await session.commit()
    await service._run_task(task_id)
    assert [call.args[0] for call in deletion.await_args_list] == ['one.jpg', 'two.jpg']
    async with batch_deletion_database() as session:
        task = await session.get(Task, task_id)
        assert task.status == 'completed' and task.result['success_count'] == 2
        assert task.payload['object_keys'] == [] and task.payload['total_count'] == 2


async def test_download_timeout_tries_next_endpoint(monkeypatch, tmp_path):
    service = StorageService()
    remote = StorageEndpoint(id=2, name='offline', provider='s3', is_enabled=True, read_priority=1, read_weight=1)
    local = StorageEndpoint(id=3, name='local', provider='local', bucket_name=str(tmp_path),
                            path_prefix='', is_enabled=True, read_priority=2, read_weight=1)
    (tmp_path / 'one.jpg').write_bytes(b'available copy')
    monkeypatch.setattr(storage_endpoint_repository, 'get_healthy_for_read', AsyncMock(return_value=[remote, local]))
    monkeypatch.setattr(image_location_repository, 'get_by_image', AsyncMock(return_value=[
        SimpleNamespace(endpoint_id=2, object_key='one.jpg'), SimpleNamespace(endpoint_id=3, object_key='one.jpg')]))
    monkeypatch.setattr(storage_module.settings, 'STORAGE_ITEM_TIMEOUT', 0.02)
    async def hang(*args):
        await asyncio.Event().wait()
    fetch = AsyncMock(side_effect=hang)
    monkeypatch.setattr(service, '_download_s3', fetch)
    target = tmp_path / 'download' / 'one.jpg'
    assert await service.download_from_any_endpoint(object(), 1, str(target))
    assert target.read_bytes() == b'available copy'
    fetch.assert_awaited_once()


@pytest.mark.parametrize('interrupt', ['timeout', 'cancel'])
async def test_s3_capacity_stays_bounded_until_threads_finish(monkeypatch, interrupt):
    service = StorageService()
    monkeypatch.setattr(storage_module.settings, 'STORAGE_SYNC_CONCURRENCY', 2)
    monkeypatch.setattr(storage_module.settings, 'STORAGE_ITEM_TIMEOUT', 0.03)
    endpoint = SimpleNamespace(name='remote', provider='s3')
    release, lock = Event(), Lock()
    started = asyncio.Event()
    loop = asyncio.get_running_loop()
    calls = 0

    def request():
        nonlocal calls
        with lock:
            calls += 1
            if calls == 2:
                loop.call_soon_threadsafe(started.set)
        assert release.wait(3), '测试未释放模拟 S3 请求'
        return True

    async def upload(*args):
        return await service._run_s3(request)
    monkeypatch.setattr(service, '_upload_s3', upload)
    running = [asyncio.create_task(service.upload_to_endpoint(b'image', 'one.jpg', endpoint)) for _ in range(6)]
    try:
        await asyncio.wait_for(started.wait(), 1)
        if interrupt == 'cancel':
            for task in running:
                task.cancel()
            results = await asyncio.gather(*running, return_exceptions=True)
            assert all(isinstance(result, asyncio.CancelledError) for result in results)
        else:
            assert await asyncio.gather(*running) == [False] * 6
        assert calls == 2
        # 原请求尚未结束，后续调用只能等待容量；不再往线程池堆积工作。
        assert not await service.upload_to_endpoint(b'image', 'two.jpg', endpoint)
        assert calls == 2
        assert await asyncio.wait_for(asyncio.to_thread(lambda: 'cpu work'), 1) == 'cpu work'
        release.set()
        assert await asyncio.wait_for(service._run_s3(lambda: 'recovered'), 1) == 'recovered'
    finally:
        release.set()
        await asyncio.gather(*running, return_exceptions=True)
        service.close()


async def test_automatic_backups_queue_deduplicate_and_drain_serially(storage_database, monkeypatch):
    service = sync_module.StorageSyncService()
    monkeypatch.setattr(service, '_process_sync_task', AsyncMock())
    ids = []
    for image_id in (1, 2, 3):
        ids.extend(await service.start_batch_sync(2, 3, [image_id], automatic_backup=True))
    assert len(ids) == 3
    assert await service.start_batch_sync(2, 3, [1, 2, 3], automatic_backup=True) == []
    with pytest.raises(ValueError):
        await service.start_batch_sync(2, 3, [4])
    async with storage_database() as session:
        assert await task_repository.claim_storage_task(session, ids[0])
        await session.commit()
        assert await task_repository.claim_storage_task(session, ids[1]) is None
        await session.commit()
        assert await task_repository.update_status(session, ids[0], 'completed')
        await session.commit()
        assert await task_repository.claim_storage_task(session, ids[1])
        await session.commit()
        assert await task_repository.claim_storage_task(session, ids[2]) is None
        assert await task_repository.update_status(session, ids[1], 'completed')
        await session.commit()
        assert await task_repository.claim_storage_task(session, ids[2])
        await session.commit()
    await asyncio.sleep(0)


async def test_automatic_backup_does_not_queue_during_destructive_task(storage_database):
    async with storage_database() as session:
        session.add(Task(id='cleaning', type='storage_unlink', status='pending', payload={'endpoint_id': 3}))
        await session.commit()
    with pytest.raises(ValueError):
        await sync_module.StorageSyncService().start_batch_sync(2, 3, [2], automatic_backup=True)


async def test_scheduled_backup_enqueues_all_pages_and_sources(storage_database, monkeypatch):
    backup = import_module('imgtag.services.backup_service')
    monkeypatch.setattr(backup, 'async_session_maker', storage_database)
    async with storage_database() as session:
        session.add(ImageLocation(image_id=3, endpoint_id=1, object_key='three.jpg', is_primary=True, sync_status='synced'))
        session.sync.add_all([ImageLocation(image_id=image_id, endpoint_id=2, object_key=f'{image_id}.jpg',
                                          is_primary=True, sync_status='synced') for image_id in range(8, 609)])
        await session.commit()
    service = sync_module.StorageSyncService()
    monkeypatch.setattr(service, '_process_sync_task', AsyncMock())
    monkeypatch.setattr(backup, 'storage_sync_service', service)
    async with storage_database() as session:
        assert [endpoint.id for endpoint in await storage_endpoint_repository.get_backup_endpoints(session)] == [3]
        assert len(await image_location_repository.get_missing_backup_batch(session, 3, 0, 500)) == 500
    stats = await backup.run_scheduled_backup()
    assert stats == {'total': 603, 'success': 603, 'failed': 0, 'skipped': 0}
    async with storage_database() as session:
        tasks = await task_repository.get_active_storage_for_endpoint(session, 3)
        queued = [image_id for task in tasks for image_id in task.payload['image_ids']]
        assert len(queued) == len(set(queued)) == 603
        assert {task.payload['source_endpoint_id'] for task in tasks} == {1, 2}
        # 再扫描不会重复创建待办，也不会漏掉第二页。
        await backup.run_scheduled_backup()
        assert len(await task_repository.get_active_storage_for_endpoint(session, 3)) == len(tasks)
    await asyncio.sleep(0)


async def test_storage_recovery_filters_types_and_live_leases_before_limit(storage_database):
    async with storage_database() as session:
        old = datetime.now(timezone.utc) - timedelta(days=1)
        session.sync.add_all([Task(id=f'analysis-{i}', type='analyze_image', status='pending',
                                  created_at=old, payload={}) for i in range(1001)])
        session.sync.add_all([
            Task(id='live', type='storage_sync', status='processing', heartbeat_at=datetime.now(timezone.utc), created_at=old, payload={}),
            Task(id='expired', type='storage_unlink', status='processing', heartbeat_at=old, payload={}),
            Task(id='pending', type='storage_sync', status='pending', payload={}),
            Task(id='audit', type='storage_cleanup', status='pending', payload={}),
        ])
        await session.commit()
        recovered = await task_repository.get_recoverable_storage_tasks(session, limit=2)
        assert {task.id for task in recovered} == {'expired', 'pending'}


async def test_batch_task_deletion_only_removes_owned_terminal_records(storage_database, monkeypatch):
    async with storage_database() as session:
        session.sync.execute(text('UPDATE images SET uploaded_by = CASE WHEN id=1 THEN 1 ELSE 2 END'))
        session.sync.add_all([
            Task(id='own-analysis', type='analyze_image', status='failed', payload={'image_id': 1}),
            Task(id='own-vector', type='rebuild_vector', status='completed', payload={'image_id': 1}),
            Task(id='other', type='analyze_image', status='failed', payload={'image_id': 2}),
            Task(id='pending', type='analyze_image', status='pending', payload={'image_id': 1}),
            Task(id='processing', type='analyze_image', status='processing', payload={'image_id': 1}),
            Task(id='storage', type='storage_sync', status='failed', payload={'source_endpoint_id': 2, 'target_endpoint_id': 3}),
            Task(id='extract', type='extract_subject', status='failed', payload={'image_id': 1}),
        ])
        await session.commit()
    monkeypatch.setattr(import_module('imgtag.services.task_service'), 'async_session_maker', storage_database)
    app = FastAPI()
    app.include_router(task_api.router, prefix='/tasks')
    user = {'id': 1, 'role': 'user', 'permissions': 0}
    app.dependency_overrides[get_current_user] = lambda: user
    all_ids = ['own-analysis', 'own-vector', 'other', 'pending', 'processing', 'storage', 'extract']
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.request('DELETE', '/tasks/batch', json={'task_ids': all_ids})
        assert response.status_code == 200 and response.json()['deleted_count'] == 2
        user['role'] = 'admin'
        response = await client.request('DELETE', '/tasks/batch', json={'task_ids': all_ids})
        assert response.status_code == 200 and response.json()['deleted_count'] == 3
    async with storage_database() as session:
        assert {task.id for task in session.sync.execute(select(Task)).scalars()} == {'pending', 'processing'}


@pytest.mark.parametrize('service_class', [StorageUnlinkService, StorageDeletionService])
async def test_cleanup_generation_rejects_upload_started_before_cleanup(storage_database, monkeypatch, service_class):
    service = service_class()
    async with storage_database() as session:
        old_generation = (await session.get(StorageEndpoint, 2)).operation_generation
    monkeypatch.setattr(service, '_run_task', AsyncMock())
    if service_class is StorageUnlinkService:
        task_id = await service.start_unlink(2, delete_files=True)
    else:
        task_id = await service.start_hard_delete(2)
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', AsyncMock(return_value=True))
    await service_class._run_task(service, task_id)
    async with storage_database() as session:
        assert (await session.get(Task, task_id)).status == 'completed'
        assert (await session.get(StorageEndpoint, 2)).operation_generation == old_generation + 1
        with pytest.raises(StorageOperationStopped):
            await image_location_repository.create(session, image_id=3, endpoint_id=2,
                expected_generation=old_generation, object_key='one.jpg')
    await asyncio.sleep(0)


async def test_expired_peers_are_revoked_and_claimed_in_order(storage_database):
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with storage_database() as session:
        for index, name in enumerate(['older', 'newer']):
            session.add(Task(id=name, type='storage_sync', status='processing', run_token=f'{name}-token',
                heartbeat_at=old, created_at=old + timedelta(seconds=index),
                payload={'source_endpoint_id': 2, 'target_endpoint_id': 3}))
        await session.commit()
        assert await task_repository.claim_storage_task(session, 'newer') is None
        await session.commit()
        marker = storage_attempt.set(('newer', 'newer-token'))
        try:
            with pytest.raises(StorageOperationStopped):
                await storage_endpoint_repository.guard_write(session, {2: 0})
            assert not await task_repository.update_status(session, 'newer', 'completed')
        finally:
            storage_attempt.reset(marker)
        assert await task_repository.claim_storage_task(session, 'older')
        await session.commit()
        assert await task_repository.claim_storage_task(session, 'newer') is None
        assert await task_repository.update_status(session, 'older', 'completed')
        await session.commit()
        assert await task_repository.claim_storage_task(session, 'newer')
        await session.commit()


async def test_queue_does_not_overtake_and_progress_prefers_running(storage_database):
    now = datetime.now(timezone.utc)
    async with storage_database() as session:
        for index, name in enumerate(['oldest', 'middle', 'latest']):
            session.add(Task(id=name, type='storage_sync', status='pending', created_at=now + timedelta(seconds=index),
                payload={'source_endpoint_id': 2, 'target_endpoint_id': 3}))
        await session.commit()
        # 并发调度的新任务先到达领取入口，仍然不能插队。
        async def claim(name):
            async with storage_database() as contender:
                token = await task_repository.claim_storage_task(contender, name)
                await contender.commit()
                return token
        results = await asyncio.gather(*(claim(name) for name in ['latest', 'middle']))
        assert results == [None, None]
        assert await task_repository.claim_storage_task(session, 'oldest')
        await session.commit()
        assert (await task_repository.get_active_for_endpoint(session, 2)).id == 'oldest'
        assert await task_repository.update_status(session, 'oldest', 'completed')
        await session.commit()
        assert (await task_repository.get_active_for_endpoint(session, 2)).id == 'middle'


@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
async def test_cancelled_s3_delete_keeps_writes_blocked_until_actual_completion(storage_database, monkeypatch, stop):
    io_service = StorageService()
    monkeypatch.setattr(storage_module, 'async_session_maker', storage_database)
    started, release, finished = Event(), Event(), Event()
    ready = asyncio.Event()
    loop = asyncio.get_running_loop()
    objects = {'one.jpg': b'image'}
    class Client:
        def delete_object(self, *, Key, **kwargs):
            started.set()
            loop.call_soon_threadsafe(ready.set)
            assert release.wait(4)
            objects.pop(Key, None)
            finished.set()
        def put_object(self, *, Key, Body, **kwargs): objects[Key] = Body
        def close(self): pass
    monkeypatch.setattr(storage_module.boto3, 'client', Mock(return_value=Client()))
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', io_service.delete_from_endpoint)
    async with storage_database() as session:
        # 留一个引用，确保实际发送远程删除。
        await image_location_repository.remove_locations(session, 2, [3])
        session.add(Task(id='drain-delete', type='storage_unlink', status='pending',
                         payload={'endpoint_id': 2, 'delete_files': True}))
        await session.commit()
    if stop == 'timeout':
        monkeypatch.setattr(storage_module.settings, 'STORAGE_ITEM_TIMEOUT', 0.03)
    expected_status = 'cancelled' if stop == 'cancel' else 'failed'
    worker = asyncio.create_task(StorageUnlinkService()._run_task('drain-delete'))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        if stop == 'cancel':
            async with storage_database() as session:
                assert await storage_management_service.cancel(session, 2) == ['drain-delete']
        else:
            await asyncio.wait_for(worker, 1)
        # 重复取消不能提前清掉禁写标记。
        import_module('imgtag.services.storage_task_control').storage_task_control.interrupt_local(['drain-delete'])
        await asyncio.sleep(0.02)
        async with storage_database() as session:
            assert (await session.get(Task, 'drain-delete')).status == expected_status
            assert await storage_endpoint_repository.has_cleanup_task(session, 2)
            endpoint, error = await storage_endpoint_repository.resolve_upload_endpoint(session, 2)
            assert endpoint is None and error
            assert await task_repository.batch_delete(session, ['drain-delete']) == 0
            with pytest.raises(StorageOperationStopped):
                await image_location_repository.create(session, image_id=3, endpoint_id=2,
                    expected_generation=0, object_key='one.jpg')
        with pytest.raises(ValueError):
            await sync_module.StorageSyncService().start_batch_sync(2, 3, [3], automatic_backup=True)
        await asyncio.wait_for(worker, 1)
        assert not finished.is_set()
        release.set()
        await asyncio.wait_for(asyncio.gather(*io_service._pending_deletes), 2)
        assert finished.is_set()
        async with storage_database() as session:
            endpoint, error = await storage_endpoint_repository.resolve_upload_endpoint(session, 2)
            assert endpoint and not error
            assert await io_service.upload_to_endpoint(b'image', 'one.jpg', endpoint)
            await image_location_repository.create(session, image_id=3, endpoint_id=2,
                expected_generation=0, object_key='one.jpg')
            await session.commit()
            assert objects['one.jpg'] == b'image'
            assert (await session.get(Task, 'drain-delete')).status == expected_status
    finally:
        release.set()
        await asyncio.gather(worker, *io_service._pending_deletes, return_exceptions=True)
        io_service.close()


async def test_cancel_while_waiting_for_s3_capacity_never_sends_delete(storage_database, monkeypatch):
    service = StorageService()
    monkeypatch.setattr(storage_module, 'async_session_maker', storage_database)
    monkeypatch.setattr(storage_module.settings, 'STORAGE_SYNC_CONCURRENCY', 1)
    release = Event()
    occupied = asyncio.Event()
    loop = asyncio.get_running_loop()
    def occupy():
        loop.call_soon_threadsafe(occupied.set)
        assert release.wait(4)
    client = SimpleNamespace(delete_object=Mock(), close=Mock())
    monkeypatch.setattr(storage_module.boto3, 'client', Mock(return_value=client))
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', service.delete_from_endpoint)
    async with storage_database() as session:
        await image_location_repository.remove_locations(session, 2, [3])
        session.add(Task(id='waiting-delete', type='storage_unlink', status='pending', payload={'endpoint_id': 2, 'delete_files': True}))
        await session.commit()
    busy = asyncio.create_task(service._run_s3(occupy))
    await asyncio.wait_for(occupied.wait(), 1)
    worker = asyncio.create_task(StorageUnlinkService()._run_task('waiting-delete'))
    try:
        async def wait_for_delete():
            while not service._pending_deletes:
                await asyncio.sleep(0)
        await asyncio.wait_for(wait_for_delete(), 1)
        async with storage_database() as session:
            await storage_management_service.cancel(session, 2)
        await asyncio.wait_for(worker, 1)
        release.set()
        await busy
        await asyncio.wait_for(asyncio.gather(*service._pending_deletes, return_exceptions=True), 1)
        client.delete_object.assert_not_called()
        async with storage_database() as session:
            assert not await storage_endpoint_repository.has_cleanup_task(session, 2)
    finally:
        release.set()
        await asyncio.gather(busy, worker, *service._pending_deletes, return_exceptions=True)
        service.close()


@pytest.mark.parametrize('status', ['processing', 'failed', 'cancelled'])
@pytest.mark.parametrize('kind', ['storage_delete', 'storage_unlink'])
async def test_force_cleanup_releases_orphan_delete_marker_without_recreating_endpoint(storage_database, status, kind):
    async with storage_database() as session:
        session.add(Task(id='orphan-delete', type=kind, status=status, run_token='old-token',
            heartbeat_at=datetime.now(timezone.utc) - timedelta(days=1),
            payload={'endpoint_id': 2, 'delete_in_flight': True}))
        session.add(Task(id='other-delete', type='storage_delete', status='cancelled', run_token='other-token',
            payload={'endpoint_id': 3, 'delete_in_flight': True}))
        await session.commit()
        assert await storage_endpoint_repository.has_cleanup_task(session, 2)
        result = await storage_management_service.force_cleanup(session, 2, remove_endpoint=False)
        assert result['cancelled_task_ids'] == ['orphan-delete']
        assert result['locations_removed'] == 2
    async with storage_database() as session:
        task = await session.get(Task, 'orphan-delete')
        assert task.run_token is None and task.heartbeat_at is None
        assert not task.payload['delete_in_flight']
        assert task.status == ('cancelled' if status == 'processing' else status)
        assert not await storage_endpoint_repository.has_cleanup_task(session, 2)
        assert await storage_endpoint_repository.has_cleanup_task(session, 3)
        assert (await session.get(Task, 'other-delete')).run_token == 'other-token'
        endpoint = await session.get(StorageEndpoint, 2)
        assert endpoint.is_enabled and endpoint.operation_generation == 1
        # 不用删配置重建；管理员确认旧远程请求结束后，手动启用恢复上传。
        await storage_management_service.update(session, 2, {'is_enabled': True})
        await session.commit()
        endpoint, error = await storage_endpoint_repository.resolve_upload_endpoint(session, 2)
        assert endpoint is not None and error is None
        await image_location_repository.create(session, image_id=3, endpoint_id=2,
            expected_generation=1, object_key='restored.jpg')
        await session.commit()
        marker = storage_attempt.set(('orphan-delete', 'old-token'))
        try:
            with pytest.raises(StorageOperationStopped):
                await storage_endpoint_repository.guard_write(session, {2: 1})
            assert not await task_repository.update_status(session, 'orphan-delete', 'completed')
        finally:
            storage_attempt.reset(marker)
        # 迟到的旧开始/收尾回调都不能重新设置禁写，或清掉后续任务的标记。
        await task_repository.set_delete_in_flight(session, 'orphan-delete', 'old-token', True)
        session.add(Task(id='new-delete', type=kind, status='processing', run_token='new-token',
                         payload={'endpoint_id': 2, 'delete_in_flight': True}))
        await session.commit()
        await task_repository.set_delete_in_flight(session, 'orphan-delete', 'old-token', False)
        await session.commit()
        assert not (await session.get(Task, 'orphan-delete')).payload['delete_in_flight']
        assert (await session.get(Task, 'new-delete')).payload['delete_in_flight']


async def test_force_cleanup_marker_reset_rolls_back_with_other_cleanup_changes(storage_database, monkeypatch):
    async with storage_database() as session:
        session.add(Task(id='orphan', type='storage_delete', status='cancelled', run_token='old-token',
                         payload={'endpoint_id': 2, 'delete_in_flight': True}))
        await session.commit()
    monkeypatch.setattr(image_location_repository, 'remove_locations', AsyncMock(side_effect=RuntimeError('synthetic failure')))
    async with storage_database() as session:
        with pytest.raises(RuntimeError):
            await storage_management_service.force_cleanup(session, 2, remove_endpoint=False)
    async with storage_database() as session:
        task = await session.get(Task, 'orphan')
        assert task.payload['delete_in_flight'] and task.run_token == 'old-token'
        assert (await session.get(StorageEndpoint, 2)).operation_generation == 0
        assert await image_location_repository.count_by_endpoint(session, 2) == 2


async def test_api_force_cleanup_retains_configuration_and_unlocks_orphan(storage_http, storage_database):
    async with storage_database() as session:
        session.add(Task(id='orphan-api', type='storage_unlink', status='failed', run_token='old-token',
                         payload={'endpoint_id': 2, 'delete_in_flight': True}))
        await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=storage_http), base_url='http://test') as client:
        response = await client.post('/storage/endpoints/2/force-cleanup',
            json={'confirm': True, 'endpoint_name': 'primary', 'remove_endpoint': False})
        assert response.status_code == 200, response.text
        assert not response.json()['endpoint_removed']
        response = await client.put('/storage/endpoints/2', json={'is_enabled': True})
        assert response.status_code == 200, response.text
    async with storage_database() as session:
        endpoint, error = await storage_endpoint_repository.resolve_upload_endpoint(session, 2)
        assert endpoint and not error
        assert await task_repository.claim_storage_task(session, 'orphan-api') is None


@pytest.mark.parametrize('status', ['failed', 'cancelled', 'completed'])
async def test_endpoint_list_and_detail_both_show_delete_drain_until_release(storage_http, storage_database, status):
    async with storage_database() as session:
        session.add(Task(id='draining', type='storage_unlink', status=status, run_token='drain-token',
            payload={'endpoint_id': 2, 'delete_in_flight': True, 'total_count': 2},
            result={'success_count': 1, 'failed_count': 0}))
        session.add(Task(id='finished', type='storage_delete', status='completed',
            payload={'endpoint_id': 2, 'delete_in_flight': False}))
        await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=storage_http), base_url='http://test') as client:
        listing = await client.get('/storage/endpoints')
        detail = await client.get('/storage/endpoints/2/task')
        assert listing.status_code == detail.status_code == 200
        endpoint = next(endpoint for endpoint in listing.json() if endpoint['id'] == 2)
        assert endpoint['active_task'] == detail.json()['active_task']
        assert endpoint['active_task']['task_id'] == 'draining'
        assert endpoint['active_task']['status'] == status
        assert endpoint['active_task']['progress_percent'] == 50
        assert not endpoint['has_active_sync']
        async with storage_database() as session:
            assert await storage_endpoint_repository.has_cleanup_task(session, 2)
            await task_repository.set_delete_in_flight(session, 'draining', 'drain-token', False)
            await session.commit()
        listing = await client.get('/storage/endpoints')
        detail = await client.get('/storage/endpoints/2/task')
        assert next(endpoint for endpoint in listing.json() if endpoint['id'] == 2)['active_task'] is None
        assert detail.json()['active_task'] is None
        async with storage_database() as session:
            assert not await storage_endpoint_repository.has_cleanup_task(session, 2)


async def test_endpoint_list_and_detail_share_running_priority_and_pending_order(storage_http, storage_database):
    now = datetime.now(timezone.utc)
    async with storage_database() as session:
        session.sync.add_all([
            Task(id='old-pending', type='storage_sync', status='pending', created_at=now - timedelta(seconds=3),
                 payload={'source_endpoint_id': 2, 'target_endpoint_id': 3, 'batch_size': 10}),
            Task(id='new-pending', type='storage_sync', status='pending', created_at=now - timedelta(seconds=2),
                 payload={'source_endpoint_id': 2, 'target_endpoint_id': 3, 'batch_size': 10}),
            Task(id='running-progress', type='storage_sync', status='processing', created_at=now,
                 payload={'source_endpoint_id': 2, 'target_endpoint_id': 3, 'batch_size': 10}, result={'success_count': 5}),
        ])
        await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=storage_http), base_url='http://test') as client:
        for expected in ['running-progress', 'old-pending']:
            listing = await client.get('/storage/endpoints')
            for endpoint in listing.json():
                if endpoint['id'] not in (2, 3):
                    continue
                detail = await client.get(f"/storage/endpoints/{endpoint['id']}/task")
                assert endpoint['active_task'] == detail.json()['active_task']
                assert endpoint['active_task']['task_id'] == expected
                assert endpoint['has_active_sync']
                if expected == 'running-progress':
                    assert endpoint['active_task']['progress_percent'] == 50
            if expected == 'running-progress':
                async with storage_database() as session:
                    await task_repository.update_status(session, expected, 'completed')
                    await session.commit()


async def test_cleanup_keeps_upload_settings_and_manual_connection_test_repairs_health(storage_http, storage_database, monkeypatch):
    monkeypatch.setattr(storage_service, 'upload_to_endpoint', AsyncMock(return_value=True))
    monkeypatch.setattr(storage_service, 'delete_from_endpoint', AsyncMock(return_value=True))
    async with storage_database() as session:
        endpoint = await session.get(StorageEndpoint, 2)
        endpoint.is_healthy = False
        endpoint.health_check_error = 'previous test failed'
        session.add(Task(id='old-drain', type='storage_delete', status='failed', run_token='old-token',
                         payload={'endpoint_id': 2, 'delete_in_flight': True}))
        await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=storage_http), base_url='http://test') as client:
        response = await client.post('/storage/endpoints/2/force-cleanup', json={
            'confirm': True, 'endpoint_name': 'primary', 'remove_endpoint': False})
        assert response.status_code == 200
        assert '端点配置保持不变' in response.json()['message']
        assert (await client.put('/storage/endpoints/2', json={'is_enabled': True})).status_code == 200
        async with storage_database() as session:
            endpoint, error = await storage_endpoint_repository.resolve_upload_endpoint(session, 2)
            assert endpoint and not error
            assert not endpoint.is_healthy and endpoint.is_default_upload
            default, error = await storage_endpoint_repository.resolve_upload_endpoint(session)
            assert default is not None and default.id == 2 and not error
            await image_location_repository.create(session, image_id=3, endpoint_id=2,
                expected_generation=1, object_key='restored.jpg')
            await session.commit()
            assert not await image_location_repository.get_readable_by_image_ids(session, [3])
        response = await client.post('/storage/endpoints/2/test')
        assert response.status_code == 200 and response.json()['success']
        async with storage_database() as session:
            endpoint = await session.get(StorageEndpoint, 2)
            assert endpoint.is_healthy and endpoint.health_check_error is None
            assert endpoint.is_default_upload
            assert len(await image_location_repository.get_readable_by_image_ids(session, [3])) == 1
        assert (await client.post('/storage/endpoints/2/set-default')).status_code == 200
        async with storage_database() as session:
            default, error = await storage_endpoint_repository.resolve_upload_endpoint(session)
            assert default.id == 2 and not error
            old = await session.get(Task, 'old-drain')
            assert old.run_token is None and not old.payload['delete_in_flight']
    storage_service.upload_to_endpoint.assert_awaited_once()
    storage_service.delete_from_endpoint.assert_awaited_once()


@pytest.mark.parametrize('lease,interval', [(60, 15), (10, 10 / 3)])
async def test_heartbeat_uses_slow_interval_without_holding_connection(storage_database, monkeypatch, caplog, lease, interval):
    control_module = import_module('imgtag.services.storage_task_control')
    control = control_module.StorageTaskControl()
    caplog.set_level('DEBUG', logger=control_module.__name__)
    monkeypatch.setattr(control_module.settings, 'STORAGE_TASK_LEASE_SECONDS', lease)
    finish = asyncio.Event()
    connections = 0
    @asynccontextmanager
    async def sessions():
        nonlocal connections
        async with storage_database() as session:
            connections += 1
            try:
                yield session
            finally:
                connections -= 1
    monkeypatch.setattr(control_module, 'async_session_maker', sessions)
    async with storage_database() as session:
        session.add(Task(id='heartbeat-test', type='storage_sync', status='pending', payload={}))
        await session.commit()
    original_wait = asyncio.wait
    original_heartbeat = task_repository.heartbeat_storage_task
    waits = []
    async def wait(children, timeout):
        assert connections == 0
        waits.append(timeout)
        assert timeout == pytest.approx(interval)
        result = await original_wait(children, timeout=0.01 if len(waits) == 1 else 1)
        if not result[0]:
            # 模拟等待经过的时间，不让回归测试真实等待 15 秒。
            runtime = import_module('imgtag.core.storage_runtime')
            for attempt in list(runtime.storage_progress):
                runtime.storage_progress[attempt] -= timeout
        return result
    async def heartbeat(*args):
        alive = await original_heartbeat(*args)
        finish.set()
        return alive
    monkeypatch.setattr(asyncio, 'wait', wait)
    heartbeat_mock = AsyncMock(side_effect=heartbeat)
    monkeypatch.setattr(task_repository, 'heartbeat_storage_task', heartbeat_mock)
    async def operation():
        await finish.wait()
        async with storage_database() as session:
            await task_repository.update_status(session, 'heartbeat-test', 'completed')
            await session.commit()
    await asyncio.wait_for(control.run('heartbeat-test', operation), 2)
    heartbeat_mock.assert_awaited_once()
    assert len(waits) == 2 and connections == 0
    assert '存储任务近期无新进度，已补写数据库心跳: task_id=heartbeat-test' in caplog.text
    assert '存储任务执行器已退出，心跳检查已停止: task_id=heartbeat-test' in caplog.text
    async with storage_database() as session:
        task = await session.get(Task, 'heartbeat-test')
        assert task.status == 'completed'
        assert task.run_token not in caplog.text


@pytest.mark.parametrize('pending', [False, True])
async def test_recovery_debug_logs_report_idle_and_dispatched_tasks(storage_database, monkeypatch, caplog, pending):
    recovery = import_module('imgtag.services.storage_task_recovery')
    caplog.set_level('DEBUG', logger=recovery.__name__)
    monkeypatch.setattr(recovery, 'async_session_maker', storage_database)
    if pending:
        async with storage_database() as session:
            session.add(Task(id='recover-debug', type='storage_sync', status='pending', payload={}))
            await session.commit()
    runner = AsyncMock()
    monkeypatch.setattr(recovery.storage_sync_service, '_process_sync_task', runner)
    original_sleep = asyncio.sleep
    async def end_cycle(waiter, timeout):
        assert timeout == 300
        waiter.close()
        await original_sleep(0)
        raise asyncio.CancelledError
    monkeypatch.setattr(asyncio, 'wait_for', end_cycle)
    with pytest.raises(asyncio.CancelledError):
        await recovery.recover_storage_tasks()
    assert '存储任务调度检查开始（读取数据库）: trigger=应用启动' in caplog.text
    count = int(pending)
    assert f'存储任务调度检查完成，查到待执行或待恢复任务 {count} 个，新提交调度 {count} 个；等待事件通知或 300 秒兜底检查' in caplog.text
    if pending:
        runner.assert_awaited_once_with('recover-debug')
    else:
        runner.assert_not_awaited()


async def test_event_scheduler_idle_then_enqueue_and_completion_drain_queue(storage_database, monkeypatch):
    recovery = import_module('imgtag.services.storage_task_recovery')
    runtime = import_module('imgtag.core.storage_runtime')
    monkeypatch.setattr(recovery, 'async_session_maker', storage_database)
    service = recovery.storage_sync_service
    first_started, second_done, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    first_scan, observed_waiter = asyncio.Event(), asyncio.Event()
    scans, started = [], []
    query = task_repository.get_recoverable_storage_tasks
    async def inspect(session):
        result = await query(session)
        scans.append(len(result))
        first_scan.set()
        if len(result) and first_started.is_set():
            observed_waiter.set()
        return result
    monkeypatch.setattr(task_repository, 'get_recoverable_storage_tasks', inspect)
    async def process(task_id):
        started.append(task_id)
        if len(started) == 1:
            first_started.set()
            await release.wait()
        await service._update_progress(task_id, 1, 0, [], final=True, completed_ids={len(started)})
        if len(started) == 2:
            second_done.set()
    monkeypatch.setattr(service, '_do_sync_task', process)
    scheduler = asyncio.create_task(recovery.recover_storage_tasks())
    try:
        await asyncio.wait_for(first_scan.wait(), 1)
        await asyncio.sleep(0.01)
        assert scans == [0]  # 空闲等待没有反复查库。
        first = (await service.start_batch_sync(2, 3, [1], automatic_backup=True))[0]
        await asyncio.wait_for(first_started.wait(), 1)
        second = (await service.start_batch_sync(2, 3, [2], automatic_backup=True))[0]
        await asyncio.wait_for(observed_waiter.wait(), 1)
        assert started == [first]
        release.set()
        await asyncio.wait_for(second_done.wait(), 1)  # 无需等待五分钟兜底。
        await asyncio.sleep(0.02)
        assert started == [first, second]
        async with storage_database() as session:
            assert (await session.get(Task, first)).status == 'completed'
            assert (await session.get(Task, second)).status == 'completed'
        assert not runtime.storage_progress
    finally:
        release.set()
        scheduler.cancel()
        await asyncio.gather(scheduler, return_exceptions=True)
    assert runtime.storage_wakeup is None


async def test_notification_during_scan_is_not_lost_and_burst_is_coalesced(storage_database, monkeypatch):
    recovery = import_module('imgtag.services.storage_task_recovery')
    runtime = import_module('imgtag.core.storage_runtime')
    monkeypatch.setattr(recovery, 'async_session_maker', storage_database)
    scanning, release, dispatched = asyncio.Event(), asyncio.Event(), asyncio.Event()
    query = task_repository.get_recoverable_storage_tasks
    count = 0
    async def inspect(session):
        nonlocal count
        rows = await query(session)
        count += 1
        if count == 1:
            scanning.set()
            await release.wait()
        return rows
    monkeypatch.setattr(task_repository, 'get_recoverable_storage_tasks', inspect)
    runner = AsyncMock(side_effect=lambda task_id: dispatched.set())
    monkeypatch.setattr(recovery.storage_sync_service, '_process_sync_task', runner)
    scheduler = asyncio.create_task(recovery.recover_storage_tasks())
    try:
        await asyncio.wait_for(scanning.wait(), 1)
        async with storage_database() as session:
            session.add(Task(id='scan-race', type='storage_sync', status='pending', payload={}))
            await session.commit()
        for _ in range(100):
            runtime.notify_storage_tasks()
        release.set()
        await asyncio.wait_for(dispatched.wait(), 1)
        await asyncio.sleep(0.01)
        assert count == 2
        runner.assert_awaited_once_with('scan-race')
    finally:
        release.set()
        scheduler.cancel()
        await asyncio.gather(scheduler, return_exceptions=True)


async def test_fallback_scan_recovers_task_that_expires_without_notification(storage_database, monkeypatch):
    recovery = import_module('imgtag.services.storage_task_recovery')
    monkeypatch.setattr(recovery, 'async_session_maker', storage_database)
    async with storage_database() as session:
        session.add(Task(id='foreign-worker', type='storage_sync', status='processing', run_token='old',
            heartbeat_at=datetime.now(timezone.utc), payload={}))
        await session.commit()
    original_sleep = asyncio.sleep
    waits = 0
    async def advance(waiter, timeout):
        nonlocal waits
        waiter.close()
        assert timeout == 300
        waits += 1
        if waits == 1:
            async with storage_database() as session:
                (await session.get(Task, 'foreign-worker')).heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=6)
                await session.commit()
            raise asyncio.TimeoutError
        await original_sleep(0)
        raise asyncio.CancelledError
    runner = AsyncMock()
    monkeypatch.setattr(recovery.storage_sync_service, '_process_sync_task', runner)
    monkeypatch.setattr(asyncio, 'wait_for', advance)
    with pytest.raises(asyncio.CancelledError):
        await recovery.recover_storage_tasks()
    assert waits == 2
    runner.assert_awaited_once_with('foreign-worker')


async def test_progress_heartbeat_avoids_extra_writes_until_progress_stalls(storage_database, monkeypatch, caplog):
    control_module = import_module('imgtag.services.storage_task_control')
    runtime = import_module('imgtag.core.storage_runtime')
    control = control_module.StorageTaskControl()
    caplog.set_level('DEBUG', logger=control_module.__name__)
    clock = [0.0]
    monkeypatch.setattr(control_module, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(runtime, 'monotonic', lambda: clock[0])
    async with storage_database() as session:
        session.add(Task(id='progress-heartbeat', type='storage_sync', status='pending', payload={}))
        await session.commit()
    finish = asyncio.Event()
    query = task_repository.heartbeat_storage_task
    async def heartbeat(*args):
        result = await query(*args)
        finish.set()
        return result
    heartbeat_mock = AsyncMock(side_effect=heartbeat)
    monkeypatch.setattr(task_repository, 'heartbeat_storage_task', heartbeat_mock)
    original_wait = asyncio.wait
    waits = 0
    async def simulate(children, timeout):
        nonlocal waits
        waits += 1
        if waits <= 2:
            clock[0] += 10
            await sync_module.storage_sync_service._update_progress('progress-heartbeat', waits, 0, [], completed_ids={waits})
            async with storage_database() as session:
                task = await session.get(Task, 'progress-heartbeat')
                assert task.heartbeat_at is not None and task.result['success_count'] == waits
            assert heartbeat_mock.await_count == 0
            return set(), children
        if waits == 3:
            clock[0] += 20
            return set(), children
        return await original_wait(children, timeout=1)
    monkeypatch.setattr(asyncio, 'wait', simulate)
    await asyncio.wait_for(control.run('progress-heartbeat', finish.wait), 2)
    assert waits == 4
    assert caplog.text.count('跳过额外心跳写入（本次不访问数据库）: task_id=progress-heartbeat') == 2
    assert '已补写数据库心跳: task_id=progress-heartbeat' in caplog.text
    heartbeat_mock.assert_awaited_once()
    assert not runtime.storage_progress


async def test_failed_progress_commit_does_not_extend_local_liveness(monkeypatch):
    runtime = import_module('imgtag.core.storage_runtime')
    attempt = ('rollback-progress', 'old-token')
    runtime.storage_progress[attempt] = 0
    context = storage_attempt.set(attempt)
    @asynccontextmanager
    async def sessions():
        yield SimpleNamespace(commit=AsyncMock(side_effect=RuntimeError('synthetic commit failure')))
    monkeypatch.setattr(sync_module, 'async_session_maker', sessions)
    monkeypatch.setattr(task_repository, 'update_status', AsyncMock(return_value=True))
    try:
        with pytest.raises(RuntimeError):
            await sync_module.storage_sync_service._update_progress('rollback-progress', 1, 0, [])
        assert runtime.storage_progress[attempt] == 0
    finally:
        runtime.storage_progress.pop(attempt)
        storage_attempt.reset(context)


@pytest.mark.parametrize('terminal', [False, True])
async def test_delete_drain_wakes_scheduler_only_when_terminal_occupation_released(storage_database, monkeypatch, terminal):
    runtime = import_module('imgtag.core.storage_runtime')
    service = StorageService()
    wakeup = asyncio.Event()
    monkeypatch.setattr(runtime, 'storage_wakeup', wakeup)
    monkeypatch.setattr(storage_module, 'async_session_maker', storage_database)
    ready, release = asyncio.Event(), Event()
    loop = asyncio.get_running_loop()
    class Client:
        def delete_object(self, **kwargs):
            loop.call_soon_threadsafe(ready.set)
            assert release.wait(3)
        def close(self): pass
    monkeypatch.setattr(storage_module.boto3, 'client', Mock(return_value=Client()))
    async with storage_database() as session:
        endpoint = await session.get(StorageEndpoint, 2)
        session.add(Task(id='drain-wakeup', type='storage_delete', status='processing', run_token='token',
                         payload={'endpoint_id': 2}))
        await session.commit()
    context = storage_attempt.set(('drain-wakeup', 'token'))
    deletion = asyncio.create_task(service.delete_from_endpoint('one.jpg', endpoint))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert not wakeup.is_set()
        if terminal:
            async with storage_database() as session:
                await task_repository.update_status(session, 'drain-wakeup', 'cancelled')
                await session.commit()
        release.set()
        assert await asyncio.wait_for(deletion, 1)
        assert wakeup.is_set() is terminal
    finally:
        release.set()
        await asyncio.gather(deletion, *service._pending_deletes, return_exceptions=True)
        storage_attempt.reset(context)
        service.close()


@pytest.mark.parametrize('enabled', [False, True])
async def test_local_cleanup_preserves_endpoint_settings_and_cancels_conflicts(storage_database, enabled):
    async with storage_database() as session:
        endpoint = await session.get(StorageEndpoint, 2)
        endpoint.is_enabled = enabled
        endpoint.auto_sync_enabled = True
        endpoint.sync_from_endpoint_id = 1
        endpoint.read_priority = 12
        endpoint.read_weight = 4
        session.add(Task(id='conflicting-sync', type='storage_sync', status='processing', run_token='old-token',
                         payload={'source_endpoint_id': 2, 'target_endpoint_id': 3}))
        await session.commit()
        fields = ['is_enabled', 'is_default_upload', 'auto_sync_enabled', 'sync_from_endpoint_id',
                  'read_priority', 'read_weight', 'role', 'endpoint_url', 'bucket_name']
        before = {key: getattr(endpoint, key) for key in fields}
        await storage_management_service.force_cleanup(session, 2, remove_endpoint=False)
    async with storage_database() as session:
        endpoint = await session.get(StorageEndpoint, 2)
        assert {key: getattr(endpoint, key) for key in fields} == before
        assert endpoint.operation_generation == 1
        assert await image_location_repository.count_by_endpoint(session, 2) == 0
        task = await session.get(Task, 'conflicting-sync')
        assert task.status == 'cancelled' and task.run_token is None
        backup = await session.get(StorageEndpoint, 3)
        assert backup.sync_from_endpoint_id == 2 and backup.auto_sync_enabled
