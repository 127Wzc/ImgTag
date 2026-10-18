"""重分析、队列合并和主体上下文的回归测试。"""

import asyncio
import json
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.dialects import postgresql

from imgtag.services import storage_service, embedding_service, vision_service
from imgtag.services.task_queue import task_queue
from imgtag.services.subject_context_service import subject_context_service
from imgtag.services.vision_service import ImageAnalysisResult, VisionService


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
    monkeypatch.setattr("imgtag.services.task_queue.image_repository.get_by_id_for_update", AsyncMock(return_value=SimpleNamespace(id=1)))
    return task_queue


async def test_force_upgrades_pending_and_deduplicates(queue, monkeypatch):
    pending = SimpleNamespace(id="pending", status="pending", payload={"image_id": 1})
    monkeypatch.setattr("imgtag.services.task_queue.task_repository.list_active_for_image", AsyncMock(return_value=[pending]))
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

    monkeypatch.setattr("imgtag.services.task_queue.task_repository.list_active_for_image", AsyncMock(side_effect=lambda *args: active))
    monkeypatch.setattr("imgtag.services.task_queue.task_repository.create_task", create)
    first = await queue.enqueue_tasks([1], force_analyze=True)
    second = await queue.enqueue_tasks([1], force_analyze=True)
    assert first["waiting"] == first["added"] == 1
    assert second["existing"] == 1
    assert len(active) == 2


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

    async def get(key, default=None, *, fresh=False):
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

    monkeypatch.setattr('imgtag.services.task_queue.task_repository.list_active_for_image', AsyncMock(side_effect=lambda *args: active))
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
    from imgtag.core.config_defaults import SUBJECT_ANALYSIS_RULES, DEFAULT_CONFIG
    migration = runpy.run_path(str(Path(__file__).parents[2] / 'src/imgtag/alembic/versions/0007_subject_workflow.py'))
    assert migration['RULES'] == SUBJECT_ANALYSIS_RULES
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL)'))
        original = {'custom': '自定义全局规则', 'empty': '', 'legacy': migration['LEGACY_VISION_PROMPT'],
                    'current': DEFAULT_CONFIG['vision_prompt'], 'legacy_edited': migration['LEGACY_VISION_PROMPT'] + '\n额外要求'}[saved]
        connection.execute(text("INSERT INTO config VALUES ('vision_prompt', :prompt), ('vision_model', 'test-model')"), {'prompt': original})
        monkeypatch.setattr(migration['op'], 'execute', connection.execute)
        migration['update_default_prompt']()
        values = dict(connection.execute(text('SELECT key, value FROM config')).all())
        assert values['vision_prompt'] == (DEFAULT_CONFIG['vision_prompt'] if saved == 'legacy' else original)
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
