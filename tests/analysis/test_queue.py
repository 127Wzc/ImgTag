"""重分析、队列合并和主体上下文的回归测试。"""

import asyncio
import base64
import io
import json
import importlib
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import h11
import pytest
from PIL import Image
from sqlalchemy.dialects import postgresql

from imgtag.services import storage_service, embedding_service, vision_service
from imgtag.services.task_queue import task_queue
from imgtag.services.subject_context_service import subject_context_service
from imgtag.services.vision_service import ImageAnalysisResult, VisionService
from imgtag.core.gif_analysis import parse_gif_frame_count
from imgtag.core import crypto


def make_gif(frame_count):
    frames = [Image.new('RGB', (12, 12), (index * 25, 50, 100)) for index in range(frame_count)]
    output = io.BytesIO()
    frames[0].save(output, format='GIF', save_all=True, append_images=frames[1:], duration=100, loop=0, disposal=2)
    return output.getvalue()


@pytest.mark.parametrize('total', [1, 2, 3, 8])
@pytest.mark.parametrize('count', [1, 2, 3])
def test_gif_sampling_is_even_ordered_and_handles_short_animations(total, count):
    frames = VisionService().sample_gif_frames(make_gif(total), count)
    expected_count = min(total, count)
    indices = [0] if expected_count == 1 else [round(index * (total - 1) / (expected_count - 1)) for index in range(expected_count)]
    assert [index for _, index in frames] == indices
    for data, index in frames:
        with Image.open(io.BytesIO(data)) as frame:
            assert frame.format == 'PNG'
            assert frame.getpixel((0, 0)) == (index * 25, 50, 100)


def test_gif_transparency_and_disposal_are_composited():
    frames = []
    for index in range(3):
        frame = Image.new('P', (12, 12), 0)
        frame.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
        frame.putpixel((index + 1, 1), 1)
        frames.append(frame)
    output = io.BytesIO()
    frames[0].save(output, format='GIF', save_all=True, append_images=frames[1:], duration=100,
        transparency=0, disposal=2, optimize=False)
    for data, index in VisionService().sample_gif_frames(output.getvalue(), 3):
        with Image.open(io.BytesIO(data)) as frame:
            assert frame.getpixel((0, 0)) == (255, 255, 255)
            assert frame.getpixel((index + 1, 1)) == (255, 0, 0)
            if index:
                assert frame.getpixel((index, 1)) == (255, 255, 255)


@pytest.mark.parametrize('invalid', ['', '0', '4', '-1', '1.5', 'bad'])
def test_gif_frame_count_rejects_invalid_configuration(invalid):
    with pytest.raises(ValueError, match='1至3'):
        parse_gif_frame_count(invalid)


def test_corrupt_gif_fails_instead_of_sending_original_to_model():
    with pytest.raises(ValueError, match='GIF 取帧失败'):
        VisionService().sample_gif_frames(b'GIF89a-invalid', 3)


class Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def commit(self):
        pass

    async def flush(self):
        pass

    def begin_nested(self):
        return self


@pytest.fixture
def queue(monkeypatch):
    monkeypatch.setattr(task_queue, "_running", True)
    monkeypatch.setattr("imgtag.services.task_queue.async_session_maker", Session)
    monkeypatch.setattr("imgtag.services.task_queue.image_repository.lock_ids", AsyncMock(side_effect=lambda session, ids: set(ids)))
    return task_queue


async def test_force_upgrades_pending_and_deduplicates(queue, monkeypatch):
    pending = SimpleNamespace(id="pending", status="pending", payload={"image_id": 1})
    monkeypatch.setattr("imgtag.services.task_queue.task_repository.list_active_for_images", AsyncMock(return_value=[pending]))
    create = AsyncMock()
    monkeypatch.setattr("imgtag.services.task_queue.task_repository.create_task", create)
    report = await queue.enqueue_tasks([1, 1], force_analyze=True)
    assert report["upgraded"] == 1
    assert pending.payload["force_analyze"] is True
    report = await queue.enqueue_tasks([1], force_analyze=True)
    assert report["existing"] == 1
    create.assert_not_awaited()


async def test_running_task_keeps_exactly_one_followup(queue, monkeypatch):
    active = [SimpleNamespace(id="running", status="processing", payload={"image_id": 1})]

    async def create(session, *, task_id, task_type, payload):
        active.append(SimpleNamespace(id=task_id, status="pending", payload=payload))

    monkeypatch.setattr("imgtag.services.task_queue.task_repository.list_active_for_images", AsyncMock(side_effect=lambda *args: active))
    monkeypatch.setattr("imgtag.services.task_queue.task_repository.create_task", create)
    first = await queue.enqueue_tasks([1], force_analyze=True)
    second = await queue.enqueue_tasks([1], force_analyze=True)
    assert first["waiting"] == first["added"] == 1
    assert second["existing"] == 1
    assert len(active) == 2


@pytest.mark.parametrize('headers', [
    {}, {'x-api-key': 'callback-test-key'}, {'Authorization': 'Bearer callback-test-token'},
    {'x-api-key': 'callback-test-key', 'Authorization': 'Bearer callback-test-token'},
    {'X-Webhook-Secret': 'custom-callback-secret', 'X-App-Id': 'callback-consumer'},
    {'custom_header': 'custom-value', 'Authorization': 'Bearer callback-test-token'},
    {'authorization': 'Bearer callback-test-token', 'x-custom-auth': 'custom-auth-token'},
    {'Host': 'virtual.callback.test', 'Content-Type': 'application/custom+json'},
    {'X-Optional': ''},
])
@pytest.mark.parametrize('success', [True, False])
@pytest.mark.parametrize('status_code', [200, 401])
async def test_callback_headers_survive_queue_and_are_sent_only_to_callback(
    queue, monkeypatch, caplog, headers, success, status_code,
):
    caplog.set_level('INFO', logger='imgtag.services.task_queue')
    # 新任务及回调发送均不再依赖运行时加密密钥。
    monkeypatch.setattr(crypto, '_fernet', None)
    create = AsyncMock()
    monkeypatch.setattr('imgtag.services.task_queue.task_repository.list_active_for_images', AsyncMock(return_value=[]))
    monkeypatch.setattr('imgtag.services.task_queue.task_repository.create_task', create)
    await queue.add_tasks([1], callback_url='https://callback.example/hook', callback_headers=headers)
    payload = create.await_args.kwargs['payload']
    assert (json.loads(payload['callback_headers']) if 'callback_headers' in payload else {}) == headers
    assert 'callback_headers_encrypted' not in payload
    expected_headers = headers
    assert queue._get_callback_headers(payload) == expected_headers

    monkeypatch.setattr('imgtag.services.task_queue.image_repository.get_with_tags',
                        AsyncMock(return_value=SimpleNamespace(width=100, height=200)))
    monkeypatch.setattr(storage_service, 'get_read_url', AsyncMock(return_value='https://images.example/a.png'))
    requests = []

    async def handle(request):
        # MockTransport 本身不会检查 HTTP/1.1 头格式，交给真实协议解析器校验。
        h11.Request(method=request.method, target=request.url.raw_path, headers=request.headers.raw)
        requests.append(request)
        return httpx.Response(status_code)

    real_client = httpx.AsyncClient
    monkeypatch.setattr('imgtag.services.task_queue.httpx.AsyncClient',
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    await queue._send_callback(
        payload['callback_url'], 1, 'callback-task', success,
        tags=['测试标签'] if success else None, error=None if success else '分析失败',
        callback_headers=payload.get('callback_headers'),
    )
    assert len(requests) == 1
    request = requests[0]
    for name, value in expected_headers.items():
        assert request.headers[name] == value
    expected_names = {name.lower() for name in expected_headers}
    for name in ['x-api-key', 'authorization']:
        if name not in expected_names:
            assert name not in request.headers
    header_logs = [record for record in caplog.records
                   if record.name == 'imgtag.services.task_queue' and 'headers=' in record.msg]
    assert len(header_logs) == 1
    assert header_logs[0].args[-1] == {
        name: f'{value[:2]}***{value[-2:]}' if len(value) > 4 else '***'
        for name, value in request.headers.items()
    }
    body = json.loads(request.content)
    assert body['success'] is success and body['image_id'] == 1
    assert body['tags'] == (['测试标签'] if success else [])
    assert body['error'] == (None if success else '分析失败')
    assert 'callback_headers' not in body
    for value in headers.values():
        if value.strip(' '):
            assert value not in caplog.text
    if status_code == 401:
        assert '失败' in caplog.text and '401' in caplog.text


@pytest.mark.parametrize('outcome', [200, 401, 'before_request'])
async def test_callback_header_mask_preserves_edges_without_changing_sent_values(queue, monkeypatch, caplog, outcome):
    caplog.set_level('INFO', logger='imgtag.services.task_queue')
    headers = {
        'X-One': 'A', 'X-Two': 'AB', 'X-Three': 'ABC', 'X-Four': 'ABCD',
        'X-Five': 'ABCDE', 'X-Example': 'AABBCCII',
    }
    expected = {
        'x-one': '***', 'x-two': '***', 'x-three': '***', 'x-four': '***',
        'x-five': 'AB***DE', 'x-example': 'AA***II',
    }
    monkeypatch.setattr('imgtag.services.task_queue.image_repository.get_with_tags',
                        AsyncMock(return_value=SimpleNamespace(width=100, height=200)))
    read_url = AsyncMock(return_value='https://images.example/a.png')
    if outcome == 'before_request':
        read_url.side_effect = RuntimeError('sensitive input AABBCCII')
    monkeypatch.setattr(storage_service, 'get_read_url', read_url)
    requests = []

    async def handle(request):
        requests.append(request)
        return httpx.Response(outcome)

    real_client = httpx.AsyncClient
    monkeypatch.setattr('imgtag.services.task_queue.httpx.AsyncClient',
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    await queue._send_callback('https://callback.example/hook', 1, 'masked-callback', True,
                              callback_headers=headers)
    assert len(requests) == (0 if outcome == 'before_request' else 1)
    if requests:
        for name, value in headers.items():
            assert requests[0].headers[name] == value
    header_log = next(record for record in caplog.records
                      if record.name == 'imgtag.services.task_queue' and 'headers=' in record.msg)
    logged_headers = {name.lower(): value for name, value in header_log.args[-1].items()}
    assert {name: logged_headers[name] for name in expected} == expected
    assert 'AABBCCII' not in caplog.text


async def test_callback_credentials_are_ignored_without_url_and_not_merged_across_destinations(queue, monkeypatch):
    active = []

    async def create(session, *, task_id, task_type, payload):
        active.append(SimpleNamespace(id=task_id, status='pending', payload=payload))

    monkeypatch.setattr('imgtag.services.task_queue.task_repository.list_active_for_images', AsyncMock(side_effect=lambda *args: active))
    monkeypatch.setattr('imgtag.services.task_queue.task_repository.create_task', create)
    await queue.enqueue_tasks([1], callback_headers={'x-api-key': 'ignored-key'})
    assert 'callback_headers' not in active[0].payload
    first = await queue.enqueue_tasks([1], callback_url='https://callback.example/one', callback_headers={'x-api-key': 'one-key'})
    same = await queue.enqueue_tasks([1], callback_url='https://callback.example/one', callback_headers={'x-api-key': 'one-key'})
    other_key = await queue.enqueue_tasks([1], callback_url='https://callback.example/one', callback_headers={'x-api-key': 'other-key'})
    other_url = await queue.enqueue_tasks([1], callback_url='https://callback.example/two', callback_headers={'x-api-key': 'one-key'})
    assert first['added'] == other_key['added'] == other_url['added'] == 1
    assert same['existing'] == 1
    assert len(active) == 4


async def test_callback_credentials_match_by_original_values(queue, monkeypatch):
    headers = {'x-api-key': ' callback-test-key ', 'Authorization': ' Bearer callback-test-token ', 'X-Optional': '   '}
    active = [SimpleNamespace(id='pending', status='pending', payload={
        'image_id': 1, 'callback_url': 'https://callback.example/hook',
        'callback_headers': headers,
    })]
    monkeypatch.setattr('imgtag.services.task_queue.task_repository.list_active_for_images', AsyncMock(return_value=active))
    create = AsyncMock()
    monkeypatch.setattr('imgtag.services.task_queue.task_repository.create_task', create)
    report = await queue.enqueue_tasks(
        [1], callback_url='https://callback.example/hook', callback_headers=headers,
    )
    assert report['existing'] == 1
    create.assert_not_awaited()
    report = await queue.enqueue_tasks(
        [1], callback_url='https://callback.example/hook',
        callback_headers={name: value.strip(' ') for name, value in headers.items()},
    )
    assert report['added'] == 1
    create.assert_awaited_once()


@pytest.mark.parametrize('headers', [
    {'Authorization': ' Bearer callback-test-token '}, {'X-Optional': ''},
    {'Authorization': 'Bearer callback-test-token\r\nInjected: value'},
    {'Authorization': '\tBearer callback-test-token\t'},
    {'Authorization': '\u00a0Bearer callback-test-token\u00a0'},
    {'x-api-key': 'callback-test-key\x00'}, {'Bad Header': 'callback-test-key'},
    {'X-Custom': 'callback-test-key\r\nInjected: value'},
])
async def test_internal_callback_headers_preserve_original_values(queue, monkeypatch, headers):
    create = AsyncMock()
    monkeypatch.setattr('imgtag.services.task_queue.task_repository.list_active_for_images', AsyncMock(return_value=[]))
    monkeypatch.setattr('imgtag.services.task_queue.task_repository.create_task', create)
    await queue.enqueue_tasks([1], callback_url='https://callback.example/hook', callback_headers=headers)
    payload = create.await_args.kwargs['payload']
    assert queue._get_callback_headers(payload) == headers
    assert 'callback_headers_encrypted' not in payload
    assert isinstance(payload['callback_headers'], str)
    assert '\x00' not in payload['callback_headers']


@pytest.mark.parametrize('value', [
    ' Bearer callback-test-token ', 'Bearer callback-test-token\r\nInjected: value',
    'Bearer callback-test-token\x00', 'Bearer callback-test-token中文',
])
async def test_callback_protocol_errors_do_not_normalize_values_or_leak_credentials(queue, monkeypatch, caplog, value):
    caplog.set_level('INFO', logger='imgtag.services.task_queue')
    monkeypatch.setattr('imgtag.services.task_queue.image_repository.get_with_tags',
                        AsyncMock(return_value=SimpleNamespace(width=100, height=200)))
    monkeypatch.setattr(storage_service, 'get_read_url', AsyncMock(return_value='https://images.example/a.png'))
    requests = []

    async def handle(request):
        h11.Request(method=request.method, target=request.url.raw_path, headers=request.headers.raw)
        return httpx.Response(200)

    real_client = httpx.AsyncClient
    real_build = real_client.build_request

    def build(client, *args, **kwargs):
        requests.append(kwargs['headers'])
        return real_build(client, *args, **kwargs)

    monkeypatch.setattr(real_client, 'build_request', build)
    monkeypatch.setattr('imgtag.services.task_queue.httpx.AsyncClient',
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    await queue._send_callback('https://callback.example/hook?token=callback-test-token', 1, 'legacy-callback', True,
        callback_headers={'Authorization': value, 'X-Optional': ''})
    assert len(requests) == 1
    assert requests[0] == {'Authorization': value, 'X-Optional': ''}
    assert '失败' in caplog.text
    assert 'callback-test-token' not in caplog.text


@pytest.mark.parametrize('error_type', [httpx.LocalProtocolError, httpx.ConnectError, ValueError, httpx.HTTPStatusError])
async def test_callback_errors_never_log_credential_values(queue, monkeypatch, caplog, error_type):
    monkeypatch.setattr('imgtag.services.task_queue.image_repository.get_with_tags',
                        AsyncMock(return_value=SimpleNamespace(width=100, height=200)))
    monkeypatch.setattr(storage_service, 'get_read_url', AsyncMock(return_value='https://images.example/a.png'))
    secret = 'callback-test-secret'

    async def handle(request):
        if error_type is httpx.HTTPStatusError:
            return httpx.Response(401)
        raise error_type(f'Illegal header value {secret}')

    real_client = httpx.AsyncClient
    monkeypatch.setattr('imgtag.services.task_queue.httpx.AsyncClient',
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    await queue._send_callback(f'https://callback.example/hook?token={secret}', 1, 'sensitive-callback', True,
        callback_headers={'x-api-key': secret})
    assert secret not in caplog.text
    assert 'sensitive-callback' in caplog.text
    assert ('HTTP 401' if error_type is httpx.HTTPStatusError else error_type.__name__) in caplog.text
    header_log = next(record for record in caplog.records
                      if record.name == 'imgtag.services.task_queue' and 'headers=' in record.msg)
    assert header_log.args[-1]['x-api-key'] == 'ca***et'
    assert all(value == '***' or (len(value) == 7 and value[2:-2] == '***')
               for value in header_log.args[-1].values())


@pytest.mark.parametrize('kind', ['invalid_header', 'wrong_type', 'null', 'invalid_json', 'json_invalid_header'])
def test_callback_header_errors_do_not_expose_credentials(queue, kind):
    secret = 'callback-test-secret'
    headers = {
        'invalid_header': {'Authorization': [secret]},
        'wrong_type': 123,
        'null': None,
        'invalid_json': secret,
        'json_invalid_header': json.dumps({'Authorization': [secret]}),
    }[kind]
    with pytest.raises(ValueError, match='回调认证头无效') as error:
        queue._get_callback_headers({'callback_headers': headers})
    assert secret not in ''.join(traceback.format_exception(error.type, error.value, error.tb))


@pytest.fixture
def subject_repos(monkeypatch):
    get_primary = AsyncMock(return_value=[])
    tags = AsyncMock(return_value=[])
    matches = AsyncMock(return_value=[])
    monkeypatch.setattr("imgtag.services.subject_context_service.image_subject_repository.get_current", get_primary)
    monkeypatch.setattr("imgtag.services.subject_context_service.image_subject_repository.has_explicit_selection", AsyncMock(return_value=False))
    monkeypatch.setattr("imgtag.services.subject_context_service.image_repository.get_image_tags_with_source", tags)
    monkeypatch.setattr("imgtag.services.subject_context_service.subject_repository.list_matching_tags", matches)
    return get_primary, tags, matches


def subject(id=1):
    return SimpleNamespace(id=id, name=f"小白{id}", aliases=["白白"], description="白色长毛猫，左耳灰斑", updated_at="v1", is_active=True, primary_tag_id=20, alias_tag_ids=[21])


async def test_manual_tag_links_unique_subject(subject_repos, monkeypatch):
    primary, tags, matches = subject_repos
    tags.return_value = [{"id": 21, "level": 2, "source": "user"}]
    matches.return_value = [subject()]

    async def assign(*args, **kwargs):
        primary.return_value = [SimpleNamespace(subject_id=1, subject=subject(), state="confirmed", source=kwargs["source"], updated_at="v1")]

    assignment = AsyncMock(side_effect=assign)
    monkeypatch.setattr("imgtag.services.subject_context_service.subject_assignment_service.assign_primary_subject", assignment)
    result = await subject_context_service.resolve(Session(), 1, assign_from_tags=True)
    assert result[0]["status"] == "confirmed"
    assert result[0]["source"] == "tag"
    assert result[0]["definition"] == "白色长毛猫，左耳灰斑"
    assert result[0]["aliases"] == ["白白"]
    assert assignment.await_args.kwargs["source"] == "tag"


@pytest.mark.parametrize("source,count", [("ai", 1), ("user", 2)])
async def test_ai_or_ambiguous_tags_stay_candidates(subject_repos, monkeypatch, source, count):
    _, tags, matches = subject_repos
    tags.return_value = [{"id": 20, "level": 2, "source": source}]
    matches.return_value = [subject(i) for i in range(count)]
    assign = AsyncMock()
    monkeypatch.setattr("imgtag.services.subject_context_service.subject_assignment_service.assign_primary_subject", assign)
    result = await subject_context_service.resolve(Session(), 1, assign_from_tags=True)
    assert all(c["status"] == "candidate" for c in result)
    assign.assert_not_awaited()


async def test_disabled_subject_does_not_inject_or_match_tags(subject_repos):
    primary, tags, _ = subject_repos
    disabled = subject()
    disabled.is_active = False
    primary.return_value = [SimpleNamespace(subject_id=disabled.id, subject=disabled, state="confirmed")]
    assert await subject_context_service.resolve(Session(), 1) == []
    tags.assert_awaited_once()


@pytest.fixture
def processing(queue, monkeypatch):
    image = SimpleNamespace(id=1, file_type="jpg", description="旧描述", tags=[SimpleNamespace(id=4, name="宠物", level=0)], embedding=None, original_url=None)
    contexts = [{"subject_id": 1, "name": "小白", "source": "manual", "status": "confirmed", "definition": "白猫"}]
    monkeypatch.setattr("imgtag.services.task_queue.image_repository.get_with_tags", AsyncMock(return_value=image))
    monkeypatch.setattr("imgtag.services.task_queue.image_repository.get_by_id_for_update", AsyncMock(return_value=image))
    monkeypatch.setattr("imgtag.services.task_queue.config_repository.get_value", AsyncMock(side_effect=lambda session, key, default: default))
    monkeypatch.setattr(storage_service, "get_file_content", AsyncMock(return_value=b"image"))
    monkeypatch.setattr(queue, "_resolve_subject_memory", AsyncMock(return_value=contexts))
    resolve = AsyncMock(return_value=contexts)
    monkeypatch.setattr(subject_context_service, "resolve", resolve)
    monkeypatch.setattr("imgtag.services.task_queue.subject_repository.lock_by_ids", AsyncMock())
    monkeypatch.setattr("imgtag.services.task_queue.task_repository.begin_attempt", AsyncMock(return_value=2))
    vision = AsyncMock(return_value=ImageAnalysisResult(tags=["新标签"], description="新描述", request_metadata={"model": "test"}))
    monkeypatch.setattr(vision_service, "analyze_image_base64", vision)
    update = AsyncMock()
    monkeypatch.setattr("imgtag.services.task_queue.image_repository.update_image", update)
    monkeypatch.setattr("imgtag.services.task_queue.image_tag_repository.set_image_tags", AsyncMock())
    monkeypatch.setattr("imgtag.services.task_queue.image_repository.get_image_tags_with_source", AsyncMock(return_value=[{"name": "人工主体标签", "source": "user", "sort_order": 0}, {"name": "新标签", "source": "ai", "sort_order": 0}]))
    embed = AsyncMock(return_value=True)
    monkeypatch.setattr(embedding_service, "save_embedding_for_image", embed)
    completed = AsyncMock()
    monkeypatch.setattr(queue, "_mark_task_completed", completed)
    monkeypatch.setattr("imgtag.services.task_queue.analysis_review_service.current", AsyncMock(return_value={"description": "旧描述", "tags": []}))
    monkeypatch.setattr("imgtag.services.task_queue.analysis_review_service.history", AsyncMock())
    return vision, update, embed, completed, resolve


@pytest.mark.parametrize("force", [True, False])
async def test_force_really_calls_vision_with_existing_results(queue, processing, force):
    vision, update, embed, completed, _ = processing
    task = SimpleNamespace(id="task", type="analyze_image", payload={"image_id": 1, "force_analyze": force})
    await queue._process_task(task, 0)
    if force:
        vision.assert_awaited_once()
        assert vision.await_args.kwargs["request_context"]["attempt"] == 2
        assert vision.await_args.kwargs["subject_contexts"][0]["definition"] == "白猫"
        update.assert_awaited_once()
        embed.assert_awaited_once()
        assert not completed.await_args.args[1].get("pending_review")
    else:
        vision.assert_not_awaited()
        update.assert_not_awaited()
    completed.assert_awaited_once()


async def test_changed_subject_discards_old_output_and_requeues(queue, processing, monkeypatch):
    _, update, embed, completed, resolve = processing
    resolve.return_value = [{"subject_id": 2}]
    enqueue = AsyncMock(return_value=1)
    monkeypatch.setattr(queue, "add_tasks", enqueue)
    await queue._process_task(SimpleNamespace(id="task", type="analyze_image", payload={"image_id": 1, "force_analyze": True}), 0)
    update.assert_not_awaited()
    embed.assert_not_awaited()
    assert enqueue.await_args.kwargs["force_analyze"] is True
    assert completed.await_args.args[1]["superseded"] is True


async def test_vision_failure_preserves_existing_data(queue, processing, monkeypatch):
    vision, update, embed, completed, _ = processing
    vision.side_effect = ValueError("模型失败")
    failed = AsyncMock()
    monkeypatch.setattr(queue, "_mark_task_failed", failed)
    with pytest.raises(ValueError, match="模型失败"):
        await queue._process_task(SimpleNamespace(id="task", type="analyze_image", payload={"image_id": 1, "force_analyze": True}), 0)
    update.assert_not_awaited()
    embed.assert_not_awaited()
    completed.assert_not_awaited()
    failed.assert_awaited_once()


@pytest.mark.parametrize('success', [True, False])
async def test_worker_forwards_headers_on_success_and_failure(queue, processing, monkeypatch, success):
    vision, _, _, _, _ = processing
    if not success:
        vision.side_effect = ValueError('模型失败')
    monkeypatch.setattr(queue, '_mark_task_failed', AsyncMock())
    callback = AsyncMock()
    monkeypatch.setattr(queue, '_send_callback', callback)
    headers = {'Authorization': 'Bearer callback-test-token'}
    task = SimpleNamespace(id='callback-task', type='analyze_image', payload={
        'image_id': 1, 'force_analyze': True, 'callback_url': 'https://callback.example/hook',
        'callback_headers': headers,
    })
    if success:
        await queue._process_task(task, 0)
    else:
        with pytest.raises(ValueError, match='模型失败'):
            await queue._process_task(task, 0)
    await asyncio.sleep(0)
    callback.assert_awaited_once()
    assert callback.await_args.args[:4] == ('https://callback.example/hook', 1, task.id, success)
    assert callback.await_args.kwargs['callback_headers'] == headers


async def test_superseded_analysis_preserves_callback_authentication(queue, processing, monkeypatch):
    processing[-1].return_value = [{'subject_id': 2}]
    enqueue = AsyncMock(return_value=1)
    monkeypatch.setattr(queue, 'add_tasks', enqueue)
    headers = {'x-api-key': 'callback-test-key'}
    await queue._process_task(SimpleNamespace(id='task', type='analyze_image', payload={
        'image_id': 1, 'force_analyze': True, 'callback_url': 'https://callback.example/hook',
        'callback_headers': headers,
    }), 0)
    assert enqueue.await_args.kwargs['callback_headers'] == headers
    assert enqueue.await_args.kwargs['callback_url'] == 'https://callback.example/hook'


async def test_superseded_analysis_invalid_callback_credentials_do_not_leak(queue, processing, monkeypatch, caplog):
    processing[-1].return_value = [{'subject_id': 2}]
    failed = AsyncMock()
    callback = AsyncMock()
    monkeypatch.setattr(queue, '_mark_task_failed', failed)
    monkeypatch.setattr(queue, '_send_callback', callback)
    secret = 'callback-test-secret'
    task = SimpleNamespace(id='invalid-legacy-callback', type='analyze_image', payload={
        'image_id': 1, 'force_analyze': True, 'callback_url': 'https://callback.example/hook',
        'callback_headers': {'Authorization': [secret]},
    })
    with pytest.raises(ValueError) as error:
        await queue._process_task(task, 0)
    await asyncio.sleep(0)
    failed.assert_awaited_once()
    callback.assert_awaited_once()
    assert secret not in ''.join(traceback.format_exception(error.type, error.value, error.tb))
    assert secret not in failed.await_args.args[1]
    assert secret not in callback.await_args.kwargs['error']
    assert secret not in caplog.text


async def test_claim_query_serializes_images():
    """检查 PostgreSQL 抢占语句中的跨任务阻塞条件与行锁。"""
    from imgtag.db.repositories import task_repository

    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))
    await task_repository.claim_next_task(session, ["analyze_image", "rebuild_vector"])
    statement = str(session.execute.await_args.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "NOT (EXISTS" in statement
    assert "processing" in statement and "rebuild_vector" in statement
    assert "FOR UPDATE SKIP LOCKED" in statement


@pytest.fixture
def vision_transport(monkeypatch):
    """检查真实 HTTP 请求体；不连接任何外部模型。"""
    requests = []
    values = {"vision_api_key": "secret-never-log", "vision_model": "test-model", "vision_api_base_url": "https://vision.test/v1", "vision_prompt": "全局规则" + "长文本" * 600 + "全局结束标记"}
    reads = []

    async def get(key, default=None, *, fresh=False, session=None):
        reads.append((key, fresh))
        return values.get(key, default)

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"description": "小白在沙发上", "tags": ["猫", "沙发"]})}}]})

    original_client = httpx.AsyncClient
    vision_module = importlib.import_module("imgtag.services.vision_service")
    monkeypatch.setattr(vision_module.config_cache, "get", get)
    monkeypatch.setattr(vision_module, "async_session_maker", Session)
    monkeypatch.setattr(vision_module.tag_repository, "get_by_id", AsyncMock(return_value=SimpleNamespace(level=0, name="宠物", prompt="分类独立要求")))
    monkeypatch.setattr(VisionService, "_get_forbidden_tags_cached", AsyncMock(return_value=[]))
    monkeypatch.setattr(vision_module.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    return requests, reads, values


async def test_request_separates_category_and_subject_logs_full_input(vision_transport, caplog):
    requests, reads, values = vision_transport
    observed = AsyncMock()
    contexts = [{"subject_id": 12, "name": "小白", "definition": "左耳灰斑的长毛猫", "aliases": ["白白"], "source": "manual", "status": "confirmed"}]
    result = await VisionService().analyze_image_base64(
        b"not-real-image", category_id=5, subject_contexts=contexts,
        request_context={"task_id": "test-task", "image_id": 123, "attempt": 2, "force_analyze": True},
        input_observer=observed,
    )
    content = requests[0]["messages"][0]["content"]
    assert "分类独立要求" in content[0]["text"]
    assert "小白" not in content[0]["text"]
    assert "左耳灰斑的长毛猫" in content[1]["text"]
    assert "分类独立要求" not in content[1]["text"]
    assert "description 继续遵守分类格式" in content[1]["text"]
    assert "# 主体资料使用规则" not in content[1]["text"]
    assert "菲比" not in content[1]["text"]
    assert content[2]["type"] == "image_url"
    assert result.request_metadata["input_messages"][0]["content"] == content[:2]
    assert observed.await_args.args[0] == result.request_metadata
    input_record = next(r for r in caplog.records if r.msg == "视觉分析输入: %s")
    logged = json.loads(input_record.args[0])
    assert logged["task_id"] == "test-task" and logged["attempt"] == 2
    assert "全局结束标记" in input_record.getMessage()
    assert "左耳灰斑的长毛猫" in input_record.getMessage()
    assert "secret-never-log" not in caplog.text
    assert "data:image" not in caplog.text
    assert ("vision_prompt", True) in reads
    assert ("vision_model", True) in reads
    # 修改后马上重分析，使用最新规则。
    values["vision_prompt"] = "修改后的全局规则"
    await VisionService().analyze_image_base64(b"image", request_context={"force_analyze": True})
    assert "修改后的全局规则" in requests[1]["messages"][0]["content"][0]["text"]


@pytest.mark.parametrize('configured,expected', [(None, [0, 4, 7]), ('1', [0]), ('2', [0, 7]), ('3', [0, 4, 7]), ('invalid', [0, 4, 7])])
async def test_gif_analysis_sends_selected_frames_in_one_request(vision_transport, configured, expected, caplog):
    requests, _, values = vision_transport
    if configured is not None:
        values['vision_gif_frame_count'] = configured
    observed = AsyncMock()
    result = await VisionService().analyze_image_base64(make_gif(8), 'image/gif',
        analysis_instructions='关注表情变化', input_observer=observed)
    assert len(requests) == 1
    parts = requests[0]['messages'][0]['content']
    images = [part for part in parts if part['type'] == 'image_url']
    assert len(images) == len(expected)
    for part, index in zip(images, expected):
        prefix, encoded = part['image_url']['url'].split(',', 1)
        assert prefix == 'data:image/png;base64'
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as frame:
            assert frame.getpixel((0, 0)) == (index * 25, 50, 100)
    text = '\n'.join(part['text'] for part in parts if part['type'] == 'text')
    assert '关注表情变化' in text
    assert ('同一个 GIF' in text) is (len(expected) > 1)
    if len(expected) > 1:
        assert '本次分析只对应一个资产' in text
        assert '该资产的不同状态，仅用于辅助识别' in text
        assert '不跨帧累计' in text
        assert '仅同一帧同时出现多个该主体才视为多个' in text
        assert '不要将不同帧的动作写成同时发生' in text
        assert 'description 仍遵守分类格式' in text
        assert 'subject_checks' not in text
        assert 'multiple=true' not in text
    assert [frame['frame_index'] for frame in result.request_metadata['gif_frames']] == expected
    assert observed.await_args.args[0] == result.request_metadata
    assert 'data:image' not in caplog.text


async def test_gif_frames_are_compressed_individually(vision_transport, monkeypatch):
    requests, _, values = vision_transport
    values['vision_max_image_size'] = '1'
    service = VisionService()
    monkeypatch.setattr(service, 'sample_gif_frames', Mock(return_value=[(b'x' * 2048, index) for index in range(3)]))
    compress = Mock(return_value=(b'compressed', 'image/jpeg'))
    monkeypatch.setattr(service, '_compress_image', compress)
    await service.analyze_image_base64(b'GIF', 'image/gif')
    assert compress.call_count == 3
    assert all(call.args[1] == 1024 for call in compress.call_args_list)
    images = [part for part in requests[0]['messages'][0]['content'] if part['type'] == 'image_url']
    assert len(images) == 3
    assert all(part['image_url']['url'].startswith('data:image/jpeg;base64,') for part in images)


async def test_gif_subject_protocol_keeps_one_identity_across_frames(vision_transport):
    requests, _, _ = vision_transport
    await VisionService().analyze_image_base64(make_gif(3), 'image/gif', subject_contexts=[
        {'subject_id': 12, 'name': '小白', 'status': 'confirmed'},
    ])
    parts = requests[0]['messages'][0]['content']
    assert len([part for part in parts if part['type'] == 'image_url']) == 3
    protocol = parts[1]['text']
    assert 'appearance:可见外观动作且不含姓名' in protocol
    assert 'multiple:同一画面是否有多个该主体' in protocol
    assert '每份主体资料返回一条核实结果' in protocol
    instructions = '\n'.join(part['text'] for part in parts if part['type'] == 'text')
    assert 'subject_checks 按主体身份返回一次' in instructions
    assert '仅同一帧同时出现多个该主体时才设置 multiple=true' in instructions


async def test_queue_preserves_gif_for_vision_but_matches_subject_on_first_frame(queue, processing, monkeypatch):
    vision = processing[0]
    content = make_gif(8)
    queue_module = importlib.import_module('imgtag.services.task_queue')
    queue_module.image_repository.get_with_tags.return_value.file_type = 'gif'
    monkeypatch.setattr(storage_service, 'get_file_content', AsyncMock(return_value=content))
    await queue._process_task(SimpleNamespace(id='task', type='analyze_image', payload={'image_id': 1, 'force_analyze': True}), 0)
    assert vision.await_args.args == (content, 'image/gif')
    memory_input = queue._resolve_subject_memory.await_args.kwargs
    assert memory_input['mime_type'] == 'image/png'
    with Image.open(io.BytesIO(memory_input['file_content'])) as frame:
        assert frame.getpixel((0, 0)) == (0, 50, 100)


async def test_disabled_gif_conversion_skips_queue_analysis(queue, processing, monkeypatch):
    queue_module = importlib.import_module('imgtag.services.task_queue')
    queue_module.image_repository.get_with_tags.return_value.file_type = 'gif'
    monkeypatch.setattr(queue_module.config_repository, 'get_value', AsyncMock(
        side_effect=lambda session, key, default: 'false' if key == 'vision_convert_gif' else default))
    skip = AsyncMock()
    monkeypatch.setattr(queue, '_skip_task', skip)
    await queue._process_task(SimpleNamespace(id='task', type='analyze_image', payload={'image_id': 1, 'force_analyze': True}), 0)
    skip.assert_awaited_once()
    processing[0].assert_not_awaited()
    storage_service.get_file_content.assert_not_awaited()


async def test_concurrent_images_do_not_share_subject_context(vision_transport):
    requests, _, _ = vision_transport
    service = VisionService()
    await asyncio.gather(*[
        service.analyze_image_base64(
            b"image", subject_contexts=[{"subject_id": i, "name": name, "status": "confirmed"}],
            request_context={"image_id": i},
        ) for i, name in [(1, "小白"), (2, "小黑")]
    ])
    parts = [r["messages"][0]["content"][1]["text"] for r in requests]
    assert "小白" in parts[0] and "小黑" not in parts[0]
    assert "小黑" in parts[1] and "小白" not in parts[1]


async def test_queue_api_defaults_to_force_reanalysis(queue, monkeypatch):
    from fastapi import BackgroundTasks
    from imgtag.api.endpoints.queue import AddTasksRequest, add_tasks

    enqueue = AsyncMock(return_value={"added": 1, "upgraded": 0, "waiting": 0, "existing": 0, "task_ids": ["t"], "missing": 0})
    monkeypatch.setattr(queue, "enqueue_tasks", enqueue)
    monkeypatch.setattr(queue, "get_status", AsyncMock(return_value={"pending_count": 1}))
    await add_tasks(AddTasksRequest(image_ids=[1]), BackgroundTasks(), user={"id": 1})
    assert enqueue.await_args.kwargs["force_analyze"] is True


async def test_retry_keeps_force_flag_and_attempt(queue, monkeypatch):
    from imgtag.db.repositories import task_repository

    row = SimpleNamespace(id="failed", status="failed", payload={"image_id": 1, "force_analyze": True, "attempt": 1}, error="old error", result={"old": True}, completed_at="old")
    monkeypatch.setattr(task_repository, "get_by_id", AsyncMock(return_value=row))
    session = SimpleNamespace(flush=AsyncMock())
    await task_repository.update_status(session, row.id, "pending")
    assert row.payload["force_analyze"] is True
    assert row.error is None and row.result is None and row.completed_at is None
    assert await task_repository.begin_attempt(session, row.id) == 2


async def test_subject_approval_enqueues_force_analysis_in_same_transaction(queue, monkeypatch):
    from imgtag.api.endpoints import approvals
    from imgtag.schemas.approval import ApprovalAction

    row = SimpleNamespace(id=1, status="pending", type=approvals.SUGGEST_SUBJECT_ASSIGNMENT_TYPE, target_id=123, payload={"image_id": 123})
    monkeypatch.setattr(approvals.approval_repository, "get_with_relations", AsyncMock(return_value=row))
    monkeypatch.setattr(approvals, "execute_approval", AsyncMock(return_value=True))
    monkeypatch.setattr(approvals.approval_repository, "approve", AsyncMock())
    monkeypatch.setattr(approvals.audit_log_repository, "add_log", AsyncMock())
    enqueue = AsyncMock(return_value=1)
    rebuild = AsyncMock()
    monkeypatch.setattr(queue, "add_tasks", enqueue)
    monkeypatch.setattr(approvals, "enqueue_rebuild_vector", rebuild)
    session = Session()
    result = await approvals.approve_request(1, ApprovalAction(), admin={"id": 1}, session=session)
    assert result["reanalyze_enqueued"] is True
    assert enqueue.await_args.args[0] == [123]
    assert enqueue.await_args.kwargs["force_analyze"] is True
    assert enqueue.await_args.kwargs["session"] is session
    rebuild.assert_not_awaited()


async def test_subject_assignment_defaults_to_reanalysis():
    from imgtag.schemas.subject import SetPrimarySubjectRequest

    assert SetPrimarySubjectRequest(subject_id=12).reanalyze is True
    assert SetPrimarySubjectRequest(subject_id=12, reanalyze=False).reanalyze is False


async def test_batch_subject_approval_also_enqueues_force_analysis(queue, monkeypatch):
    from imgtag.api.endpoints import approvals
    from imgtag.schemas.approval import BatchApproveRequest

    row = SimpleNamespace(id=1, status="pending", type=approvals.SUGGEST_SUBJECT_ASSIGNMENT_TYPE, target_id=123, payload={"image_id": 123})
    monkeypatch.setattr(approvals.approval_repository, "get_with_relations", AsyncMock(return_value=row))
    monkeypatch.setattr(approvals, "execute_approval", AsyncMock(return_value=True))
    monkeypatch.setattr(approvals.approval_repository, "approve", AsyncMock())
    monkeypatch.setattr(approvals.audit_log_repository, "add_log", AsyncMock())
    enqueue = AsyncMock(return_value=1)
    monkeypatch.setattr(queue, "add_tasks", enqueue)
    result = await approvals.batch_approve(BatchApproveRequest(approval_ids=[1]), admin={"id": 1}, session=Session())
    assert result["approved_count"] == 1
    assert enqueue.await_args.args[0] == [123]
    assert enqueue.await_args.kwargs["force_analyze"] is True


async def test_unsupported_format_preserves_old_embedding(queue, processing, monkeypatch):
    vision, update, embed, completed, _ = processing
    image = SimpleNamespace(id=1, file_type="pdf", description="旧描述", tags=[], embedding=[0.1], original_url=None)
    monkeypatch.setattr("imgtag.services.task_queue.image_repository.get_with_tags", AsyncMock(return_value=image))
    failed = AsyncMock()
    monkeypatch.setattr(queue, "_mark_task_failed", failed)
    await queue._process_task(SimpleNamespace(id="task", type="analyze_image", payload={"image_id": 1, "force_analyze": True}), 0)
    vision.assert_not_awaited()
    update.assert_not_awaited()
    embed.assert_not_awaited()
    completed.assert_not_awaited()
    assert "未调用视觉模型" in failed.await_args.args[1]


async def test_first_analysis_still_saves_directly_even_when_force_requested(queue, processing, monkeypatch):
    vision, update, embed, completed, _ = processing
    image = SimpleNamespace(id=1, file_type='jpg', description='', tags=[], embedding=None, original_url=None)
    monkeypatch.setattr('imgtag.services.task_queue.image_repository.get_with_tags', AsyncMock(return_value=image))
    monkeypatch.setattr('imgtag.services.task_queue.image_repository.get_by_id_for_update', AsyncMock(return_value=image))
    monkeypatch.setattr('imgtag.services.task_queue.analysis_review_service.current', AsyncMock(return_value={'description':'','tags':[],'tag_sources':[]}))
    await queue._process_task(SimpleNamespace(id='task',type='analyze_image',payload={'image_id':1,'force_analyze':True}),0)
    vision.assert_awaited_once()
    update.assert_awaited_once()
    embed.assert_awaited_once()
    assert not completed.await_args.args[1].get('pending_review')


async def test_custom_instructions_are_separate_logged_and_do_not_leak_between_requests(vision_transport):
    requests, _, _ = vision_transport
    service = VisionService()
    custom = '重点描述表情和动作，保留图中文字'
    first = await service.analyze_image_base64(b'image', category_id=5, analysis_instructions=custom)
    content = requests[0]['messages'][0]['content']
    assert '分类独立要求' in content[0]['text']
    assert custom not in content[0]['text'] and custom not in content[1]['text']
    assert custom in content[2]['text'] and content[3]['type'] == 'image_url'
    assert first.request_metadata['analysis_instructions'] == custom
    assert first.request_metadata['input_messages'][0]['content'] == content[:3]
    await service.analyze_image_base64(b'image', category_id=5)
    second = requests[1]['messages'][0]['content']
    assert len(second) == 3 and all(custom not in part.get('text', '') for part in second)


async def test_pending_tasks_merge_only_when_custom_instructions_match(queue, monkeypatch):
    active = [SimpleNamespace(id='default', status='pending', payload={'image_id': 1})]

    async def create(session, *, task_id, task_type, payload):
        active.append(SimpleNamespace(id=task_id, status='pending', payload=payload))

    monkeypatch.setattr('imgtag.services.task_queue.task_repository.list_active_for_images', AsyncMock(side_effect=lambda *args: active))
    monkeypatch.setattr('imgtag.services.task_queue.task_repository.create_task', create)
    first = await queue.enqueue_tasks([1], force_analyze=False, analysis_instructions=' 描述动作 ')
    second = await queue.enqueue_tasks([1], force_analyze=True, analysis_instructions='描述动作')
    third = await queue.enqueue_tasks([1], force_analyze=True, analysis_instructions='描述文字')
    assert first['added'] == third['added'] == 1 and second['existing'] == 1
    assert len(active) == 3 and active[0].payload == {'image_id': 1}
    assert active[1].payload['analysis_instructions'] == '描述动作'
    assert active[1].payload['force_analyze'] is True
    assert active[2].payload['analysis_instructions'] == '描述文字'


async def test_worker_passes_custom_instructions_and_forces_real_analysis(queue, processing):
    vision, update, embed, completed, resolve = processing
    await queue._process_task(SimpleNamespace(id='custom', type='analyze_image', payload={
        'image_id': 1, 'force_analyze': False, 'analysis_instructions': '只关注表情',
    }), 0)
    assert vision.await_count == 1
    assert vision.await_args.kwargs['analysis_instructions'] == '只关注表情'
    assert vision.await_args.kwargs['request_context']['force_analyze'] is True


async def test_default_prompt_keeps_meme_format_and_manages_subject_rules_globally(vision_transport, monkeypatch):
    from imgtag.core.config_defaults import DEFAULT_CONFIG
    requests, _, values = vision_transport
    values.pop('vision_prompt')
    module = importlib.import_module('imgtag.services.vision_service')
    category = 'description 格式：主体: xxx。文字: xxx。心情/氛围: xxx。表述含义: xxx。'
    monkeypatch.setattr(module.tag_repository, 'get_by_id', AsyncMock(
        return_value=SimpleNamespace(level=0, name='表情包', prompt=category)))
    await VisionService().analyze_image_base64(b'image', category_id=5,
        subject_contexts=[{'subject_id': 1, 'name': '菲比', 'status': 'confirmed'}])
    text = requests[0]['messages'][0]['content']
    assert DEFAULT_CONFIG['vision_prompt'] in text[0]['text']
    assert '每次分析只对应一份图片资产' in text[0]['text']
    assert '一个资产中可以包含多个主体' in text[0]['text']
    assert text[0]['text'].endswith(category)
    assert '自然融合到对应的主体段' in text[0]['text']
    assert '分类提示词负责 description 的具体结构' in text[0]['text']
    assert '菲比' in text[1]['text'] and 'subject_checks' in text[1]['text']
    # 管理员编辑的主体融合规则直接生效，不再追加另一套隐藏规则。
    values['vision_prompt'] = '管理员规则：保留四段，主体段使用规范名称'
    await VisionService().analyze_image_base64(b'image', category_id=5)
    edited = requests[1]['messages'][0]['content'][0]['text']
    assert values['vision_prompt'] in edited
    assert '# 主体资料使用规则' not in edited


@pytest.mark.parametrize('saved', ['custom', 'empty', 'legacy', 'current', 'legacy_edited'])
def test_prompt_migration_preserves_custom_config_and_matches_defaults(monkeypatch, saved):
    from pathlib import Path
    import runpy
    from sqlalchemy import create_engine, text
    from imgtag.core.config_defaults import DEFAULT_CONFIG
    migration = runpy.run_path(str(Path(__file__).parents[2] / 'src/imgtag/alembic/versions/0007_subject_workflow.py'))
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL)'))
        original = {'custom': '自定义全局规则', 'empty': '', 'legacy': migration['LEGACY_VISION_PROMPT'],
                    'current': DEFAULT_CONFIG['vision_prompt'], 'legacy_edited': migration['LEGACY_VISION_PROMPT'] + '\n额外要求'}[saved]
        connection.execute(text("INSERT INTO config VALUES ('vision_prompt', :prompt), ('vision_model', 'test-model')"), {'prompt': original})
        monkeypatch.setattr(migration['op'], 'execute', connection.execute)
        migration['update_default_prompt']()
        values = dict(connection.execute(text('SELECT key, value FROM config')).all())
        assert values['vision_prompt'] == (migration['LEGACY_VISION_PROMPT'] + '\n\n' + migration['RULES'] if saved == 'legacy' else original)
        assert values['vision_model'] == 'test-model'
        migration['update_default_prompt']()
        assert connection.execute(text("SELECT value FROM config WHERE key='vision_prompt'")).scalar_one() == values['vision_prompt']
    engine.dispose()


async def test_reanalysis_backs_up_latest_content_then_replaces_without_review(queue, processing, monkeypatch):
    _, update, embed, completed, _ = processing
    latest = {'description': '分析期间用户编辑的内容', 'tags': ['人工标签']}
    monkeypatch.setattr('imgtag.services.task_queue.analysis_review_service.current', AsyncMock(return_value=latest))
    backup = AsyncMock()
    monkeypatch.setattr('imgtag.services.task_queue.analysis_review_service.history', backup)
    async def write(session, image, **values):
        assert backup.await_count == 1
        assert backup.await_args.args[2] == latest
        assert image.embedding is None
    update.side_effect = write
    await queue._process_task(SimpleNamespace(id='task', type='analyze_image', payload={'image_id': 1, 'force_analyze': True}), 0)
    update.assert_awaited_once()
    assert update.await_args.kwargs['description'] == '新描述'
    embed.assert_awaited_once()
    assert completed.await_args.args[1]['description'] == '新描述'
    assert 'pending_review' not in completed.await_args.args[1]


async def test_model_failure_does_not_replace_or_back_up_current_image(queue, processing, monkeypatch):
    vision, update, embed, completed, _ = processing
    vision.side_effect = ValueError('模型失败')
    backup = AsyncMock()
    monkeypatch.setattr('imgtag.services.task_queue.analysis_review_service.history', backup)
    monkeypatch.setattr(queue, '_mark_task_failed', AsyncMock())
    with pytest.raises(ValueError, match='模型失败'):
        await queue._process_task(SimpleNamespace(id='task', type='analyze_image', payload={'image_id': 1, 'force_analyze': True}), 0)
    backup.assert_not_awaited()
    update.assert_not_awaited()
    embed.assert_not_awaited()
    completed.assert_not_awaited()


async def test_empty_global_and_custom_category_prompts_are_not_replaced_by_defaults(vision_transport, monkeypatch):
    requests, _, values = vision_transport
    values['vision_prompt'] = ''
    module = importlib.import_module('imgtag.services.vision_service')
    custom = '用户自定义分类：description 只输出一句话'
    monkeypatch.setattr(module.tag_repository, 'get_by_id', AsyncMock(
        return_value=SimpleNamespace(level=0, name='表情包', prompt=custom)))
    await VisionService().analyze_image_base64(b'image', category_id=5)
    actual = requests[0]['messages'][0]['content'][0]['text']
    assert custom in actual
    assert '# 主体资料使用规则' not in actual
    assert '主体: xxx。文字: xxx。' not in actual


async def test_batch_enqueue_reads_once_and_preserves_per_image_matching(queue, monkeypatch):
    locks = AsyncMock(return_value=set(range(1, 101)))
    active = AsyncMock(return_value=[SimpleNamespace(id=f't-{i}', status='pending', payload={'image_id': i}) for i in range(1,101)])
    create = AsyncMock()
    monkeypatch.setattr('imgtag.services.task_queue.image_repository.lock_ids', locks)
    monkeypatch.setattr('imgtag.services.task_queue.task_repository.list_active_for_images', active)
    monkeypatch.setattr('imgtag.services.task_queue.task_repository.create_task', create)
    report = await queue.enqueue_tasks([*reversed(range(1,102)), 1], session=Session())
    assert report['existing'] == 100 and report['missing'] == 1 and report['added'] == 0
    assert report['task_ids'] == [f't-{i}' for i in range(1,101)]
    assert locks.await_count == active.await_count == 1
    assert locks.await_args.args[1] == list(range(1,102))
    assert active.await_args.args[1] == list(range(1,101))
    create.assert_not_awaited()
