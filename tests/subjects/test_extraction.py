"""主体提炼：参考图边界、数量限制、输入快照与重复提交。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
import httpx
import pytest

from imgtag.api.endpoints import config as config_api, subjects as subjects_api
from imgtag.api.endpoints.auth import get_current_user
from imgtag.core.config_defaults import DEFAULT_CONFIG
from imgtag.core.subject_extraction_limits import SUBJECT_EXTRACTION_LIMIT_KEY
from imgtag.db import get_async_session
from imgtag.db.repositories import config_repository, image_repository, subject_repository, task_repository
from imgtag.db.repositories.subject_definition import subject_definition_repository
from imgtag.schemas.subject import SubjectExtractionRequest
from imgtag.services.subject_extraction_service import subject_extraction_service as extraction, subject_extraction_service as service


async def test_default_three_blocks_four_before_reading_images_or_creating_task(monkeypatch):
    monkeypatch.setattr(config_repository, 'get_value', AsyncMock(return_value=None))
    images = AsyncMock(); create = AsyncMock()
    monkeypatch.setattr(image_repository, 'get_by_id', images)
    monkeypatch.setattr(task_repository, 'create_task', create)
    with pytest.raises(ValidationError):
        SubjectExtractionRequest(samples=[{'image_id':i} for i in range(1,5)])
    with pytest.raises(HTTPException) as exc:
        await service.check_image_limit(None, 4)
    assert exc.value.status_code == 400 and '最多3张' in exc.value.detail
    assert DEFAULT_CONFIG[SUBJECT_EXTRACTION_LIMIT_KEY] == '3'
    images.assert_not_awaited(); create.assert_not_awaited()


@pytest.mark.parametrize('configured,count', [(None,3),('2',2)])
async def test_configured_boundary_allows_all_selected_references(monkeypatch,configured,count):
    monkeypatch.setattr(config_repository,'get_value',AsyncMock(return_value=configured))
    subject=SimpleNamespace(id=1,name='菲比',aliases=[],description='',is_active=True,definition_revision=0,primary_tag_id=10)
    monkeypatch.setattr(subject_repository,'get_by_id',AsyncMock(return_value=subject))
    monkeypatch.setattr(subject_repository,'eligible_reference_ids',AsyncMock(return_value=set(range(1,count+1))))
    images=AsyncMock(return_value=SimpleNamespace(file_type='png',file_hash='sample'))
    monkeypatch.setattr(image_repository,'get_by_id',images)
    request=SubjectExtractionRequest(samples=[{'image_id':i} for i in range(1,count+1)])
    snapshot=await service.build_input(None,1,request)
    assert len(snapshot['samples'])==count and snapshot['max_images']==count
    assert images.await_count==count


@pytest.mark.parametrize('changed_during_download', [False,True])
async def test_queued_task_rechecks_latest_limit_and_never_calls_model_when_over_budget(monkeypatch,changed_during_download):
    class Session:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
    monkeypatch.setattr('imgtag.services.subject_extraction_service.async_session_maker',Session)
    monkeypatch.setattr(task_repository,'get_by_id',AsyncMock(return_value=None))
    # 两张参考图在旧设置允许；最新上限降为1时，开始读取前或模型调用前拦截。
    monkeypatch.setattr(config_repository,'get_value',AsyncMock(side_effect=['3','1'] if changed_during_download else ['1']))
    storage=AsyncMock(return_value=b'picture')
    model=AsyncMock()
    monkeypatch.setattr('imgtag.services.subject_extraction_service.storage_service.get_file_content',storage)
    monkeypatch.setattr('imgtag.services.subject_extraction_service.vision_service.extract_subject',model)
    payload={'snapshot':{'samples':[{'image_id':1,'role':'positive','target':'左'},{'image_id':2,'role':'positive','target':'右'}],'prompt':'提炼','max_images':6}}
    with pytest.raises(HTTPException) as exc:
        await service.process('queued',payload)
    assert exc.value.status_code==400 and '最多1张' in exc.value.detail
    assert storage.await_count==(2 if changed_during_download else 0)
    model.assert_not_awaited()


@pytest.mark.parametrize('value',['0','4','12','13','3.5'])
async def test_both_config_write_routes_reject_invalid_limit_before_any_write(monkeypatch,value):
    writes=AsyncMock();single=AsyncMock()
    monkeypatch.setattr(config_repository,'update_multiple',writes)
    monkeypatch.setattr(config_repository,'set_value',single)
    with pytest.raises(HTTPException) as batch:
        await config_api.update_configs(config_api.ConfigUpdate(configs={SUBJECT_EXTRACTION_LIMIT_KEY:value}),{},None)
    with pytest.raises(HTTPException) as one:
        await config_api.update_single_config(SUBJECT_EXTRACTION_LIMIT_KEY,value,{},None)
    assert batch.value.status_code==one.value.status_code==400
    writes.assert_not_awaited();single.assert_not_awaited()


async def test_invalid_persisted_setting_fails_closed(monkeypatch):
    monkeypatch.setattr(config_repository,'get_value',AsyncMock(return_value='invalid'))
    with pytest.raises(HTTPException) as exc:
        await service.get_max_images(None)
    assert exc.value.status_code==503


async def test_settings_endpoint_returns_effective_limit_and_requires_admin(monkeypatch):
    app=FastAPI();app.include_router(subjects_api.router,prefix='/subjects')
    user={'id':1,'role':'admin'}
    app.dependency_overrides[get_current_user]=lambda:user
    app.dependency_overrides[get_async_session]=lambda:None
    monkeypatch.setattr(config_repository,'get_value',AsyncMock(return_value='2'))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/subjects/extraction-settings')
        assert response.status_code==200 and response.json()=={'max_images':2}
        user['role']='user'
        assert (await client.get('/subjects/extraction-settings')).status_code==403


@pytest.mark.parametrize("status", ["pending", "processing"])
async def test_active_extraction_rejects_duplicate_without_rebuilding_input(monkeypatch, status):
    calls = []

    subject = SimpleNamespace(is_active=True, cover_image_id=99)

    async def lock(*args):
        calls.append("lock")
        return subject

    async def active(*args):
        calls.append("active")
        return SimpleNamespace(id="existing", status=status)

    monkeypatch.setattr(service, "check_image_limit", AsyncMock())
    monkeypatch.setattr(subject_definition_repository, "lock_subject", lock)
    monkeypatch.setattr(task_repository, "get_active_subject_extraction", active)
    build = AsyncMock()
    create = AsyncMock()
    monkeypatch.setattr(service, "build_input", build)
    monkeypatch.setattr(task_repository, "create_task", create)
    with pytest.raises(HTTPException) as exc:
        await service.enqueue(None, 1, SubjectExtractionRequest(samples=[{"image_id": 18}]), 1)
    assert exc.value.status_code == 409
    assert "任务队列" in exc.value.detail
    assert calls == ["lock", "active"]
    build.assert_not_awaited()
    create.assert_not_awaited()
    assert subject.cover_image_id == 99


async def test_new_submission_keeps_snapshot_and_actor_after_lock(monkeypatch):
    calls = []

    subject = SimpleNamespace(is_active=True, cover_image_id=99)

    async def lock(*args):
        calls.append("lock")
        return subject

    async def active(*args):
        calls.append("active")
        return None

    async def build(*args):
        calls.append("build")
        return {"prompt": "本次主体提炼", "base_revision": 3}

    monkeypatch.setattr(service, "check_image_limit", AsyncMock())
    monkeypatch.setattr(subject_definition_repository, "lock_subject", lock)
    monkeypatch.setattr(task_repository, "get_active_subject_extraction", active)
    monkeypatch.setattr(service, "build_input", build)
    create = AsyncMock()
    monkeypatch.setattr(task_repository, "create_task", create)
    task_id = await service.enqueue(None, 7, SubjectExtractionRequest(samples=[{"image_id": 18}]), 2)
    assert calls == ["lock", "active", "build"]
    assert create.await_args.args == (None, task_id, "extract_subject", {
        "subject_id": 7, "actor_id": 2,
        "snapshot": {"prompt": "本次主体提炼", "base_revision": 3},
    })

    assert subject.cover_image_id == 18


async def test_reference_selection_rejects_untagged_image_before_loading_or_calling_model(monkeypatch):
    monkeypatch.setattr(extraction, 'check_image_limit', AsyncMock(return_value=3))
    monkeypatch.setattr(subject_repository, 'get_by_id', AsyncMock(return_value=SimpleNamespace(is_active=True, primary_tag_id=10)))
    monkeypatch.setattr(subject_repository, 'eligible_reference_ids', AsyncMock(return_value={1}))
    images = AsyncMock()
    monkeypatch.setattr(image_repository, 'get_by_id', images)
    with pytest.raises(HTTPException) as error:
        await extraction.build_input(None, 7, SubjectExtractionRequest(samples=[{'image_id': 1}, {'image_id': 2}]))
    assert error.value.status_code == 400 and '主名称标签' in error.value.detail
    images.assert_not_awaited()


@pytest.mark.parametrize('model_fails', [False, True])
async def test_extraction_applies_immediately_with_old_definition_backup(monkeypatch, model_fails):
    from copy import deepcopy
    module = 'imgtag.services.subject_extraction_service'
    subject = SimpleNamespace(id=1, name='菲比', aliases=[], description='原定义', recognition_notes='保留备注',
                              is_active=True, definition_revision=2)
    snapshot = {'subject': {'id': 1, 'name': '菲比', 'aliases': [], 'is_active': True},
                'samples': [{'image_id': 10, 'role': 'positive', 'target': '中央'}],
                'prompt': '提炼', 'identity_background': '', 'base_revision': 2}
    task = SimpleNamespace(result={})
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def commit(self): pass
    monkeypatch.setattr(module + '.async_session_maker', Session)
    monkeypatch.setattr(task_repository, 'get_by_id', AsyncMock(return_value=task))
    monkeypatch.setattr(service, 'check_image_limit', AsyncMock(return_value=3))
    monkeypatch.setattr(subject_definition_repository, 'lock_subject', AsyncMock(return_value=subject))
    monkeypatch.setattr(module + '.storage_service.get_file_content', AsyncMock(return_value=b'picture'))
    evidence = {'analysis_context': '提炼出的新定义', 'distinguishing_features': [],
                'observed_variations': [], 'confusions': [], 'unresolved': [], 'proposed_changes': []}
    model = AsyncMock(return_value=(evidence, {'model': 'test'}))
    if model_fails: model.side_effect = ValueError('模型失败')
    monkeypatch.setattr(module + '.vision_service.extract_subject', model)
    backups = []
    async def backup(session, **values): backups.append(deepcopy(values))
    monkeypatch.setattr(subject_definition_repository, 'create', backup)
    samples = AsyncMock()
    monkeypatch.setattr(module + '.subject_sample_repository.create_sample', samples)
    payload = {'subject_id': 1, 'actor_id': 7, 'snapshot': snapshot}
    if model_fails:
        with pytest.raises(ValueError, match='模型失败'):
            await service.process('task', payload)
        assert not backups and subject.description == '原定义'
        assert subject.definition_revision == 2
        return
    result = await service.process('task', payload)
    assert result['applied'] is True and 'version_id' not in result
    assert subject.description == '提炼出的新定义' and subject.definition_revision == 3
    assert subject.recognition_notes == '保留备注'
    assert backups[0]['definition'] == '原定义' and backups[0]['recognition_notes'] == '保留备注'
    assert backups[0]['state'] == 'history'
    assert samples.await_count == 1
    # 重试复用同一事务内保存的已应用标记，避免重复调用模型或备份。
    assert await service.process('task', payload) == result
    assert model.await_count == 1 and len(backups) == 1
