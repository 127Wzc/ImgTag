import hashlib
from contextlib import asynccontextmanager
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from imgtag.core.config import Settings
from imgtag.services.storage_service import StorageService

sync_module = import_module("imgtag.services.storage_sync_service")


def test_pool_settings_from_environment(monkeypatch):
    monkeypatch.setenv('DB_POOL_SIZE', '3')
    monkeypatch.setenv('DB_MAX_OVERFLOW', '1')
    monkeypatch.setenv('DB_POOL_PRE_PING', 'false')
    config = Settings(_env_file=None)
    assert (config.DB_POOL_SIZE, config.DB_MAX_OVERFLOW, config.DB_POOL_PRE_PING) == (3, 1, False)
    monkeypatch.setenv('DB_POOL_SIZE', '0')
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


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
