import hashlib
from contextlib import asynccontextmanager
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from imgtag.api.endpoints import storage_endpoints
from imgtag.core.config import Settings
from imgtag.models.storage_endpoint import StorageEndpoint
from imgtag.schemas.storage import EndpointCreate, EndpointUpdate
from imgtag.services.storage_service import StorageService

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
    session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    endpoint = StorageEndpoint(
        id=2, name='storage', provider='s3', endpoint_url='https://storage.example',
        region='auto', bucket_name='photos', path_style=True, path_prefix='images',
        public_url_prefix='https://cdn.example', public_url_include_bucket=True,
        role='primary', is_enabled=True, is_default_upload=False, auto_sync_enabled=False,
        read_priority=100, read_weight=1, is_healthy=True,
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
    monkeypatch.setattr(storage_endpoints.image_location_repository, 'count_by_endpoint', AsyncMock(return_value=4))
    monkeypatch.setattr(storage_endpoints.task_repository, 'get_active_for_endpoint', AsyncMock(return_value=None))
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
