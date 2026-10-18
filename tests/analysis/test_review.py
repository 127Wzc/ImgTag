"""当前分析直接更新、历史备份与主体命名。"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from imgtag.db.repositories.analysis_version import analysis_version_repository as repo
from imgtag.db.repositories import image_repository, image_tag_repository, tag_repository
from imgtag.db.repositories.subject_definition import subject_definition_repository as subject_repo
from imgtag.schemas.analysis_review import CurrentAnalysisSave
from imgtag.schemas.subject import SaveSubjectContent, SubjectExtractionRequest
from imgtag.services.analysis_review_service import analysis_review_service as service
from imgtag.services.subject_analysis_service import review_subject_analysis
from imgtag.services.subject_extraction_service import subject_extraction_service as subject_service, identity_snapshot
from imgtag.services.vision_service import ImageAnalysisResult, VisionService


async def test_current_write_archives_before_replacing_and_enqueues_search(monkeypatch):
    image = SimpleNamespace(id=1, description='原描述', subject_analysis=None, embedding=[1])
    archive = AsyncMock()
    monkeypatch.setattr(service, 'history', archive)
    monkeypatch.setattr(tag_repository, 'get_name_levels', AsyncMock(return_value={}))
    tags = AsyncMock()
    monkeypatch.setattr(image_tag_repository, 'set_image_tags', tags)
    from imgtag.services.task_queue import task_queue
    async def queued(*args, **kwargs):
        assert session.flush.await_count >= 1, "刷新实体锁之前必须先保存本事务的新内容"
    enqueue = AsyncMock(side_effect=queued)
    monkeypatch.setattr(task_queue, 'add_tasks', enqueue)
    session = SimpleNamespace(flush=AsyncMock())
    await service.write_current(session, image, {'description':'原描述'}, '新描述', ['动作'], preserve_manual=True)
    archive.assert_awaited_once()
    assert image.embedding is None and image.description == '新描述'
    assert tags.await_args.kwargs['source'] == 'ai'
    assert enqueue.await_args.kwargs == {'task_type': 'rebuild_vector', 'force_analyze': True, 'session': session}


def test_positive_reference_default_and_trusted_identity_survives_uncertainty():
    request = SubjectExtractionRequest(samples=[{'image_id':1}])
    assert request.samples[0].role == 'positive'
    a = ImageAnalysisResult(description='多个Q版菲比漂浮在水中', tags=['游泳'],
        subject_checks=[{'subject_id':1, 'status':'uncertain', 'evidence':'尺寸较小'}])
    report = review_subject_analysis(a, [{'subject_id':1, 'name':'菲比', 'status':'confirmed'}])
    assert '菲比' in a.description and a.tags == ['游泳','菲比']
    assert report['checks'][0]['status'] == 'supported'
    prompt = VisionService._subject_prompt([{'subject_id':1, 'name':'菲比', 'status':'confirmed'}])
    from imgtag.core.config_defaults import DEFAULT_CONFIG
    assert 'status=confirmed 采用已确认身份，默认核实为 supported' in DEFAULT_CONFIG['vision_prompt']
    assert 'subject_checks' in prompt


def test_missing_subject_name_does_not_prepend_mechanical_identity_statement():
    analysis = ImageAnalysisResult(description='Q版女孩举起双臂，面带笑容', tags=['可爱'])
    report = review_subject_analysis(analysis, [{'subject_id': 1, 'name': '菲比', 'status': 'confirmed'}])
    assert analysis.description == 'Q版女孩举起双臂，面带笑容'
    assert analysis.tags == ['可爱', '菲比']
    assert report['checks'][0]['status'] == 'supported'


def test_subject_review_preserves_structured_description():
    description = '主体：Q版菲比，金发紫眼。\n动作：举起双臂，微笑。\n场景：浅色背景。\n文字：拉电线哈哈。\n风格：卡通表情包。'
    analysis = ImageAnalysisResult(description=description, tags=['金发', '举手', '菲比表情包'])
    review_subject_analysis(analysis, [{'subject_id': 1, 'name': '菲比', 'status': 'confirmed'}])
    assert analysis.description == description
    assert analysis.tags == ['金发', '举手', '菲比']


async def test_history_requires_owner_and_comparison_routes_are_removed(monkeypatch):
    import httpx
    from fastapi import FastAPI
    from imgtag.api.endpoints import analysis_reviews as api
    from imgtag.api.endpoints.auth import get_current_user
    from imgtag.db import get_async_session
    app=FastAPI();app.include_router(api.router)
    app.dependency_overrides[get_current_user]=lambda:{'id':2,'role':'user'}
    app.dependency_overrides[get_async_session]=lambda:SimpleNamespace()
    monkeypatch.setattr(image_repository,'get_by_id',AsyncMock(return_value=SimpleNamespace(uploaded_by=1)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/1')).status_code==403
        assert (await client.delete('/1/2')).status_code==403
        assert (await client.post('/1/2/restore',json={'expected_snapshot':{}})).status_code==403
        assert (await client.patch('/1/2',json={'description':'x','tags':[],'expected_revision':0})).status_code==405
        assert (await client.put('/1/current',json={'description':'x','tags':[],'expected_snapshot':{}})).status_code==403
        assert (await client.post('/1/2/decide',json={'action':'adopt','expected_revision':0,'expected_snapshot':{}})).status_code==404


@pytest.mark.parametrize('changed', [False,True])
async def test_search_vector_skips_stale_content(monkeypatch,changed):
    import importlib
    module=importlib.import_module('imgtag.services.embedding_service')
    service=module.embedding_service
    class Session:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def commit(self):pass
    monkeypatch.setattr(module,'async_session_maker',Session)
    monkeypatch.setattr(service,'get_embedding_combined',AsyncMock(return_value=[1]))
    monkeypatch.setattr(image_repository,'get_by_id_for_update',AsyncMock(return_value=SimpleNamespace(description='用户刚修改' if changed else '原描述')))
    monkeypatch.setattr(image_repository,'get_image_tags_with_source',AsyncMock(return_value=[{'name':'标签','level':2}]))
    update=AsyncMock();monkeypatch.setattr(image_repository,'update_image',update)
    assert await service.save_embedding_for_image(1,'原描述',['标签']) is not changed
    if changed:update.assert_not_awaited()
    else:update.assert_awaited_once()


async def test_multiple_unambiguous_manual_tags_provide_trusted_names(monkeypatch):
    from imgtag.services.subject_context_service import subject_context_service
    from imgtag.db.repositories import image_subject_repository,subject_repository
    subjects=[SimpleNamespace(id=i,name=name,aliases=[],description='',is_active=True,updated_at='v1',
                              primary_tag_id=tag,alias_tag_ids=[],definition_revision=1) for i,name,tag in [(1,'菲比',10),(2,'糯糯',20)]]
    monkeypatch.setattr(image_subject_repository,'get_current',AsyncMock(return_value=[]))
    monkeypatch.setattr(image_subject_repository,'has_explicit_selection',AsyncMock(return_value=False))
    monkeypatch.setattr(image_repository,'get_image_tags_with_source',AsyncMock(return_value=[{'id':10,'source':'user','level':2},{'id':20,'source':'user','level':2}]))
    monkeypatch.setattr(subject_repository,'list_matching_tags',AsyncMock(return_value=subjects))
    result=await subject_context_service.resolve(None,1)
    assert [(c['name'],c['status']) for c in result]==[('菲比','confirmed'),('糯糯','confirmed')]


@pytest.mark.parametrize('colon', [': ', '：'])
@pytest.mark.parametrize('status', ['uncertain', 'conflict'])
def test_meme_identity_fallback_keeps_ocr_mood_and_meaning(colon, status):
    tail = f'。文字{colon}菲比你在干嘛。心情/氛围{colon}无奈、疑惑。表述含义{colon}表达对离谱行为的疑问。'
    analysis = ImageAnalysisResult(
        description=f'主体{colon}菲比举手' + tail, tags=['菲比', '疑惑'],
        subject_checks=[{'subject_id': 1, 'status': status, 'evidence': '外观不一致'}],
        subject_observations=[{'position': '中央', 'appearance': '粉发角色举手'}],
    )
    review_subject_analysis(analysis, [{'subject_id': 1, 'name': '菲比', 'status': 'candidate'}])
    assert analysis.description == f'主体{colon}中央：粉发角色举手' + tail
    assert analysis.tags == ['疑惑']


def test_meme_ocr_name_is_not_an_identity_assertion():
    description = '主体: 粉发角色举手。文字: 菲比你在干嘛。心情/氛围: 疑惑、无奈。表述含义: 询问对方行为。'
    analysis = ImageAnalysisResult(description=description, tags=['疑惑'])
    review_subject_analysis(analysis, [{'subject_id': 1, 'name': '菲比', 'status': 'candidate'}])
    assert analysis.description == description


async def test_subject_manual_update_backs_up_previous_content(monkeypatch):
    subject = SimpleNamespace(id=1, name='菲比', aliases=[], description='原定义', recognition_notes='原备注',
                              is_active=True, definition_revision=2)
    monkeypatch.setattr(subject_repo, 'lock_subject', AsyncMock(return_value=subject))
    backups = []
    async def create(session, **values):
        assert subject.description == '原定义'
        backups.append(values)
    monkeypatch.setattr(subject_repo, 'create', create)
    await subject_service.save_current(SimpleNamespace(flush=AsyncMock()), 1,
        SaveSubjectContent(definition='新定义', recognition_notes='新备注', expected_revision=2), 1)
    assert backups[0]['state'] == 'history'
    assert backups[0]['definition'] == '原定义' and backups[0]['recognition_notes'] == '原备注'
    assert subject.description == '新定义' and subject.recognition_notes == '新备注'
    assert subject.definition_revision == 3
    with pytest.raises(HTTPException) as error:
        await subject_service.save_current(None, 1, SaveSubjectContent(definition='过期', expected_revision=2), 1)
    assert error.value.status_code == 409 and len(backups) == 1


@pytest.mark.parametrize('rollback', [False, True])
async def test_image_history_keeps_three_previous_results_and_rolls_back(rollback):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    class LocalSession:
        def __init__(self, sync): self.sync = sync
        def add(self, row): self.sync.add(row)
        async def flush(self): self.sync.flush()
        async def refresh(self, row): self.sync.refresh(row)
        async def execute(self, statement): return self.sync.execute(statement)
    engine = create_engine('sqlite://')
    with Session(engine, expire_on_commit=False) as sync:
        sync.execute(text('''CREATE TABLE image_analysis_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, image_id INTEGER NOT NULL, task_id TEXT,
            state TEXT NOT NULL, pending BOOLEAN NOT NULL, revision INTEGER NOT NULL,
            description TEXT NOT NULL, tags TEXT NOT NULL, subject_analysis TEXT,
            base_snapshot TEXT NOT NULL, metadata_snapshot TEXT NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)'''))
        sync.commit()
        session = LocalSession(sync)
        image = SimpleNamespace(id=1, subject_analysis=None)
        for i in range(5):
            await service.history(session, image, {'description': f'旧描述{i}', 'tags': [f'标签{i}']})
        other = SimpleNamespace(id=2, subject_analysis=None)
        await service.history(session, other, {'description': '其他图片', 'tags': []})
        sync.commit()
        await service.history(session, image, {'description': '上一版', 'tags': ['动作']})
        if rollback: sync.rollback()
        else: sync.commit()
        rows = await repo.versions(session, 1)
        assert [r.description for r in rows] == (['旧描述4', '旧描述3', '旧描述2'] if rollback else ['上一版', '旧描述4', '旧描述3'])
        assert len(await repo.versions(session, 2)) == 1
        assert await repo.versions(session, 1, offset=3) == []
    engine.dispose()


@pytest.mark.parametrize('failure', [None, 'stale', 'missing'])
async def test_image_restore_checks_current_and_reuses_backup_and_search_flow(monkeypatch, failure):
    image = SimpleNamespace(id=1)
    current = {'description': '当前描述', 'tags': ['当前标签']}
    expected = {**current, 'description': '过期描述'} if failure == 'stale' else current
    monkeypatch.setattr(image_repository, 'get_by_id_for_update', AsyncMock(return_value=image))
    monkeypatch.setattr(service, 'locked_current', AsyncMock(return_value=current))
    monkeypatch.setattr(service, 'current', AsyncMock(return_value={'description': '历史描述'}))
    source = SimpleNamespace(description='历史描述', tags=['历史标签'], subject_analysis={'checks': []})
    monkeypatch.setattr(repo, 'get_history', AsyncMock(return_value=None if failure == 'missing' else source))
    write = AsyncMock()
    monkeypatch.setattr(service, 'write_current', write)
    if failure:
        with pytest.raises(HTTPException) as error:
            await service.restore(None, 1, 2, expected)
        assert error.value.status_code == (409 if failure == 'stale' else 404)
        write.assert_not_awaited()
        return
    await service.restore(None, 1, 2, expected)
    assert write.await_args.args == (None, image, current, '历史描述', ['历史标签'])
    assert write.await_args.kwargs == {'preserve_manual': False, 'assessment': {'checks': []}}


async def test_restoring_image_replaces_normal_tags_backs_up_current_and_rebuilds_vector(monkeypatch):
    image = SimpleNamespace(id=1, description='当前', subject_analysis=None, embedding=[1])
    backups = AsyncMock()
    monkeypatch.setattr(service, 'history', backups)
    monkeypatch.setattr(tag_repository, 'get_name_levels', AsyncMock(return_value={'旧标签': 2}))
    monkeypatch.setattr(tag_repository, 'get_or_create', AsyncMock(return_value=SimpleNamespace(id=9)))
    tags = AsyncMock()
    monkeypatch.setattr(image_tag_repository, 'set_image_tags_by_ids', tags)
    from imgtag.services.task_queue import task_queue
    queue = AsyncMock()
    monkeypatch.setattr(task_queue, 'add_tasks', queue)
    session = SimpleNamespace(flush=AsyncMock())
    await service.write_current(session, image, {'description':'当前', 'tags':['当前标签']}, '旧描述', ['旧标签'],
                                preserve_manual=False, assessment={'checks': []})
    assert backups.await_args.args[2]['description'] == '当前'
    assert image.description == '旧描述' and image.embedding is None and image.subject_analysis == {'checks': []}
    assert tags.await_args.args == (session, 1, [9])
    assert queue.await_args.kwargs['task_type'] == 'rebuild_vector'


@pytest.mark.parametrize('missing', [False, True])
async def test_delete_image_history_keeps_current_and_other_backups(monkeypatch, missing):
    image = SimpleNamespace(id=1, description='当前描述', embedding=[1], subject_analysis={'checks': []})
    source = SimpleNamespace(id=2)
    monkeypatch.setattr(image_repository, 'get_by_id_for_update', AsyncMock(return_value=image))
    read = AsyncMock(return_value=None if missing else source)
    monkeypatch.setattr(repo, 'get_history', read)
    delete = AsyncMock()
    monkeypatch.setattr(repo, 'delete', delete)
    if missing:
        with pytest.raises(HTTPException) as error:
            await service.delete_history(None, 1, 2)
        assert error.value.status_code == 404
        delete.assert_not_awaited()
    else:
        await service.delete_history(None, 1, 2)
        delete.assert_awaited_once_with(None, source)
    read.assert_awaited_once_with(None, 1, 2)
    assert image.description == '当前描述' and image.embedding == [1] and image.subject_analysis == {'checks': []}


async def test_owner_can_delete_one_image_backup_and_commit(monkeypatch):
    import httpx
    from fastapi import FastAPI
    from imgtag.api.endpoints import analysis_reviews as api
    from imgtag.api.endpoints.auth import get_current_user
    from imgtag.db import get_async_session
    app = FastAPI()
    app.include_router(api.router)
    session = SimpleNamespace(commit=AsyncMock())
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: {'id': 1, 'role': 'user'}
    monkeypatch.setattr(image_repository, 'get_by_id', AsyncMock(return_value=SimpleNamespace(uploaded_by=1)))
    delete = AsyncMock()
    monkeypatch.setattr(service, 'delete_history', delete)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.delete('/1/2')
    assert response.status_code == 204 and response.content == b''
    delete.assert_awaited_once_with(session, 1, 2)
    session.commit.assert_awaited_once()


def test_public_snapshot_hides_subject_details_but_still_detects_revision_changes():
    from imgtag.services.analysis_review_service import public_snapshot, check_snapshot
    current = {'description':'图片描述','tags':['标签'],'subjects':[{
        'subject_id':7,'name':'主体','definition':'内部定义','recognition_notes':'内部备注',
        'aliases':['别名'],'version':'v1','definition_revision':1,'source':'manual','status':'confirmed'}]}
    public = public_snapshot(current)
    assert public['subjects'] == [{'subject_id':7,'name':'主体','version':'v1',
        'definition_revision':1,'source':'manual','status':'confirmed'}]
    check_snapshot(current, public)
    current['subjects'][0]['definition_revision'] = 2
    with pytest.raises(HTTPException) as error:
        check_snapshot(current, public)
    assert error.value.status_code == 409
