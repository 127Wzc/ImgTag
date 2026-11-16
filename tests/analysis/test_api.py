"""图片分析接口：单次补充要求、权限与任务响应契约。"""

import asyncio
import io
import json
import time
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from PIL import Image as PillowImage
from pydantic import ValidationError
import httpx
import pytest
import starlette.formparsers as form_parsers

from imgtag.api.endpoints import config as config_api, external, images, mcp, queue, system, tasks as task_api
from imgtag.api import dependencies as api_dependencies
from imgtag.api.endpoints.auth import get_current_user
from imgtag.core.config import settings
from imgtag.core.config_cache import config_cache
from imgtag.core.config_defaults import parse_max_upload_size
from imgtag.core.exceptions import EmbeddingAPIError
from imgtag.core.storage_runtime import StorageOperationStopped
from imgtag.main import unhandled_exception_handler
from imgtag.models.task import Task
from imgtag.schemas.image import ImageCreateByUrl, TagWithSource
from imgtag.schemas.task import Task as TaskResponse
from imgtag.services import external_image_service as external_upload
from imgtag.services.storage_service import StorageService
from imgtag.services.task_service import task_service
from imgtag.services.upload_service import UploadService, upload_service


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


@pytest.mark.parametrize('single', [False, True])
@pytest.mark.parametrize('value', ['', '0', '4', '2.5', 'invalid'])
async def test_gif_frame_config_rejects_invalid_values_before_writing(monkeypatch, single, value):
    from imgtag.api.endpoints import config as config_api

    app = FastAPI()
    app.include_router(config_api.router, prefix='/config')
    app.dependency_overrides[get_current_user] = lambda: {'id': 1, 'role': 'admin'}
    app.dependency_overrides[config_api.get_async_session] = lambda: object()
    batch_write = AsyncMock()
    single_write = AsyncMock()
    monkeypatch.setattr(config_api.config_repository, 'update_multiple', batch_write)
    monkeypatch.setattr(config_api.config_repository, 'set_value', single_write)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        if single:
            response = await client.put('/config/vision_gif_frame_count', params={'value': value})
        else:
            response = await client.put('/config/', json={'configs': {'vision_gif_frame_count': value}})
    assert response.status_code == 400
    batch_write.assert_not_awaited()
    single_write.assert_not_awaited()


@pytest.mark.parametrize('model', [ImageCreateByUrl, external.ExternalImageCreate, mcp.AddImageArguments])
async def test_url_and_mcp_upload_inputs_support_bounded_optional_instructions(model):
    assert model(image_url='https://example.com/a.png', analysis_instructions='描述图中文字').analysis_instructions == '描述图中文字'
    assert model(image_url='https://example.com/a.png').analysis_instructions == ''
    with pytest.raises(ValidationError):
        model(image_url='https://example.com/a.png', analysis_instructions='字' * 6001)


@pytest.mark.parametrize('model', [ImageCreateByUrl, external.ExternalImageCreate])
def test_upload_instructions_accept_null_but_reject_invalid_types(model):
    assert model(image_url='https://example.com/a.png', analysis_instructions=None).analysis_instructions == ''
    for invalid in [False, 123, [], {}]:
        with pytest.raises(ValidationError):
            model(image_url='https://example.com/a.png', analysis_instructions=invalid)


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


@pytest.fixture
def upload_dependencies(monkeypatch):
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    endpoint = SimpleNamespace(id=1, name='local', provider='local', operation_generation=7)
    image = SimpleNamespace(id=18, description='已有描述')
    monkeypatch.setattr(images.storage_endpoint_repository, 'resolve_upload_endpoint', AsyncMock(return_value=(endpoint, None)))
    monkeypatch.setattr(images.storage_endpoint_repository, 'get_by_id', AsyncMock(return_value=endpoint))
    monkeypatch.setattr(upload_service, 'get_max_upload_size', AsyncMock(side_effect=lambda **kwargs: settings.MAX_UPLOAD_SIZE))
    monkeypatch.setattr(images.upload_service, 'save_remote_image', AsyncMock(return_value=('a.png', '/uploads/a.png', b'image')))
    monkeypatch.setattr(images.upload_service, 'fetch_remote_image', AsyncMock(return_value=(b'image', 'image/png')))
    monkeypatch.setattr(images.upload_service, 'extract_image_dimensions', Mock(return_value=(None, None)))
    monkeypatch.setattr(images.storage_service, 'upload_to_endpoint', AsyncMock(return_value=True))
    monkeypatch.setattr(images.storage_service, 'get_read_url', AsyncMock(return_value='/uploads/a.png'))
    monkeypatch.setattr(images.image_repository, 'create_image', AsyncMock(return_value=image))
    monkeypatch.setattr(images.image_repository, 'get_image_tags_with_source', AsyncMock(return_value=[]))
    monkeypatch.setattr(images.image_location_repository, 'create', AsyncMock())
    monkeypatch.setattr(images.image_tag_repository, 'set_image_tags', AsyncMock())
    monkeypatch.setattr(images.image_tag_repository, 'add_tag_to_image', AsyncMock())
    monkeypatch.setattr(images.tag_repository, 'get_name_levels', AsyncMock(return_value={'已有标签': 2}))
    monkeypatch.setattr(images.tag_repository, 'get_or_create', AsyncMock(return_value=SimpleNamespace(id=9)))
    monkeypatch.setattr(images, 'trigger_backup_for_image', AsyncMock())
    monkeypatch.setattr(external_upload, 'trigger_backup_for_image', AsyncMock())
    monkeypatch.setattr(external_upload, 'get_category_code_cached', AsyncMock(return_value='landscape'))
    monkeypatch.setattr(images.embedding_service, 'save_embedding_for_image', AsyncMock())
    monkeypatch.setattr(images.task_queue, 'add_tasks', AsyncMock())
    monkeypatch.setattr(images.task_queue, '_running', True)
    return session


@pytest.fixture
def image_file():
    content = io.BytesIO()
    PillowImage.new('RGB', (16, 12), 'red').save(content, format='PNG')
    return content.getvalue()


@pytest.fixture
def external_upload_api(upload_dependencies):
    app = FastAPI()
    app.include_router(external.router, prefix='/external')
    user = {'id': 1, 'role': 'admin', 'permissions': 15}
    app.dependency_overrides[external.require_api_key] = lambda: user
    app.dependency_overrides[external.get_async_session] = lambda: upload_dependencies
    return app, user


async def test_external_file_upload_preserves_metadata_and_uses_detected_format(
    external_upload_api, upload_dependencies, image_file,
):
    app, _ = external_upload_api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/external/images',
            files={'file': ('photo.jpg', image_file, 'application/octet-stream')},
            data={'tags': ['已有标签', '手动标签'], 'description': '手动描述', 'category_id': '7',
                  'endpoint_id': '1', 'auto_analyze': 'false', 'is_public': 'false'})
    await asyncio.sleep(0)
    assert response.status_code == 200, response.text
    assert response.json()['original_url'] is None
    assert (response.json()['width'], response.json()['height']) == (16, 12)
    external_upload.upload_service.save_remote_image.assert_not_awaited()
    external_upload.storage_endpoint_repository.resolve_upload_endpoint.assert_awaited_once_with(upload_dependencies, 1)
    values = external_upload.image_repository.create_image.await_args.kwargs
    assert values['file_type'] == 'png' and values['original_url'] is None and values['is_public'] is False
    assert values['uploaded_by'] == 1 and values['description'] == '手动描述'
    assert external_upload.storage_service.upload_to_endpoint.await_args.args[0] == image_file
    external_upload.image_tag_repository.set_image_tags.assert_awaited_once_with(
        upload_dependencies, 18, ['已有标签', '手动标签'], source='user', added_by=1)
    assert external_upload.image_location_repository.create.await_args.kwargs['sync_status'] == 'synced'
    assert external_upload.image_location_repository.create.await_args.kwargs['expected_generation'] == 7
    external_upload.get_category_code_cached.assert_awaited_once_with(upload_dependencies, 7)
    upload_dependencies.commit.assert_awaited_once()
    external_upload.trigger_backup_for_image.assert_awaited_once_with(18, 1)
    external_upload.task_queue.add_tasks.assert_not_awaited()


@pytest.mark.parametrize('permissions, data', [
    (0, {'auto_analyze': 'false'}),
    (1, {'auto_analyze': 'true'}),
    (1, {'tags': '新标签', 'auto_analyze': 'false'}),
])
async def test_external_file_upload_checks_permissions_before_reading_file(
    external_upload_api, image_file, monkeypatch, permissions, data,
):
    app, user = external_upload_api
    user.update(role='user', permissions=permissions)
    read = AsyncMock()
    monkeypatch.setattr(external_upload, '_read_uploaded_image', read)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/external/images', data=data,
            files={'file': ('photo.png', image_file, 'image/png')})
    assert response.status_code == 403
    read.assert_not_awaited()
    external_upload.image_repository.create_image.assert_not_awaited()
    external_upload.storage_service.upload_to_endpoint.assert_not_awaited()


@pytest.mark.parametrize('kind, status', [
    ('missing', 422), ('empty', 400), ('oversized', 413), ('extension', 415), ('invalid', 400),
])
async def test_external_file_upload_rejects_invalid_files_without_side_effects(
    external_upload_api, upload_dependencies, image_file, monkeypatch, kind, status,
):
    app, _ = external_upload_api
    name, content = 'photo.png', image_file
    if kind == 'empty':
        content = b''
    elif kind == 'oversized':
        monkeypatch.setattr(settings, 'MAX_UPLOAD_SIZE', len(image_file) - 1)
    elif kind == 'extension':
        name = 'photo.html'
    elif kind == 'invalid':
        content = b'not an image'
    files = ([('auto_analyze', (None, 'false'))] if kind == 'missing' else
             {'file': (name, content, 'image/png')})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/external/images', data={'auto_analyze': 'false'}, files=files)
    assert response.status_code == status, response.text
    external_upload.image_repository.create_image.assert_not_awaited()
    external_upload.storage_service.upload_to_endpoint.assert_not_awaited()
    external_upload.task_queue.add_tasks.assert_not_awaited()
    upload_dependencies.commit.assert_not_awaited()


@pytest.mark.parametrize('content_length', [None, '1'])
async def test_external_multipart_stops_receiving_and_closes_spool_on_limit(
    external_upload_api, upload_dependencies, monkeypatch, tmp_path, content_length,
):
    app, _ = external_upload_api
    max_size = 2 * 1024 * 1024
    monkeypatch.setattr(upload_service, 'get_max_upload_size', AsyncMock(return_value=max_size))
    consumed, written = 0, 0
    temporary = []
    original_spool = form_parsers.SpooledTemporaryFile
    original_write = form_parsers.UploadFile.write
    def spool(*args, **kwargs):
        file = original_spool(*args, **kwargs, dir=tmp_path)
        temporary.append(file)
        return file
    async def write(file, data):
        nonlocal written
        written += len(data)
        await original_write(file, data)
    monkeypatch.setattr(form_parsers, 'SpooledTemporaryFile', spool)
    monkeypatch.setattr(form_parsers.UploadFile, 'write', write)
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal consumed
            yield b'--limit\r\nContent-Disposition: form-data; name="file"; filename="photo.png"\r\n\r\n'
            for _ in range(128):
                consumed += 1
                yield b'x' * 65536
            yield b'\r\n--limit--\r\n'
    headers = {'Content-Type': 'multipart/form-data; boundary=limit'}
    if content_length is not None:
        headers['Content-Length'] = content_length
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/external/images', headers=headers, content=Body())
    assert response.status_code == 413, response.text
    assert consumed == 33 and written == max_size
    assert temporary and all(file.closed for file in temporary)
    external_upload.image_repository.create_image.assert_not_awaited()
    external_upload.storage_service.upload_to_endpoint.assert_not_awaited()
    upload_dependencies.commit.assert_not_awaited()


async def test_external_multipart_does_not_read_body_before_authentication(external_upload_api, monkeypatch):
    app, _ = external_upload_api
    app.dependency_overrides.pop(external.require_api_key)
    consumed = 0
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal consumed
            consumed += 1
            yield b'not consumed'
    parse = AsyncMock()
    monkeypatch.setattr(upload_service, 'parse_upload_form', parse)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/external/images', content=Body(),
            headers={'Content-Type': 'multipart/form-data; boundary=limit'})
    assert response.status_code == 401
    assert consumed == 0
    parse.assert_not_awaited()


@pytest.mark.parametrize('extra', [-1, 0, 1])
async def test_external_multipart_limit_counts_file_without_form_framing(
    external_upload_api, image_file, monkeypatch, extra,
):
    app, _ = external_upload_api
    monkeypatch.setattr(upload_service, 'get_max_upload_size', AsyncMock(return_value=len(image_file) + extra))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/external/images', data={'auto_analyze': 'false'},
            files={'file': ('photo.png', image_file, 'image/png')})
    assert response.status_code == (413 if extra < 0 else 200), response.text


async def test_external_multipart_rejects_multiple_files_and_malformed_parts(external_upload_api, image_file):
    app, _ = external_upload_api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        multiple = await client.post('/external/images', files=[
            ('file', ('one.png', image_file)), ('file', ('two.png', image_file)),
        ])
        malformed = await client.post('/external/images', content=b'body',
            headers={'Content-Type': 'multipart/form-data'})
        bad_boundary = await client.post('/external/images', content=b'broken',
            headers={'Content-Type': 'multipart/form-data; boundary=expected'})
    assert multiple.status_code == malformed.status_code == bad_boundary.status_code == 400
    external_upload.image_repository.create_image.assert_not_awaited()


async def test_external_post_openapi_documents_both_content_types(external_upload_api):
    app, _ = external_upload_api
    schema = app.openapi()['paths']['/external/images']['post']['requestBody']['content']
    assert set(schema) == {'application/json', 'multipart/form-data'}
    assert 'image_url' in schema['application/json']['schema']['required']
    assert schema['multipart/form-data']['schema']['required'] == ['file']
    assert schema['multipart/form-data']['schema']['properties']['file']['format'] == 'binary'


async def test_admin_upload_size_change_applies_to_form_url_and_public_config(
    external_upload_api, image_file, monkeypatch, tmp_path,
):
    app, _ = external_upload_api
    app.include_router(config_api.router, prefix='/config')
    app.include_router(system.router, prefix='/system')
    app.dependency_overrides[config_api.require_admin] = lambda: {'id': 1, 'role': 'admin'}
    database_config = {'max_upload_size': '1'}
    monkeypatch.setattr(config_cache, '_cache', {})
    monkeypatch.setattr(config_cache, '_cache_time', 0)
    async def load(session=None):
        config_cache._cache = dict(database_config)
        config_cache._cache_time = time.time()
    async def save(session, values):
        database_config.update(values)
        return True
    monkeypatch.setattr(config_cache, '_load_snapshot', load)
    monkeypatch.setattr(config_api.config_repository, 'update_multiple', AsyncMock(side_effect=save))
    monkeypatch.setattr(upload_service, 'get_max_upload_size', UploadService.get_max_upload_size.__get__(upload_service))
    monkeypatch.setattr(upload_service, 'save_remote_image', UploadService.save_remote_image.__get__(upload_service))
    monkeypatch.setattr(upload_service, 'fetch_remote_image', UploadService.fetch_remote_image.__get__(upload_service))
    monkeypatch.setattr(upload_service, '_upload_dir', tmp_path)
    content = image_file + b'x' * (1024 * 1024)
    original_client = httpx.AsyncClient
    async def remote(request):
        return httpx.Response(200, headers={'content-type': 'image/png'}, content=content)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original_client(
        transport=httpx.MockTransport(remote), **kwargs))
    async with original_client(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for expected in (413, 200):
            form = await client.post('/external/images', data={'auto_analyze': 'false'},
                files={'file': ('photo.png', content, 'image/png')})
            url = await client.post('/external/images', json={
                'image_url': 'http://images.example/photo.png', 'auto_analyze': False,
            })
            assert form.status_code == url.status_code == expected, (form.text, url.text)
            if expected == 413:
                external_upload.image_repository.create_image.assert_not_awaited()
                saved = await client.put('/config/', json={'configs': {'max_upload_size': '2'}})
                assert saved.status_code == 200
        public = await client.get('/system/config')
        assert public.status_code == 200 and public.json()['max_upload_size'] == 2 * 1024 * 1024
    assert external_upload.image_repository.create_image.await_count == 2


@pytest.mark.parametrize('single', [False, True])
@pytest.mark.parametrize('value', ['0', '-1', 'nan', 'inf', 'invalid'])
async def test_admin_upload_size_rejects_invalid_values_before_saving(upload_dependencies, monkeypatch, single, value):
    app = FastAPI()
    app.include_router(config_api.router, prefix='/config')
    app.dependency_overrides[config_api.require_admin] = lambda: {'id': 1, 'role': 'admin'}
    app.dependency_overrides[config_api.get_async_session] = lambda: upload_dependencies
    batch_write, single_write = AsyncMock(), AsyncMock()
    monkeypatch.setattr(config_api.config_repository, 'update_multiple', batch_write)
    monkeypatch.setattr(config_api.config_repository, 'set_value', single_write)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = (await client.put('/config/max_upload_size', params={'value': value}) if single else
                    await client.put('/config/', json={'configs': {'max_upload_size': value}}))
    assert response.status_code == 400
    batch_write.assert_not_awaited()
    single_write.assert_not_awaited()


def test_admin_upload_size_supports_fractional_megabytes():
    assert parse_max_upload_size('0.5') == 512 * 1024


@pytest.mark.parametrize('data', [
    {'callback_headers': 'not json'}, {'callback_headers': '["value"]'},
    {'callback_headers': '{"x-api-key":123}'}, {'endpoint_id': 'invalid'},
    {'auto_analyze': 'invalid'}, {'analysis_instructions': '字' * 6001},
])
async def test_external_file_upload_validates_form_fields_before_saving(external_upload_api, image_file, data):
    app, _ = external_upload_api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/external/images', data=data,
            files={'file': ('photo.png', image_file, 'image/png')})
    assert response.status_code == 422, response.text
    external_upload.image_repository.create_image.assert_not_awaited()
    external_upload.storage_service.upload_to_endpoint.assert_not_awaited()


async def test_external_file_upload_forwards_callback_headers_and_analysis(external_upload_api, image_file):
    app, _ = external_upload_api
    headers = {'Authorization': 'Bearer callback-test-token', 'x-api-key': ' callback-test-key '}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/external/images', data={
            'callback_url': 'https://example.com/callback', 'callback_headers': json.dumps(headers),
            'analysis_instructions': '重点描述文字',
        }, files={'file': ('photo.png', image_file, 'image/png')})
    assert response.status_code == 200, response.text
    external_upload.task_queue.add_tasks.assert_awaited_once_with([18],
        callback_url='https://example.com/callback', callback_headers=headers, analysis_instructions='重点描述文字')
    assert 'callback_headers' not in response.json()


@pytest.mark.parametrize('authentication', ['header', 'query'])
async def test_external_file_upload_uses_existing_api_key_authentication(
    external_upload_api, image_file, monkeypatch, authentication,
):
    app, _ = external_upload_api
    app.dependency_overrides.pop(external.require_api_key)
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(api_dependencies.user_repository, 'get_by_api_key', lookup)
    files = {'file': ('photo.png', image_file, 'image/png')}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post('/external/images', files=files)).status_code == 401
        assert (await client.post('/external/images', files=files,
            headers={'X-API-Key': 'invalid-test-key'})).status_code == 401
        lookup.return_value = SimpleNamespace(id=1, username='test', role='user', is_active=True, permissions=1)
        auth = ({'headers': {'X-API-Key': 'valid-test-key'}} if authentication == 'header' else
                {'params': {'api_key': 'valid-test-key'}})
        response = await client.post('/external/images', files=files,
            data={'auto_analyze': 'false'}, **auth)
    assert response.status_code == 200, response.text
    assert lookup.await_args.args[1] == 'valid-test-key'


@pytest.mark.parametrize('stage', ['upload', 'location'])
async def test_external_file_upload_has_no_followup_tasks_after_storage_failure(
    external_upload_api, upload_dependencies, image_file, stage,
):
    app, _ = external_upload_api
    if stage == 'upload':
        external_upload.storage_service.upload_to_endpoint.return_value = False
    else:
        external_upload.image_location_repository.create.side_effect = StorageOperationStopped('端点已被清理')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/external/images', files={'file': ('photo.png', image_file, 'image/png')})
    await asyncio.sleep(0)
    assert response.status_code == 500
    if stage == 'upload':
        external_upload.image_location_repository.create.assert_not_awaited()
    upload_dependencies.commit.assert_not_awaited()
    external_upload.trigger_backup_for_image.assert_not_awaited()
    external_upload.task_queue.add_tasks.assert_not_awaited()


@pytest.mark.parametrize('file_upload', [False, True])
@pytest.mark.parametrize('auto_analyze,instructions,full,expected', [
    (True, '重点描述文字', True, True),
    (True, '', True, False),
    (True, '   ', True, False),
    (True, None, True, False),
    (True, None, False, True),
    (True, '', False, True),
    (False, '重点描述文字', True, False),
    (False, '重点描述文字', False, False),
])
async def test_external_upload_analysis_decision_and_instruction_forwarding(
    monkeypatch, upload_dependencies, image_file, file_upload, auto_analyze, instructions, full, expected,
):
    app = FastAPI()
    app.include_router(external.router, prefix='/external')
    app.dependency_overrides[external.require_api_key] = lambda: {'id': 1, 'role': 'admin'}
    app.dependency_overrides[external.get_async_session] = lambda: upload_dependencies
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        payload = {
            'image_url': 'https://example.com/a.png', 'auto_analyze': auto_analyze,
            'analysis_instructions': instructions, 'callback_url': 'https://example.com/callback',
            'tags': ['已有标签'] if full else [], 'description': '已有描述' if full else '',
        }
        if file_upload:
            payload.pop('image_url')
            payload['auto_analyze'] = str(auto_analyze).lower()
            if instructions is None:
                payload.pop('analysis_instructions')
            response = await client.post('/external/images', data=payload,
                files={'file': ('photo.png', image_file, 'image/png')})
        else:
            response = await client.post('/external/images', json=payload)
    await asyncio.sleep(0)
    assert response.status_code == 200, response.text
    if expected:
        external_upload.task_queue.add_tasks.assert_awaited_once_with(
            [18], callback_url='https://example.com/callback', analysis_instructions=instructions or '',
            callback_headers={},
        )
        external_upload.embedding_service.save_embedding_for_image.assert_not_awaited()
    else:
        external_upload.task_queue.add_tasks.assert_not_awaited()


@pytest.mark.parametrize('headers', [
    pytest.param(None, id='omitted'),
    {}, {'x-api-key': 'callback-test-key'}, {'Authorization': 'Bearer callback-test-token'},
    {'x-api-key': 'callback-test-key', 'Authorization': 'Bearer callback-test-token'},
    {'x-api-key': ' callback-test-key '}, {'Authorization': ' Bearer callback-test-token '},
    {'x-api-key': ' callback-test-key ', 'Authorization': ' Bearer callback-test-token '},
    {'X-Webhook-Secret': ' custom-callback-secret ', 'X-App-Id': 'my-app'},
    {'custom_header': 'custom-value', 'Authorization': 'Bearer callback-test-token'},
    {'Host': 'callback.example'},
    {'authorization': 'Bearer callback-test-token', 'x-custom-auth': 'custom-auth-token'},
    {'x-api-key': ''}, {'x-api-key': '   '}, {'Authorization': ' '},
    {'Bad Header': 'value'}, {'Authorization': 'Bearer test\r\nInjected: value'},
    {'Authorization': '中文'},
    {'Authorization': '\tBearer callback-test-token\t'},
    {'Authorization': '\r\nBearer callback-test-token\r\n'},
    {'Authorization': '\u00a0Bearer callback-test-token\u00a0'},
    {'x-api-key': 'callback-test-key\x7f'}, {'x-api-key': 'callback-test-key\x00'},
    {'': 'value'}, {'Bad:Header': 'value'}, {'X-Header\r\nInjected': 'value'},
    {'中文': 'value'}, {'X-Custom': 'value\r\nInjected: yes'},
])
async def test_external_upload_forwards_callback_authentication(upload_dependencies, headers):
    app = FastAPI()
    app.include_router(external.router, prefix='/external')
    app.dependency_overrides[external.require_api_key] = lambda: {'id': 1, 'role': 'admin'}
    app.dependency_overrides[external.get_async_session] = lambda: upload_dependencies
    payload = {'image_url': 'https://example.com/a.png', 'callback_url': 'https://example.com/callback'}
    if headers is not None:
        payload['callback_headers'] = headers
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/external/images', json=payload,
            headers={'X-API-Key': 'imgtag-test-key', 'Authorization': 'Bearer imgtag-test-token'})
    await asyncio.sleep(0)
    assert response.status_code == 200, response.text
    external_upload.task_queue.add_tasks.assert_awaited_once_with(
        [18], callback_url='https://example.com/callback',
        callback_headers=headers or {}, analysis_instructions='',
    )
    assert 'callback_headers' not in response.json()


@pytest.mark.parametrize('headers', [
    {'x-api-key': 123}, None, 'callback-test-secret',
])
async def test_external_callback_headers_reject_invalid_values_before_upload(upload_dependencies, headers):
    app = FastAPI()
    app.include_router(external.router, prefix='/external')
    app.dependency_overrides[external.require_api_key] = lambda: {'id': 1, 'role': 'admin'}
    app.dependency_overrides[external.get_async_session] = lambda: upload_dependencies
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/external/images', json={
            'image_url': 'https://example.com/a.png',
            'callback_url': 'https://example.com/callback', 'callback_headers': headers,
        })
    assert response.status_code == 422
    external_upload.upload_service.save_remote_image.assert_not_awaited()


async def test_external_custom_instructions_require_ai_permission_before_upload(upload_dependencies):
    app = FastAPI()
    app.include_router(external.router, prefix='/external')
    app.dependency_overrides[external.require_api_key] = lambda: {'id': 1, 'role': 'user', 'permissions': 0}
    app.dependency_overrides[external.get_async_session] = lambda: upload_dependencies
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/external/images', json={
            'image_url': 'https://example.com/a.png', 'tags': ['已有标签'],
            'description': '已有描述', 'analysis_instructions': '重点描述文字',
        })
    assert response.status_code == 403
    external_upload.upload_service.save_remote_image.assert_not_awaited()
    external_upload.image_repository.create_image.assert_not_awaited()
    external_upload.task_queue.add_tasks.assert_not_awaited()


@pytest.mark.parametrize('source', ['external', 'file', 'url'])
@pytest.mark.parametrize('extra', [{}, {'analysis_instructions': ''}, {'analysis_instructions': ' \t\n '}, {'analysis_instructions': None}])
async def test_upload_empty_instructions_preserve_existing_behavior(monkeypatch, upload_dependencies, source, extra):
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.include_router(external.router, prefix='/external')
    user = {'id': 1, 'role': 'user', 'permissions': int(images.Permission.UPLOAD_IMAGE)}
    app.dependency_overrides[get_current_user] = lambda: user if source == 'file' else {'id': 1, 'role': 'admin'}
    app.dependency_overrides[external.require_api_key] = lambda: user
    app.dependency_overrides[images.get_async_session] = lambda: upload_dependencies
    process = AsyncMock()
    monkeypatch.setattr(images, '_post_upload_process', process)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        if source == 'file':
            response = await client.post('/images/upload', files={'file': ('a.png', b'image', 'image/png')},
                data={'auto_analyze': 'true', 'tags': '已有标签', 'description': '已有描述', **extra})
        else:
            path = '/external/images' if source == 'external' else '/images/analyze-url'
            response = await client.post(path, json={
                'image_url': 'https://example.com/a.png', 'auto_analyze': True,
                'tags': ['已有标签'], 'description': '已有描述', **extra,
            })
    await asyncio.sleep(0)
    assert response.status_code == (200 if source == 'external' else 201), response.text
    images.task_queue.add_tasks.assert_not_awaited()
    if source == 'external':
        images.embedding_service.save_embedding_for_image.assert_awaited_once()
    else:
        process.assert_awaited_once()
        assert not process.await_args.kwargs['analysis_instructions'].strip()


@pytest.mark.parametrize('source', ['file', 'url'])
async def test_web_upload_routes_forward_instructions(monkeypatch, upload_dependencies, source):
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.dependency_overrides[get_current_user] = lambda: {'id': 1, 'role': 'admin'}
    app.dependency_overrides[images.get_async_session] = lambda: upload_dependencies
    process = AsyncMock()
    monkeypatch.setattr(images, '_post_upload_process', process)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        if source == 'file':
            response = await client.post('/images/upload', files={'file': ('a.png', b'image', 'image/png')},
                data={'auto_analyze': 'true', 'analysis_instructions': '重点描述文字'})
        else:
            response = await client.post('/images/analyze-url', json={
                'image_url': 'https://example.com/a.png', 'auto_analyze': True, 'analysis_instructions': '重点描述文字',
            })
    await asyncio.sleep(0)
    assert response.status_code == 201, response.text
    assert process.await_args.kwargs['analysis_instructions'] == '重点描述文字'
    assert process.await_args.kwargs['auto_analyze'] is True


@pytest.mark.parametrize('auto_analyze,instructions,expected', [
    (True, '重点描述文字', True), (True, '   ', False), (False, '重点描述文字', False),
])
async def test_upload_background_analysis_respects_custom_instructions(
    monkeypatch, upload_dependencies, auto_analyze, instructions, expected,
):
    class UploadSession(LocalSession):
        async def commit(self):
            pass

    monkeypatch.setattr('imgtag.db.database.async_session_maker', UploadSession)
    await images._post_upload_process(
        image_id=18, user_id=1, tags=['已有标签'], description='已有描述',
        category_id=None, width=None, height=None, auto_analyze=auto_analyze,
        log=images.logger, analysis_instructions=instructions,
    )
    if expected:
        images.task_queue.add_tasks.assert_awaited_once_with([18], analysis_instructions=instructions)
    else:
        images.task_queue.add_tasks.assert_not_awaited()
        images.embedding_service.save_embedding_for_image.assert_awaited_once()


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


@pytest.mark.parametrize('role', ['admin', 'user'])
@pytest.mark.parametrize('credentials', [
    {'callback_headers_encrypted': 'encrypted-test-credentials'},
    {'callback_headers': {'Authorization': 'Bearer plaintext-test-credentials'}},
    {'callback_headers': json.dumps({'Authorization': 'Bearer plaintext-test-credentials'})},
])
async def test_task_responses_never_expose_callback_credentials(repository, role, credentials):
    detail, listing = repository
    now = datetime.now(timezone.utc)
    task = Task(
        id='callback-task', type='analyze_image', status='pending',
        payload={'image_id': 18, **credentials},
        created_at=now, updated_at=now,
    )
    detail.return_value = task
    listing.return_value = ([task], 1)
    user = {'id': 1, 'role': role}
    response = task_service.task_response(task, user)
    assert response['payload'] == {'image_id': 18}
    assert task.payload == {'image_id': 18, **credentials}
    if role == 'admin':
        assert (await task_service.get_task(task.id, user=user))['payload'] == {'image_id': 18}
        assert (await task_service.get_tasks(user=user))['tasks'][0]['payload'] == {'image_id': 18}


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
            payload JSON, result JSON, error TEXT, run_token TEXT, heartbeat_at DATETIME,
            created_at DATETIME, updated_at DATETIME, completed_at DATETIME)'''))
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


async def test_global_task_mutations_require_admin_before_side_effects(monkeypatch):
    cleanup = AsyncMock(return_value=4)
    create = AsyncMock(return_value='vector-task')
    monkeypatch.setattr(task_service, 'cleanup_old_tasks', cleanup)
    monkeypatch.setattr(task_service, 'create_task', create)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app('user')), base_url='http://test') as client:
        assert (await client.post('/tasks/cleanup')).status_code == 403
        assert (await client.post('/tasks/vectorize?force=true', json=[999])).status_code == 403
    cleanup.assert_not_awaited()
    create.assert_not_awaited()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app('admin')), base_url='http://test') as client:
        assert (await client.post('/tasks/cleanup')).status_code == 200
        assert (await client.post('/tasks/vectorize?force=true', json=[999])).status_code == 200
    cleanup.assert_awaited_once_with(7)
    create.assert_awaited_once_with('vectorize_batch', {'image_ids': [999], 'force': True})


async def test_external_upload_requires_upload_permission_without_ai_or_tags(upload_dependencies):
    app = FastAPI()
    app.include_router(external.router, prefix='/external')
    app.dependency_overrides[external.require_api_key] = lambda: {'id': 1, 'role': 'user', 'permissions': 0}
    app.dependency_overrides[external.get_async_session] = lambda: upload_dependencies
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/external/images', json={'image_url': 'http://192.168.1.10/image.png', 'auto_analyze': False})
    assert response.status_code == 403
    external_upload.upload_service.save_remote_image.assert_not_awaited()
    external_upload.image_repository.create_image.assert_not_awaited()


@pytest.mark.parametrize('kind', ['analyze_image', 'rebuild_vector'])
async def test_task_retry_checks_ownership_and_ai_permission(monkeypatch, kind):
    app = make_app('user')
    user = {'id': 1, 'role': 'user', 'permissions': 0}
    app.dependency_overrides[get_current_user] = lambda: user
    class ReadSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(task_api, 'async_session_maker', ReadSession)
    task = SimpleNamespace(id='own', type=kind, status='failed', payload={'image_id': 1})
    visible = AsyncMock(return_value=None)
    monkeypatch.setattr(task_api.task_repository, 'get_visible_by_id', visible)
    retry = AsyncMock(return_value=True)
    monkeypatch.setattr(task_api.task_queue, 'retry_task', retry)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post('/tasks/other/retry')).status_code == 404
        assert visible.await_args.args[1:] == ('other', 1)
        retry.assert_not_awaited()
        visible.return_value = task
        assert (await client.post('/tasks/own/retry')).status_code == 403
        retry.assert_not_awaited()
        user['permissions'] = int(images.Permission.AI_ANALYZE)
        assert (await client.post('/tasks/own/retry')).status_code == 200
        retry.assert_awaited_once_with('own')


@pytest.mark.parametrize('redirect', [False, True])
async def test_remote_image_stream_keeps_unrestricted_urls_and_enforces_size(monkeypatch, redirect):
    original_client = httpx.AsyncClient
    requests = []
    async def handler(request):
        requests.append(str(request.url))
        if redirect and request.url.host == 'images.example':
            return httpx.Response(302, headers={'location': 'http://192.168.1.10/private.png'})
        return httpx.Response(200, headers={'content-type': 'image/png'}, content=b'image')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    limit = AsyncMock(return_value=5)
    monkeypatch.setattr(upload_service, 'get_max_upload_size', limit)
    url = 'https://images.example/a.png' if redirect else 'http://127.0.0.1/private.png'
    assert await upload_service.fetch_remote_image(url) == (b'image', 'image/png')
    assert any('192.168.1.10' in request if redirect else '127.0.0.1' in request for request in requests)
    limit.return_value = 4
    with pytest.raises(ValueError, match='大小限制'):
        await upload_service.fetch_remote_image(url)


async def test_remote_image_stops_reading_oversized_stream(monkeypatch):
    original_client = httpx.AsyncClient
    consumed = 0
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal consumed
            for _ in range(20):
                consumed += 1
                yield b'x' * 65536
    async def handler(request):
        return httpx.Response(200, headers={'content-type': 'image/png', 'content-length': '1'}, stream=Chunks())
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(upload_service, 'get_max_upload_size', AsyncMock(return_value=65536))
    with pytest.raises(ValueError, match='大小限制'):
        await upload_service.fetch_remote_image('http://images.example/chunked.png')
    assert consumed == 2


async def test_remote_image_has_total_download_deadline(monkeypatch):
    wait_for = asyncio.wait_for
    async def short_deadline(operation, timeout):
        assert timeout == 30.0
        return await wait_for(operation, 0.01)
    async def hang(url, **kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr(upload_service, '_stream_remote_image', hang)
    monkeypatch.setattr(asyncio, 'wait_for', short_deadline)
    with pytest.raises(ValueError, match='下载超时'):
        await upload_service.fetch_remote_image('http://images.example/slow.png')


async def test_zip_upload_commits_each_image_before_next_network_call(upload_dependencies, monkeypatch):
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.dependency_overrides[get_current_user] = lambda: {'id': 1, 'role': 'admin'}
    app.dependency_overrides[images.get_async_session] = lambda: upload_dependencies
    upload_dependencies.expunge = Mock()
    held_lock = False
    async def commit():
        nonlocal held_lock
        held_lock = False
    async def rollback():
        nonlocal held_lock
        held_lock = False
    async def create_location(*args, **kwargs):
        nonlocal held_lock
        held_lock = True
    uploads = 0
    async def upload(*args):
        nonlocal uploads
        assert not held_lock, '下一张图片的网络上传不能持有上一张图片的端点锁'
        uploads += 1
        return uploads != 2
    upload_dependencies.commit = AsyncMock(side_effect=commit)
    upload_dependencies.rollback = AsyncMock(side_effect=rollback)
    monkeypatch.setattr(images.image_location_repository, 'create', AsyncMock(side_effect=create_location))
    monkeypatch.setattr(images.storage_service, 'upload_to_endpoint', AsyncMock(side_effect=upload))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as zip_file:
        for name in ('one.png', 'bad.png', 'three.png'):
            zip_file.writestr(name, b'image')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/images/upload-zip', files={'file': ('images.zip', archive.getvalue(), 'application/zip')})
    assert response.status_code == 201, response.text
    assert response.json()['uploaded_count'] == 2 and response.json()['failed_files'] == ['bad.png']
    assert images.image_repository.create_image.await_count == 2
    assert upload_dependencies.commit.await_count == 3
    upload_dependencies.rollback.assert_awaited_once()


@pytest.mark.parametrize('local_success', [True, False])
async def test_upload_timeout_falls_back_and_requires_success_before_metadata(upload_dependencies, monkeypatch, local_success):
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.dependency_overrides[get_current_user] = lambda: {'id': 1, 'role': 'admin'}
    app.dependency_overrides[images.get_async_session] = lambda: upload_dependencies
    service = StorageService()
    remote = SimpleNamespace(id=2, name='remote', provider='s3', operation_generation=0)
    monkeypatch.setattr(images.storage_endpoint_repository, 'resolve_upload_endpoint', AsyncMock(return_value=(remote, None)))
    monkeypatch.setattr(settings, 'STORAGE_ITEM_TIMEOUT', 0.01)
    async def hang(*args):
        await asyncio.Event().wait()
    monkeypatch.setattr(service, '_upload_s3', hang)
    local = AsyncMock(return_value=local_success)
    monkeypatch.setattr(service, '_upload_local', local)
    monkeypatch.setattr(images.storage_service, 'upload_to_endpoint', service.upload_to_endpoint)
    monkeypatch.setattr(images, '_post_upload_process', AsyncMock())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/images/upload', files={'file': ('one.png', b'image', 'image/png')},
                                     data={'auto_analyze': 'false'})
    await asyncio.sleep(0)
    local.assert_awaited_once()
    if local_success:
        assert response.status_code == 201, response.text
        assert images.image_location_repository.create.await_args.kwargs['endpoint_id'] == 1
    else:
        assert response.status_code == 500
        images.image_repository.create_image.assert_not_awaited()
        images.image_location_repository.create.assert_not_awaited()
