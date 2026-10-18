"""真实 PostgreSQL 的主体关联、标签标记与迁移；使用隔离 schema 并全量回滚。"""

import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints import subjects as api
from imgtag.db.repositories import image_repository, subject_repository
from imgtag.models import Base, Image, ImageSubject, ImageTag, Subject, SubjectSample, Tag
from imgtag.schemas.subject import SubjectCreate
from imgtag.services.subject_gallery_service import subject_gallery_service as gallery

pytestmark = pytest.mark.postgres
workflow_migration = importlib.import_module("imgtag.alembic.versions.0007_subject_workflow")


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
    assert script.get_heads() == ['0007_subject_workflow']
    assert script.get_revision('head').down_revision == '0006_mcp_hardening'

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
    await conn.run_sync(lambda sync: migrate(sync, 'head'))
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
    await conn.run_sync(lambda sync: migrate(sync, 'head'))
    await conn.run_sync(structure)
