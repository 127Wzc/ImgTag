"""真实 PostgreSQL 的主体关联、标签标记与迁移；使用隔离 schema 并全量回滚。"""

import importlib
import json
import logging
import math
import random
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints import subjects as api
from imgtag.api.endpoints import auth, images as image_api, mcp
from imgtag.core import config_cache as cache_module
from imgtag.db import get_async_session
from imgtag.db.repositories import image_repository, subject_repository
from imgtag.models import Base, Image, ImageLocation, ImageSubject, ImageTag, StorageEndpoint, Subject, SubjectSample, Tag, User
from imgtag.schemas.subject import SubjectCreate
from imgtag.services.search_service import SearchOptions, SearchService
from imgtag.services.embedding_service import embedding_service
from imgtag.services.search_guard_service import SearchGuardService, search_guard
from imgtag.db.repositories.vector_index import vector_index_repository, INDEX_NAME
from imgtag.services.subject_gallery_service import subject_gallery_service as gallery

pytestmark = pytest.mark.postgres
workflow_migration = importlib.import_module("imgtag.alembic.versions.0007_subject_workflow")
search_migration = importlib.import_module("imgtag.alembic.versions.0008_search_indexes")


async def test_readonly_search_returns_connection_before_model_and_reuses_session(postgres_connection, monkeypatch):
    engine = postgres_connection.engine
    checked_out = engine.pool.checkedout()
    service = SearchService()
    monkeypatch.setattr(service, 'query_terms', AsyncMock(return_value={}))
    monkeypatch.setattr(service, 'load_options', AsyncMock(return_value=SearchOptions()))

    async with AsyncSession(engine) as session:
        await session.execute(text('SELECT 1'))
        assert engine.pool.checkedout() == checked_out + 1

        async def embedding(*args, **kwargs):
            assert kwargs['session'] is None
            assert engine.pool.checkedout() == checked_out
            return [1., 0.]

        async def query(current, **kwargs):
            assert current is session
            assert await current.scalar(text('SELECT 1')) == 1
            return []

        monkeypatch.setattr(embedding_service, 'get_embedding', embedding)
        monkeypatch.setattr(image_repository, 'hybrid_search', query)
        await service.search(session, text='猫', release_connection=True)
    assert engine.pool.checkedout() == checked_out


async def test_hybrid_scores_and_visibility_match_reference_after_narrow_materialization(postgres_connection):
    conn = postgres_connection
    await conn.run_sync(Base.metadata.create_all)
    await conn.execute(text('ALTER TABLE images ALTER COLUMN embedding TYPE vector(4) USING NULL::vector(4)'))
    async with AsyncSession(bind=conn, expire_on_commit=False) as session:
        owner = User(username='score-owner', password_hash='synthetic')
        category, other = Tag(name='类别', level=0), Tag(name='其他类', level=0)
        primary, alias, emotion = [Tag(name=name, level=2) for name in ['主体', '别名', '情绪']]
        session.add_all([owner, category, other, primary, alias, emotion]); await session.flush()
        session.add(Subject(name='主体', category_tag_id=category.id, primary_tag_id=primary.id, alias_tag_ids=[alias.id]))
        rng = random.Random(7331)
        data = []
        for i in range(1, 81):
            vector = None if i % 11 == 0 else [0., 0., 0., 0.] if i % 13 == 0 else [rng.uniform(-1, 1) for _ in range(4)]
            tag_ids = {category.id if i % 3 else other.id}
            if i % 2 == 0: tag_ids.add(primary.id)
            if i % 7 == 0: tag_ids.add(alias.id)
            if i % 3 == 0: tag_ids.add(emotion.id)
            image = Image(description=f'图片{i}', embedding=vector, is_public=i % 5 != 0,
                          uploaded_by=owner.id if i % 5 == 0 else None)
            session.add(image); await session.flush()
            session.add_all([ImageTag(image_id=image.id, tag_id=tag_id) for tag_id in tag_ids])
            data.append((image, vector, tag_ids))
        await session.flush()
        await session.execute(text(f'CREATE INDEX {INDEX_NAME} ON images USING hnsw (embedding vector_cosine_ops)'))
        await image_repository.configure_hnsw(session, 100)
        query_vector = [1., .2, -.3, .4]
        for filters in [{}, {'visible_to_user_id':owner.id}, {'skip_visibility_filter':True},
                        {'category_id':other.id}, {'tags':['别名','情绪']}]:
            expected = []
            for image, vector, tag_ids in data:
                if not filters.get('skip_visibility_filter') and not image.is_public and image.uploaded_by != filters.get('visible_to_user_id'):
                    continue
                if filters.get('category_id') and filters['category_id'] not in tag_ids:
                    continue
                subject_hit = bool(tag_ids & {primary.id, alias.id})
                emotion_hit = emotion.id in tag_ids
                if filters.get('tags') and not (subject_hit and emotion_hit):
                    continue
                norm = math.hypot(*vector) * math.hypot(*query_vector) if vector else 0
                semantic = sum(a*b for a,b in zip(vector, query_vector)) / norm if norm else 0
                tag_score = (2*subject_hit + emotion_hit)/3
                if semantic > .15 or tag_score > 0:
                    expected.append((image.id, semantic, tag_score, .7*semantic+.3*tag_score))
            expected.sort(key=lambda row:(row[3],row[0]), reverse=True)
            for candidate_limit in (None, 200):
                actual = await image_repository.hybrid_search(
                    session, query_vector=query_vector, query_text='主体 情绪',
                    query_tag_weights={'主体':2.,'情绪':1.}, limit=20, candidate_limit=candidate_limit, **filters,
                )
                assert [row['id'] for row in actual] == [row[0] for row in expected[:20]]
                for row, reference in zip(actual, expected):
                    assert (row['vector_score'], row['tag_score'], row['similarity']) == pytest.approx(reference[1:], abs=1e-6)


async def test_search_sql_chains_reuse_connection_and_avoid_redundant_reads(postgres_connection, monkeypatch, caplog):
    """执行真实 ORM/候选/地址查询，核对查询数、字段投影与可见性。"""
    conn = postgres_connection
    caplog.set_level(logging.DEBUG, logger='imgtag.search')
    await conn.run_sync(Base.metadata.create_all)
    await conn.execute(text('ALTER TABLE images ALTER COLUMN embedding TYPE vector(3) USING NULL::vector(3)'))
    async with AsyncSession(bind=conn, expire_on_commit=False) as session:
        owner = User(username='search-owner', password_hash='synthetic-test-hash')
        tag = Tag(name='猫', level=2)
        endpoint = StorageEndpoint(name='search-local', provider='local', bucket_name='uploads')
        session.add_all([owner, tag, endpoint]); await session.flush()
        owner_id = owner.id
        images = [Image(description='猫', embedding=[1,0,0], uploaded_by=owner_id),
                  Image(description='私有猫', embedding=[1,0,0], uploaded_by=owner_id, is_public=False)]
        session.add_all(images); await session.flush()
        for image in images:
            session.add(ImageTag(image_id=image.id, tag_id=tag.id))
            session.add(ImageLocation(image_id=image.id, endpoint_id=endpoint.id, object_key=f'{image.id}.jpg'))
        await session.flush()
        service = SearchService()
        monkeypatch.setattr(image_api, 'search_service', service)
        monkeypatch.setattr(mcp, 'search_service', service)
        monkeypatch.setattr(embedding_service, 'get_embedding', AsyncMock(return_value=[1.,0.,0.]))
        monkeypatch.setattr(auth.auth_service, 'decode_token', lambda token: {'sub': str(owner_id)})
        storage_module = importlib.import_module('imgtag.services.storage_service')
        monkeypatch.setattr(storage_module, 'async_session_maker', lambda: pytest.fail('搜索不能嵌套借连接'))
        app = FastAPI()
        app.include_router(image_api.router, prefix='/images')
        async def request_session():
            # 与生产一致：每个请求独立会话，请求内所有依赖复用该会话。
            async with AsyncSession(bind=conn, expire_on_commit=False) as current:
                yield current

        app.dependency_overrides[get_async_session] = request_session
        statements = []
        traces = {}

        def capture(connection, cursor, statement, params, context, executemany):
            statements.append(' '.join(statement.split()))

        async def request(client, name, path, payload, logged_in=False, expected=5):
            statements.clear()
            response = await client.post(path, json=payload,
                                         headers={'Authorization': 'Bearer synthetic-test-token'} if logged_in else {})
            assert response.status_code == 200, response.text
            data = response.json()['data']
            assert len(data) == (2 if logged_in else 1)
            assert all(item['image_url'].startswith('/data/uploads/') for item in data)
            if logged_in:
                assert any(item['is_public'] is False for item in data)
            trace = list(statements)
            assert len(trace) == expected, '\n'.join(trace)
            assert not any('pg_locks' in sql or 'pg_relation_size' in sql for sql in trace)
            traces[name] = trace

        event.listen(conn.sync_connection, 'before_cursor_execute', capture)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                await request(client, 'gallery_anonymous', '/images/search', {})
                await request(client, 'gallery_authenticated', '/images/search', {}, True, 6)
                await request(client, 'smart_exact_anonymous', '/images/smart-search', {'text':'猫'})
                await request(client, 'smart_exact_authenticated', '/images/smart-search', {'text':'猫'}, True, 6)
                monkeypatch.setattr(cache_module.ConfigCache, '_cache', {})
                monkeypatch.setattr(cache_module.ConfigCache, '_cache_time', 0)
                monkeypatch.setattr(cache_module, 'async_session_maker', lambda: pytest.fail('配置不能嵌套借连接'))
                monkeypatch.setattr(search_guard, 'load_policy', SearchGuardService().load_policy)
                await request(client, 'smart_exact_cold_config', '/images/smart-search', {'text':'猫'}, expected=6)
                await session.execute(text(f'CREATE INDEX {INDEX_NAME} ON images USING hnsw (embedding vector_cosine_ops)'))
                await session.execute(text("INSERT INTO config (key,value) VALUES ('search_hnsw_enabled','true')"))
                await request(client, 'smart_hnsw_anonymous', '/images/smart-search', {'text':'猫'}, expected=8)
                await request(client, 'smart_hnsw_authenticated', '/images/smart-search', {'text':'猫'}, True, 9)
                await request(client, 'smart_filters_only', '/images/smart-search', {'tags':['猫']}, expected=3)
            statements.clear()
            await mcp._tool_search_images({'keyword':'猫','match':'fuzzy'}, session, None)
            traces['mcp_fuzzy'] = list(statements)
            assert len(statements) == 4, '\n'.join(statements)
            assert not any('JOIN users' in sql for sql in statements)
            statements.clear()
            await mcp._tool_search_images({}, session, None)
            traces['mcp_random'] = list(statements)
            assert len(statements) == 3, '\n'.join(statements)
            assert not any('images.embedding' in sql for sql in statements)
            gallery = traces['gallery_anonymous']
            assert not any('images.embedding' in sql for sql in gallery)
            assert sum('JOIN tags' in sql for sql in gallery) == 1
            assert not any('secret_access_key' in sql or 'access_key_id' in sql for sql in gallery)
            smart = traces['smart_exact_anonymous']
            assert not any('COUNT(*) OVER' in sql for sql in smart)
            assert not any(sql.startswith('SELECT images.id, images.file_hash') for sql in smart)
            for stage in ['gallery.count', 'gallery.rows', 'tags.batch', 'subjects.batch',
                          'urls.locations', 'urls.build', 'embedding', 'dictionary', 'options',
                          'retrieval', 'hybrid.sql', 'total']:
                assert f'stage={stage} ' in caplog.text
            print(json.dumps({'search_sql_counts': {name: len(trace) for name, trace in traces.items()},
                              'search_sql_chains': traces}, ensure_ascii=False))
        finally:
            event.remove(conn.sync_connection, 'before_cursor_execute', capture)


async def test_search_index_migration_preserves_vectors_and_is_repeatable(postgres_connection, monkeypatch):
    conn = postgres_connection
    await conn.run_sync(Base.metadata.create_all)
    await conn.execute(text('ALTER TABLE images ALTER COLUMN embedding TYPE vector(3) USING NULL::vector(3)'))
    await conn.execute(text("INSERT INTO images (description, embedding) VALUES ('保留内容', '[1,0,0]')"))
    await conn.execute(text('DROP INDEX ix_image_tags_tag_image'))
    for name in ('ix_images_embedding', 'idx_images_embedding'):
        await conn.execute(text(f'CREATE INDEX {name} ON images USING ivfflat (embedding vector_cosine_ops) WITH (lists=1)'))
    ddl = []

    def migrate(sync):
        # CONCURRENTLY 本身不能回滚；仅在此隔离测试中去掉该关键字以检查其余真实 DDL。
        # 原始语句另外断言在线形式，生产迁移仍使用独立自动提交块。
        def execute(statement):
            ddl.append(str(statement))
            return sync.execute(text(str(statement).replace(' CONCURRENTLY', '')))
        monkeypatch.setattr(search_migration, 'op', SimpleNamespace(
            get_bind=lambda: sync, get_context=lambda: SimpleNamespace(autocommit_block=nullcontext), execute=execute,
        ))
        search_migration.upgrade()

    await conn.run_sync(migrate)
    await conn.run_sync(migrate)
    names = set((await conn.execute(text("""
        SELECT c.relname FROM pg_index x JOIN pg_class c ON c.oid=x.indexrelid
        WHERE x.indrelid IN (to_regclass('images'), to_regclass('image_tags')) AND x.indisvalid
    """))).scalars())
    assert 'ix_image_tags_tag_image' in names
    assert not names.intersection({'ix_images_embedding', 'idx_images_embedding'})
    assert await conn.scalar(text("SELECT embedding::text FROM images WHERE description='保留内容'")) == '[1,0,0]'
    assert any('CREATE INDEX CONCURRENTLY' in item for item in ddl)
    assert all('public.' not in item for item in ddl)


async def test_hnsw_catalog_reuse_weighted_candidates_and_resize_are_schema_safe(postgres_connection, monkeypatch):
    """真实余弦、目录与候选 SQL；全部 DDL 在隔离 schema 的事务内回滚。"""
    conn = postgres_connection
    await conn.run_sync(Base.metadata.create_all)
    await conn.execute(text('ALTER TABLE images ALTER COLUMN embedding TYPE vector(3) USING NULL::vector(3)'))
    async with AsyncSession(bind=conn, expire_on_commit=False) as session:
        cat = Tag(name='分类', level=0)
        name = Tag(name='Doro', level=2)
        alias = Tag(name='多萝', level=2)
        emotion = Tag(name='无语', level=2)
        session.add_all([cat, name, alias, emotion]); await session.flush()
        subject = Subject(name='Doro', category_tag_id=cat.id, primary_tag_id=name.id, alias_tag_ids=[alias.id])
        images = [Image(description='正常', embedding=[1,0,0]),
                  Image(description='标签独立召回', embedding=None),
                  Image(description='零向量', embedding=[0,0,0]),
                  Image(description='私有', embedding=[1,0,0], is_public=False)]
        session.add_all([subject, *images]); await session.flush()
        session.add_all([ImageTag(image_id=image.id, tag_id=tag.id)
                         for image, tag in [(images[1],name),(images[1],emotion),(images[2],alias),(images[3],name)]])
        await session.flush()
        terms = await SearchService().query_terms(session, 'Doro 无语')
        assert terms == {'Doro': 2.0, '无语': 1.0}
        before = await vector_index_repository.inspect(session)
        assert before['ready'] is False
        assert not (await vector_index_repository.search_options(session))['index_ready']
        # 并发 DDL 的事务约束由模拟测试覆盖；真实索引在回滚事务内构建，不留下对象。
        await session.execute(text(f'CREATE INDEX {INDEX_NAME} ON images USING hnsw (embedding vector_cosine_ops)'))
        state = await vector_index_repository.inspect(session)
        assert state['ready'] and state['size_bytes'] > 0
        assert state['schema_name'].startswith('test_imgtag_')
        monkeypatch.setattr(image_repository, 'get_by_ids', AsyncMock(return_value=[]))
        params = dict(query_vector=[1.,0.,0.], query_text='Doro 无语', query_tag_weights=terms)
        exact = await image_repository.hybrid_search(session, **params)
        ann = await image_repository.hybrid_search(session, **params, candidate_limit=1)
        assert [row['id'] for row in exact] == [image.id for image in images[:3]]
        assert [row['id'] for row in ann] == [row['id'] for row in exact]
        assert ann[1]['vector_score'] == ann[2]['vector_score'] == 0
        assert ann[1]['tag_score'] == 1
        assert ann[2]['tag_score'] == pytest.approx(2/3)
        # 开关读取真实配置；重新创建 Service 也复用目录里的索引，不构建或修改向量。
        monkeypatch.setattr(embedding_service, 'get_embedding', AsyncMock(return_value=[1.,0.,0.]))
        await session.execute(text("INSERT INTO config (key,value) VALUES ('search_hnsw_enabled','true')"))
        assert (await vector_index_repository.search_options(session))['index_ready']
        accelerated = await SearchService().search(session, text='Doro 无语')
        assert accelerated.search_mode == 'hnsw'
        assert [row['id'] for row in accelerated] == [row['id'] for row in exact]
        await session.execute(text("UPDATE config SET value='false' WHERE key='search_hnsw_enabled'"))
        baseline = await SearchService().search(session, text='Doro 无语')
        assert baseline.search_mode == 'exact'
        assert [row['id'] for row in baseline] == [row['id'] for row in exact]
        # 锁和索引都定位到当前 schema；调整后只留下 NULL，不重新创建空索引。
        await image_repository.resize_embedding_dimensions(session, 4)
        assert await image_repository.get_embedding_dimensions(session) == 4
        assert not (await vector_index_repository.inspect(session))['exists']
        assert await session.scalar(select(func.count()).select_from(Image).where(Image.embedding.is_not(None))) == 0


async def test_creation_appends_tag_matches_preserves_multiple_subjects_and_does_not_create_references(postgres_connection):
    conn = postgres_connection
    await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(bind=conn, expire_on_commit=False) as session:
        category = Tag(name='表情包', level=0)
        name = Tag(name='菲比', level=2)
        other_name = Tag(name='糯糯', level=2)
        session.add_all([category, name, other_name]); await session.flush()
        other = Subject(name='糯糯', category_tag_id=category.id, primary_tag_id=other_name.id)
        images = [Image(description=description) for description in ['叠叠乐', '游泳', '其他角色']]
        session.add_all([other, *images]); await session.flush()
        session.add_all([ImageTag(image_id=image.id, tag_id=name.id) for image in images[:2]])
        session.add(ImageSubject(image_id=images[0].id, subject_id=other.id, is_current=True, is_primary=True, source='manual'))
        await session.flush()
        created = await api.create_subject(SubjectCreate(category_tag_id=category.id, primary_tag_id=name.id), {}, session)
        subject = await subject_repository.get_by_id(session, created.id)
        assert created.cover_image_id is None and created.cover_image_url == ''
        # 重复调用不增加关联、不改主主体、不把带标签的图全部登记为参考。
        await gallery.associate_on_create(session, subject, None)
        rows = (await session.execute(select(ImageSubject).order_by(ImageSubject.image_id, ImageSubject.subject_id))).scalars().all()
        assert len(rows) == 3
        assert {(row.subject_id, row.is_primary) for row in rows if row.image_id == images[0].id} == {(other.id, True), (subject.id, False)}
        assert [(row.image_id, row.is_primary) for row in rows if row.subject_id == subject.id] == [(images[0].id, False), (images[1].id, True)]
        assert all(row.synced_primary_tag_id is None for row in rows)
        assert (await session.execute(select(func.count()).select_from(SubjectSample))).scalar_one() == 0
        assert subject.cover_image_id is None
        page, total = await subject_repository.tagged_images(session, name.id, page=1, size=1)
        assert total == 2 and [image.id for image in page] == [images[1].id]
        filtered, count = await subject_repository.tagged_images(session, name.id, keyword='叠叠')
        assert count == 1 and filtered[0].id == images[0].id
        assert await subject_repository.eligible_reference_ids(session, name.id, [i.id for i in images]) == {i.id for i in images[:2]}
        assert created.image_count == 2
        assert await subject_repository.count_current_images(session, [subject.id, other.id]) == {subject.id: 2, other.id: 1}
        # 新添同名标签、仅保留历史关联，都不计入当前重分析范围。
        session.add(ImageTag(image_id=images[2].id, tag_id=name.id))
        session.add(ImageSubject(image_id=images[2].id, subject_id=subject.id, is_current=False, is_primary=False))
        await session.flush()
        assert await subject_repository.count_current_images(session, [subject.id]) == {subject.id: 2}
        assert await subject_repository.count_current_images(session, []) == {}
        alias = Tag(name='Phoebe', level=2)
        ordinary = Tag(name='金色头发', level=2)
        session.add_all([alias, ordinary]); await session.flush()
        subject.alias_tag_ids = [alias.id]
        session.add_all([ImageTag(image_id=images[0].id, tag_id=tag.id) for tag in [alias, ordinary, category]])
        await session.flush()
        marked = await image_repository.get_image_tags_with_source(session, images[0].id)
        flags = {tag['id']: tag['is_subject'] for tag in marked}
        assert flags == {name.id: True, alias.id: True, ordinary.id: False, category.id: False}
        batch = await image_repository.get_batch_image_tags_with_source(session, [images[0].id, images[1].id])
        assert {tag['id']: tag['is_subject'] for tag in batch[images[0].id]} == flags
        subject.is_active = False; await session.flush()
        assert not any(tag['is_subject'] for tag in await image_repository.get_image_tags_with_source(session, images[0].id))


async def test_cover_migration_preserves_subjects_and_nulls_cover_on_image_delete(postgres_connection):
    conn = postgres_connection
    for sql in ['CREATE TABLE images (id INTEGER PRIMARY KEY)', 'CREATE TABLE subjects (id INTEGER PRIMARY KEY)',
                'CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMPTZ)',
                'INSERT INTO images VALUES (1)', 'INSERT INTO subjects VALUES (7)',
                "INSERT INTO config VALUES ('subject_extraction_max_images', '12', now())"]:
        await conn.execute(text(sql))
    def upgrade(sync_conn):
        with Operations.context(MigrationContext.configure(sync_conn)):
            workflow_migration.add_subject_cover()
    await conn.run_sync(upgrade)
    assert (await conn.execute(text('SELECT cover_image_id FROM subjects WHERE id=7'))).scalar_one() is None
    assert (await conn.execute(text('SELECT value FROM config'))).scalar_one() == '3'
    await conn.execute(text('UPDATE subjects SET cover_image_id=1 WHERE id=7'))
    await conn.execute(text('DELETE FROM images WHERE id=1'))
    assert (await conn.execute(text('SELECT cover_image_id FROM subjects WHERE id=7'))).scalar_one() is None


@pytest.mark.parametrize('existing', ['absent', 'column_only', 'complete'])
async def test_upgrade_repairs_legacy_and_preserves_existing_ownership(existing, postgres_connection):
    conn = postgres_connection
    await conn.execute(text("CREATE TABLE tags (id INTEGER PRIMARY KEY)"))
    await conn.execute(text("CREATE TABLE image_subjects (id INTEGER PRIMARY KEY)"))
    await conn.execute(text("INSERT INTO tags VALUES (10)"))
    await conn.execute(text("INSERT INTO image_subjects VALUES (1)"))
    if existing != "absent":
        await conn.execute(text("ALTER TABLE image_subjects ADD COLUMN synced_primary_tag_id INTEGER"))
        await conn.execute(text("UPDATE image_subjects SET synced_primary_tag_id=10"))
    if existing == "complete":
        # 使用不同名称，确认按真实外键识别，避免重复创建。
        await conn.execute(text("ALTER TABLE image_subjects ADD CONSTRAINT existing_tag_fk FOREIGN KEY (synced_primary_tag_id) REFERENCES tags(id) ON DELETE SET NULL"))

    def upgrade(sync_conn):
        with Operations.context(MigrationContext.configure(sync_conn)):
            workflow_migration.repair_subject_tag_ownership()

    await conn.run_sync(upgrade)
    await conn.run_sync(upgrade)
    value = (await conn.execute(text("SELECT synced_primary_tag_id FROM image_subjects WHERE id=1"))).scalar_one()
    assert value == (None if existing == "absent" else 10)
    fk_count = (await conn.execute(text("SELECT count(*) FROM pg_constraint WHERE conrelid='image_subjects'::regclass AND contype='f'"))).scalar_one()
    assert fk_count == 1
    await conn.execute(text("UPDATE image_subjects SET synced_primary_tag_id=10"))
    await conn.execute(text("DELETE FROM tags WHERE id=10"))
    assert (await conn.execute(text("SELECT synced_primary_tag_id FROM image_subjects WHERE id=1"))).scalar_one() is None
    await conn.execute(text("SELECT synced_primary_tag_id FROM image_subjects"))


@pytest.mark.parametrize('legacy_ownership', [False, True])
async def test_0006_upgrades_directly_to_final_0007_and_can_downgrade(postgres_connection, legacy_ownership):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect
    conn = postgres_connection
    script = ScriptDirectory.from_config(Config('alembic.ini'))
    assert script.get_heads() == ['0008_search_indexes']
    assert script.get_revision('0007_subject_workflow').down_revision == '0006_mcp_hardening'

    def migrate(sync_conn, target, downgrade=False):
        schema = sync_conn.scalar(text('SELECT current_schema()'))
        steps = script._downgrade_revs if downgrade else script._upgrade_revs
        context = MigrationContext.configure(sync_conn, opts={
            'version_table_schema': schema, 'fn': lambda revision, _: steps(target, revision),
        })
        with Operations.context(context):
            context.run_migrations()

    await conn.run_sync(lambda sync: migrate(sync, '0006_mcp_hardening'))
    category = await conn.scalar(text("SELECT id FROM tags WHERE level=0 AND code='meme'"))
    name = await conn.scalar(text("INSERT INTO tags (name,level) VALUES ('迁移测试主体',2) RETURNING id"))
    subject_id = await conn.scalar(text("INSERT INTO subjects (name,category_tag_id,primary_tag_id,description) VALUES ('迁移测试主体',:category,:name,'保留原描述') RETURNING id"), {'category':category,'name':name})
    image_id = await conn.scalar(text("INSERT INTO images (description) VALUES ('保留图片描述') RETURNING id"))
    await conn.execute(text("INSERT INTO image_subjects (image_id,subject_id,is_primary) VALUES (:image,:subject,true)"), {'image':image_id,'subject':subject_id})
    await conn.execute(text("UPDATE tags SET prompt='用户分类提示词' WHERE id=:category"), {'category':category})
    await conn.execute(text("INSERT INTO config (key,value) VALUES ('vision_prompt','用户全局提示词'),('subject_extraction_max_images','12')"))
    if legacy_ownership:
        await conn.execute(text('ALTER TABLE image_subjects DROP COLUMN synced_primary_tag_id CASCADE'))
    await conn.run_sync(lambda sync: migrate(sync, '0007_subject_workflow'))
    assert await conn.scalar(text('SELECT version_num FROM alembic_version')) == '0007_subject_workflow'
    subject = (await conn.execute(text('SELECT description,definition_revision,recognition_notes,cover_image_id FROM subjects WHERE id=:id'), {'id':subject_id})).one()
    assert tuple(subject) == ('保留原描述',1,'',None)
    assert await conn.scalar(text('SELECT is_current FROM image_subjects WHERE subject_id=:id'), {'id':subject_id}) is True
    assert await conn.scalar(text('SELECT count(*) FROM subject_definition_versions')) == 0
    assert await conn.scalar(text('SELECT count(*) FROM image_analysis_versions')) == 0
    assert await conn.scalar(text('SELECT count(*) FROM subject_prompt_templates')) == 5
    assert await conn.scalar(text("SELECT value FROM config WHERE key='subject_extraction_max_images'")) == '3'
    assert await conn.scalar(text("SELECT value FROM config WHERE key='vision_prompt'")) == '用户全局提示词'
    assert await conn.scalar(text('SELECT prompt FROM tags WHERE id=:id'), {'id':category}) == '用户分类提示词'

    def structure(sync):
        inspector = inspect(sync)
        defaults = {name:{c['name']:c['default'] for c in inspector.get_columns(name)} for name in ['image_analysis_versions','subject_definition_versions']}
        assert 'history' in defaults['image_analysis_versions']['state']
        assert defaults['image_analysis_versions']['pending'] == 'false'
        assert 'history' in defaults['subject_definition_versions']['state']
        assert any(fk['constrained_columns'] == ['cover_image_id'] and fk['options'].get('ondelete') == 'SET NULL' for fk in inspector.get_foreign_keys('subjects'))
        assert any(fk['constrained_columns'] == ['synced_primary_tag_id'] and fk['options'].get('ondelete') == 'SET NULL' for fk in inspector.get_foreign_keys('image_subjects'))
    await conn.run_sync(structure)
    await conn.execute(text('UPDATE subjects SET cover_image_id=:image WHERE id=:subject'), {'image':image_id,'subject':subject_id})
    await conn.execute(text('DELETE FROM images WHERE id=:id'), {'id':image_id})
    assert await conn.scalar(text('SELECT cover_image_id FROM subjects WHERE id=:id'), {'id':subject_id}) is None
    await conn.run_sync(lambda sync: migrate(sync, '0006_mcp_hardening', downgrade=True))
    assert await conn.scalar(text('SELECT version_num FROM alembic_version')) == '0006_mcp_hardening'
    assert await conn.scalar(text('SELECT description FROM subjects WHERE id=:id'), {'id':subject_id}) == '保留原描述'
    await conn.run_sync(lambda sync: migrate(sync, '0007_subject_workflow'))
    await conn.run_sync(structure)
