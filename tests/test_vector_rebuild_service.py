import asyncio

import pytest
from sqlalchemy.exc import SQLAlchemyError

from imgtag.services import vector_rebuild_service as rebuild_module
from imgtag.services.vector_rebuild_service import VectorRebuildService


class Session:
    def __init__(self):
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def rebuild(monkeypatch):
    service = VectorRebuildService()
    monkeypatch.setattr(rebuild_module, "async_session_maker", Session)
    return service


@pytest.mark.asyncio
async def test_progress_counts_success_failure_skip_and_deleted_images(rebuild, monkeypatch):
    progress = []

    async def inputs(session):
        return [(1, "success", []), (2, "failure", []), (3, " ", []), (4, "deleted", [])]

    async def embed(text, tags):
        progress.append(rebuild.status["processed"])
        if text == "failure":
            raise ValueError("HTTP 400")
        return [0.1]

    async def update(session, image_id, embedding):
        return image_id != 4

    monkeypatch.setattr(rebuild_module.image_repository, "list_embedding_inputs", inputs)
    monkeypatch.setattr(rebuild_module.embedding_service, "get_embedding_combined", embed)
    monkeypatch.setattr(rebuild_module.image_repository, "set_embedding", update)
    status_reference = rebuild.status
    rebuild._reset(running=True)
    await rebuild.run()

    assert rebuild.status is status_reference
    assert progress == [0, 1, 3]
    assert rebuild.status["processed"] == rebuild.status["total"] == 4
    assert rebuild.status["succeeded"] == 1
    assert rebuild.status["failed"] == 1
    assert rebuild.status["skipped"] == 2
    assert rebuild.status["last_error"] == "HTTP 400"
    assert rebuild.status["is_running"] is False


@pytest.mark.asyncio
async def test_all_failures_still_reach_full_progress(rebuild, monkeypatch):
    async def inputs(session):
        return [(1, "a", []), (2, "b", []), (3, "c", [])]

    async def fail(text, tags):
        raise ValueError("HTTP 400")

    monkeypatch.setattr(rebuild_module.image_repository, "list_embedding_inputs", inputs)
    monkeypatch.setattr(rebuild_module.embedding_service, "get_embedding_combined", fail)
    rebuild._reset(running=True)
    await rebuild.run()

    assert rebuild.status["processed"] == rebuild.status["total"] == 3
    assert rebuild.status["failed"] == 3
    assert rebuild.status["succeeded"] == 0
    assert rebuild.status["is_running"] is False


@pytest.mark.asyncio
async def test_prepare_reserves_running_state_before_await(rebuild, monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def dimensions():
        entered.set()
        await release.wait()
        return 1024

    async def db_dimensions(session):
        return 1024

    monkeypatch.setattr(rebuild_module.embedding_service, "get_dimensions", dimensions)
    monkeypatch.setattr(rebuild_module.image_repository, "get_embedding_dimensions", db_dimensions)
    task = asyncio.create_task(rebuild.prepare(Session()))
    try:
        await entered.wait()
        assert rebuild.status["is_running"] is True
        with pytest.raises(ValueError, match="正在进行中"):
            await rebuild.prepare(Session())
    finally:
        release.set()
        assert await task == 1024


@pytest.mark.asyncio
async def test_preparation_failure_releases_state_and_rolls_back(rebuild, monkeypatch):
    async def dimensions():
        return 1024

    async def db_dimensions(session):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(rebuild_module.embedding_service, "get_dimensions", dimensions)
    monkeypatch.setattr(rebuild_module.image_repository, "get_embedding_dimensions", db_dimensions)
    session = Session()
    with pytest.raises(SQLAlchemyError):
        await rebuild.prepare(session)
    assert rebuild.status["is_running"] is False
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_listing_failure_is_visible_and_releases_state(rebuild, monkeypatch):
    async def inputs(session):
        raise SQLAlchemyError("list failed")

    monkeypatch.setattr(rebuild_module.image_repository, "list_embedding_inputs", inputs)
    rebuild._reset(running=True)
    await rebuild.run()
    assert rebuild.status["is_running"] is False
    assert "重建失败" in rebuild.status["message"]
    assert rebuild.status["last_error"] == "list failed"
