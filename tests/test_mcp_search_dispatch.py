"""MCP 合并版 search_images 分发逻辑与作用域边界测试。

不依赖数据库：仓库层与 embedding 服务均以 monkeypatch 替换，
仅验证 mcp.py 内的分发矩阵、可见性参数传递与 scope/权限边界。
"""

import asyncio
import json
import logging
import math
import re
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import TextualSelect

import pytest

from imgtag.api.endpoints import images, mcp, search as legacy_search
from imgtag.api.endpoints.auth import get_current_user_optional
from imgtag.api import dependencies as auth_dependencies, search_guards
from imgtag.db import get_async_session
from imgtag.core.search_limits import SEARCH_DEFAULTS, SearchPolicy
from imgtag.services import search_guard_service as guard_module
from imgtag.services.search_guard_service import SearchGuardService, SearchRejected, search_guard
from imgtag.services.search_service import SearchOptions, SearchService
from imgtag.core import config_cache as cache_module
from imgtag.core import search_logging
from imgtag.db.repositories.vector_index import vector_index_repository
from imgtag.schemas.image import ImageSearchRequest
from sqlalchemy.exc import SQLAlchemyError

ANON = None
USER = {"id": 7, "username": "u1", "role": "user", "is_active": True, "permissions": 0}
ADMIN = {"id": 1, "username": "root", "role": "admin", "is_active": True, "permissions": 0}


async def test_debug_search_traces_are_isolated_and_do_not_log_payloads(monkeypatch, caplog):
    service = SearchService()
    monkeypatch.setattr(service, 'query_terms', AsyncMock(return_value={'保密标签':1.}))
    monkeypatch.setattr(service, 'load_options', AsyncMock(return_value=SearchOptions()))
    monkeypatch.setattr(images.image_repository, 'hybrid_search', AsyncMock(return_value=[]))

    async def embedding(*args, **kwargs):
        await asyncio.sleep(0)
        return [123.123456789, 456.987654321]

    monkeypatch.setattr(images.embedding_service, 'get_embedding', embedding)
    with caplog.at_level(logging.DEBUG, logger='imgtag.search'):
        await asyncio.gather(service.search(None, text='保密搜索一'), service.search(None, text='保密搜索二'))
        with search_logging.search_stage('outside_search'):
            pass
    messages = [record.getMessage() for record in caplog.records if record.name == 'imgtag.search']
    traces = {re.search(r'trace=([0-9a-f]{12})', message)[1] for message in messages}
    assert len(traces) == 2
    for trace in traces:
        stages = [re.search(r'stage=(\S+)', message)[1] for message in messages
                  if f'trace={trace}' in message and 'stage=' in message]
        assert sorted(stages) == sorted(['embedding', 'dictionary', 'options', 'retrieval', 'total'])
    assert 'outside_search' not in caplog.text
    assert all(payload not in caplog.text for payload in ['保密搜索', '保密标签', '123.123456789', '456.987654321'])


async def test_info_search_does_not_create_traces_or_read_clock(monkeypatch, caplog):
    service = SearchService()
    monkeypatch.setattr(service, 'query_terms', AsyncMock(return_value={}))
    monkeypatch.setattr(service, 'load_options', AsyncMock(return_value=SearchOptions()))
    monkeypatch.setattr(images.embedding_service, 'get_embedding', AsyncMock(return_value=[1., 0.]))
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(images.image_repository, 'hybrid_search', query)
    monkeypatch.setattr(search_logging, 'perf_counter', lambda: pytest.fail('INFO 不应读取阶段时钟'))
    monkeypatch.setattr(search_logging, 'uuid4', lambda: pytest.fail('INFO 不应创建编号'))
    with caplog.at_level(logging.INFO, logger='imgtag.search'):
        assert await service.search(None, text='猫') == []
    query.assert_awaited_once()
    assert not any(record.name == 'imgtag.search' for record in caplog.records)


async def test_debug_search_records_hnsw_failure_and_exact_fallback_without_error_payload(monkeypatch, caplog):
    service = SearchService()
    monkeypatch.setattr(service, 'query_terms', AsyncMock(return_value={}))
    monkeypatch.setattr(service, 'load_options', AsyncMock(return_value=SearchOptions(True, 40, True)))
    monkeypatch.setattr(images.embedding_service, 'get_embedding', AsyncMock(return_value=[1.,0.]))
    monkeypatch.setattr(images.image_repository, 'configure_hnsw', AsyncMock())
    monkeypatch.setattr(images.image_repository, 'hybrid_search',
                        AsyncMock(side_effect=[SQLAlchemyError('保密 SQL 和向量'), []]))

    class Savepoint:
        async def __aenter__(self):
            pass
        async def __aexit__(self, *args):
            pass

    with caplog.at_level(logging.DEBUG, logger='imgtag.search'):
        assert await service.search(SimpleNamespace(begin_nested=Savepoint), text='猫') == []
    retrieval = [record.getMessage() for record in caplog.records if 'stage=retrieval ' in record.getMessage()]
    assert len(retrieval) == 2
    assert 'status=error' in retrieval[0] and 'mode=hnsw' in retrieval[0]
    assert 'status=ok' in retrieval[1] and 'mode=exact' in retrieval[1] and 'fallback_reason=SQLAlchemyError' in retrieval[1]
    assert '保密 SQL 和向量' not in caplog.text


@pytest.mark.parametrize('error_type', [ValueError, asyncio.CancelledError])
async def test_failed_or_cancelled_search_resets_debug_context(monkeypatch, caplog, error_type):
    monkeypatch.setattr(images.embedding_service, 'get_embedding', AsyncMock(side_effect=error_type('保密错误详情')))
    with caplog.at_level(logging.DEBUG, logger='imgtag.search'):
        with pytest.raises(error_type):
            await SearchService().search(None, text='保密输入')
        with search_logging.search_stage('outside_search'):
            pass
    assert 'stage=embedding status=error' in caplog.text
    assert 'stage=total status=error' in caplog.text
    assert 'outside_search' not in caplog.text and '保密错误详情' not in caplog.text


async def test_debug_repository_stages_do_not_add_queries_or_log_parameters(caplog):
    count = AsyncMock(return_value=SimpleNamespace(scalar=lambda: 0))
    hybrid = AsyncMock(return_value=SimpleNamespace(fetchall=lambda: []))
    with caplog.at_level(logging.DEBUG, logger='imgtag.search'):
        await images.image_repository.search_images(SimpleNamespace(execute=count), keyword='保密关键词')
        await images.image_repository.hybrid_search(
            SimpleNamespace(execute=hybrid), query_text='保密关键词', query_vector=[123.123456789,1.],
            query_tag_weights={}, candidate_limit=100, limit=50,
        )
    count.assert_awaited_once()
    hybrid.assert_awaited_once()
    assert 'stage=gallery.count' in caplog.text and 'skip_results=True' in caplog.text
    assert 'stage=gallery.rows' not in caplog.text
    assert 'stage=hybrid.sql' in caplog.text and 'candidate_limit=100' in caplog.text
    assert '保密关键词' not in caplog.text and '123.123456789' not in caplog.text


async def test_query_terms_prefers_longest_names_and_subjects_without_latin_substrings(monkeypatch):
    monkeypatch.setattr(mcp.image_repository, 'match_search_tags', AsyncMock(return_value=[
        ('可爱猫咪', False), ('Doro', True), ('doro', True), ('猫咪', False), ('可爱', False), ('无语', False), ('ann', True),
    ]))
    terms = await SearchService().query_terms(None, 'Doro可爱猫咪无语 banner')
    assert terms == {'可爱猫咪': 1.0, 'Doro': 2.0, '无语': 1.0}


@pytest.mark.parametrize('ready,fail', [(False, False), (True, False), (True, True)])
async def test_hnsw_uses_ready_index_and_rolls_back_before_exact_fallback(monkeypatch, ready, fail):
    events = []
    service = SearchService()
    monkeypatch.setattr(service, 'load_options', AsyncMock(return_value=SearchOptions(True, 100, ready)))
    monkeypatch.setattr(service, 'query_terms', AsyncMock(return_value={'猫': 1.0}))
    monkeypatch.setattr(mcp.embedding_service, 'get_embedding', AsyncMock(return_value=[1.0, 0.0]))
    monkeypatch.setattr(mcp.image_repository, 'configure_hnsw', AsyncMock())

    class Savepoint:
        async def __aenter__(self):
            events.append('begin')
        async def __aexit__(self, exc_type, *args):
            events.append('rollback' if exc_type else 'release')

    async def query(session, **kwargs):
        events.append('ann' if kwargs.get('candidate_limit') else 'exact')
        assert kwargs['tags'] == ['猫'] and kwargs['visible_to_user_id'] == 7
        if fail and kwargs.get('candidate_limit'):
            raise SQLAlchemyError('index unavailable')
        return []

    monkeypatch.setattr(mcp.image_repository, 'hybrid_search', query)
    await service.search(SimpleNamespace(begin_nested=Savepoint), text='猫', tags=['猫'], visible_to_user_id=7)
    assert events == (['exact'] if not ready else
                      ['begin', 'ann', 'rollback', 'exact'] if fail else ['begin', 'ann', 'release'])


@pytest.mark.parametrize('limit,candidate_limit', [(10, 20), (20, 40), (50, 100)])
async def test_hnsw_candidates_follow_single_page_size(monkeypatch, limit, candidate_limit):
    service = SearchService()
    monkeypatch.setattr(service, 'load_options', AsyncMock(return_value=SearchOptions(enabled=True, index_ready=True)))
    monkeypatch.setattr(service, 'query_terms', AsyncMock(return_value={}))
    monkeypatch.setattr(mcp.embedding_service, 'get_embedding', AsyncMock(return_value=[1.0, 0.0]))
    inspect = AsyncMock(side_effect=AssertionError('搜索不应读取完整维护状态'))
    monkeypatch.setattr(vector_index_repository, 'inspect', inspect)
    configure = AsyncMock()
    monkeypatch.setattr(mcp.image_repository, 'configure_hnsw', configure)
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(mcp.image_repository, 'hybrid_search', query)

    class Savepoint:
        async def __aenter__(self):
            pass
        async def __aexit__(self, *args):
            pass

    await service.search(SimpleNamespace(begin_nested=Savepoint), text='风景', limit=limit)
    args = query.await_args.kwargs
    assert args.get('candidate_limit') == candidate_limit
    assert args['limit'] == limit and 'offset' not in args
    inspect.assert_not_awaited()
    assert configure.await_args.args[1] == max(40, limit)


async def test_filter_only_search_skips_embedding_and_preserves_hard_filters(monkeypatch):
    embed = AsyncMock(side_effect=AssertionError('纯筛选不应请求模型'))
    monkeypatch.setattr(mcp.embedding_service, 'get_embedding', embed)
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(mcp.image_repository, 'hybrid_search', query)
    await SearchService().search(None, text=' ', tags=['猫'], category_id=4)
    args = query.await_args.kwargs
    assert args['query_vector'] is None and args['tags'] == ['猫']
    assert args['category_id'] == 4 and 'offset' not in args
    embed.assert_not_awaited()


@pytest.mark.parametrize('release', [False, True])
async def test_model_wait_releases_only_explicit_readonly_sessions(monkeypatch, release):
    session = SimpleNamespace(close=AsyncMock())
    service = SearchService()
    monkeypatch.setattr(service, 'query_terms', AsyncMock(return_value={}))
    monkeypatch.setattr(service, 'load_options', AsyncMock(return_value=SearchOptions()))
    monkeypatch.setattr(images.image_repository, 'hybrid_search', AsyncMock(return_value=[]))

    async def embedding(text, **kwargs):
        assert session.close.await_count == int(release)
        assert kwargs['session'] is (None if release else session)
        return [1., 0.]

    monkeypatch.setattr(images.embedding_service, 'get_embedding', embedding)
    await service.search(session, text='猫', release_connection=release)


@pytest.mark.parametrize('total,offset', [(0, 0), (12, 12), (12, 40)])
async def test_empty_or_out_of_range_gallery_skips_result_queries(total, offset):
    execute = AsyncMock(return_value=SimpleNamespace(scalar=lambda: total))
    result = await images.image_repository.search_images(SimpleNamespace(execute=execute), offset=offset)
    assert result == {'images': [], 'total': total, 'limit': 20, 'offset': offset}
    execute.assert_awaited_once()


@pytest.mark.parametrize('field', ['embedding', 'subject_analysis', 'tags', '__dict__'])
async def test_gallery_rejects_non_business_sort_fields_before_query(field):
    with pytest.raises(ValidationError):
        ImageSearchRequest(sort_by=field)
    execute = AsyncMock()
    with pytest.raises(ValueError, match='排序字段'):
        await images.image_repository.search_images(SimpleNamespace(execute=execute), sort_by=field)
    execute.assert_not_awaited()


async def test_search_options_use_one_fresh_query_and_never_full_inspection():
    states = [dict(enabled=True, ef_search=40, index_ready=True),
              dict(enabled=False, ef_search=80, index_ready=False)]
    statements = []

    async def execute(statement, params):
        statements.append(str(statement))
        return SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: states.pop(0)))

    session = SimpleNamespace(execute=execute)
    service = SearchService()
    assert await service.load_options(session) == SearchOptions(True, 40, True)
    assert await service.load_options(session) == SearchOptions(False, 80, False)
    assert len(statements) == 2
    assert all('pg_relation_size' not in sql and 'pg_locks' not in sql and '__hnsw_index_state' not in sql
               for sql in statements)


async def test_config_cache_refreshes_whole_snapshot_and_reuses_request_connection(monkeypatch):
    cache = cache_module.ConfigCache
    clock = [100.0]
    saved = {'option_a': 'new-a', 'option_b': 'new-b'}
    reads = []

    async def execute(statement):
        reads.append(str(statement))
        return SimpleNamespace(fetchall=lambda: list(saved.items()))

    session = SimpleNamespace(execute=execute)
    monkeypatch.setattr(cache, '_cache', {'option_a': 'old-a', 'option_b': 'old-b', 'removed': 'old'})
    monkeypatch.setattr(cache, '_cache_time', 0)
    monkeypatch.setattr(cache_module, 'time', SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr(cache_module, 'async_session_maker', lambda: pytest.fail('不能嵌套借连接'))
    assert await cache.get('option_b', session=session) == 'new-b'
    assert await cache.get('option_a', session=session) == 'new-a'
    assert await cache.get('removed', 'fallback', session=session) == 'fallback'
    assert len(reads) == 1
    saved['option_a'] = 'changed-a'
    clock[0] += 31
    assert await cache.get('option_b', session=session) == 'new-b'
    assert await cache.get('option_a', session=session) == 'changed-a'
    assert len(reads) == 2


@pytest.mark.parametrize('route', ['/images/smart-search', '/search/similar'])
@pytest.mark.parametrize('payload', [{'text': '猫', 'page': 2}, {'text': '猫', 'size': 51}])
async def test_smart_search_rejects_extra_pages_and_oversized_results(monkeypatch, route, payload):
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.include_router(legacy_search.router, prefix='/search')
    app.dependency_overrides[get_async_session] = lambda: SimpleNamespace(close=AsyncMock(), rollback=AsyncMock())
    app.dependency_overrides[get_current_user_optional] = lambda: None
    embed = AsyncMock()
    monkeypatch.setattr(mcp.embedding_service, 'get_embedding', embed)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post(route, json=payload)
    assert response.status_code == 422
    embed.assert_not_awaited()


async def test_smart_search_default_is_one_page_of_fifty_with_no_next_page(monkeypatch):
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.dependency_overrides[get_async_session] = lambda: SimpleNamespace(close=AsyncMock(), rollback=AsyncMock())
    app.dependency_overrides[get_current_user_optional] = lambda: None
    monkeypatch.setattr(mcp.embedding_service, 'get_embedding', AsyncMock(return_value=[1., 0.]))
    query = AsyncMock(return_value=[{'id': i, 'image_url': '', 'description': '', 'tags': [], 'similarity': .7}
                                   for i in range(1, 51)])
    monkeypatch.setattr(mcp.image_repository, 'hybrid_search', query)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        data = (await client.post('/images/smart-search', json={'text': '猫'})).json()
    assert len(data['data']) == data['total'] == data['size'] == 50
    assert data['page'] == data['pages'] == 1 and not data['has_next'] and not data['has_prev']
    assert query.await_args.kwargs['limit'] == 50


@pytest.mark.parametrize('match', ['auto', 'semantic'])
async def test_mcp_semantic_search_rejects_extra_pages_without_fuzzy_fallback(monkeypatch, match):
    embed, fuzzy = AsyncMock(), AsyncMock()
    monkeypatch.setattr(mcp.embedding_service, 'get_embedding', embed)
    monkeypatch.setattr(mcp.image_repository, 'search_images', fuzzy)
    with pytest.raises(ValueError, match='只支持第一页'):
        await mcp._tool_search_images({'keyword': '猫', 'match': match, 'page': 2}, None, USER)
    embed.assert_not_awaited()
    fuzzy.assert_not_awaited()


async def test_mcp_explicit_fuzzy_search_keeps_pagination(monkeypatch):
    query = AsyncMock(return_value={'images': [], 'total': 30})
    monkeypatch.setattr(mcp.image_repository, 'search_images', query)
    monkeypatch.setattr(mcp.storage_service, 'get_read_urls_with_session', AsyncMock(return_value={}))
    result = await mcp._tool_search_images({'keyword': '猫', 'match': 'fuzzy', 'page': 2}, None, USER)
    assert result['page'] == 2 and result['total'] == 30
    assert query.await_args.kwargs['offset'] == 10


@pytest.mark.parametrize('vector', [[0.0, 0.0], [float('nan'), 1], [float('inf'), 1], []])
async def test_invalid_query_vector_is_rejected_before_database_access(monkeypatch, vector):
    monkeypatch.setattr(mcp.embedding_service, 'get_embedding', AsyncMock(return_value=vector))
    query = AsyncMock()
    monkeypatch.setattr(mcp.image_repository, 'hybrid_search', query)
    with pytest.raises(ValueError, match='查询向量无效'):
        await SearchService().search(None, text='猫')
    query.assert_not_awaited()


def _orm_image(image_id: int = 1, is_public: bool = True, uploaded_by: int | None = None):
    return SimpleNamespace(
        id=image_id,
        description="desc",
        is_public=is_public,
        uploaded_by=uploaded_by,
        width=100,
        height=200,
        created_at=None,
        tags=[SimpleNamespace(name="普通标签", level=2), SimpleNamespace(name="主分类", level=0)],
    )


# ============================================================
# search_images 分发矩阵
# ============================================================

@pytest.mark.asyncio
async def test_no_keyword_defaults_to_random(monkeypatch) -> None:
    """无 keyword 无 sort → 随机路径，匿名可见性为仅 public。"""
    calls: list[dict] = []

    async def fake_random(session, tag_names, count, **kwargs):
        calls.append({"tags": tag_names, "count": count, **kwargs})
        return [{"id": 1, "image_url": "http://u/1", "description": "d", "tags": ["t"]}]

    monkeypatch.setattr(mcp.image_repository, "get_random_by_tags", fake_random)

    result = await mcp._tool_search_images({}, session=None, api_user=ANON)

    assert result["sort"] == "random"
    assert result["match"] is None
    assert "total" not in result
    assert calls[0]["tags"] == []
    assert calls[0]["count"] == 10
    assert calls[0]["visible_to_user_id"] is None
    assert calls[0]["skip_visibility_filter"] is False


@pytest.mark.asyncio
async def test_tags_only_random_with_admin_visibility(monkeypatch) -> None:
    """仅 tags → 随机路径且透传标签；admin 跳过可见性过滤。"""
    calls: list[dict] = []

    async def fake_random(session, tag_names, count, **kwargs):
        calls.append({"tags": tag_names, **kwargs})
        return []

    monkeypatch.setattr(mcp.image_repository, "get_random_by_tags", fake_random)

    await mcp._tool_search_images(
        {"tags": ["猫", " 白底 "], "count": 3}, session=None, api_user=ADMIN
    )

    assert calls[0]["tags"] == ["猫", "白底"]
    assert calls[0]["skip_visibility_filter"] is True


@pytest.mark.asyncio
async def test_sort_latest_without_keyword_browses_with_pagination(monkeypatch) -> None:
    """sort=latest 无 keyword → 确定性浏览路径，返回 total/page。"""
    calls: list[dict] = []

    async def fake_search(session, **kwargs):
        calls.append(kwargs)
        return {"images": [_orm_image()], "total": 42}

    async def fake_urls(session, images):
        return {img.id: f"http://u/{img.id}" for img in images}

    monkeypatch.setattr(mcp.image_repository, "search_images", fake_search)
    monkeypatch.setattr(mcp.storage_service, "get_read_urls_with_session", fake_urls)

    result = await mcp._tool_search_images(
        {"sort": "latest", "count": 20, "page": 2}, session=None, api_user=USER
    )

    assert result["sort"] == "latest"
    assert result["match"] is None
    assert result["total"] == 42
    assert result["page"] == 2
    assert calls[0]["offset"] == 20
    assert calls[0]["limit"] == 20
    assert calls[0]["visible_to_user_id"] == 7
    # 仅 level=2 标签进入响应
    assert result["images"][0]["tags"] == ["普通标签"]


@pytest.mark.asyncio
async def test_keyword_semantic_path(monkeypatch) -> None:
    """keyword + 默认 auto → 语义路径，tags 作为硬过滤透传，返回 score。"""
    hybrid_calls: list[dict] = []

    async def fake_embedding(text, **kwargs):
        return [0.1] * 512

    async def fake_hybrid(session, **kwargs):
        hybrid_calls.append(kwargs)
        return [{
            "id": 9,
            "image_url": "http://u/9",
            "description": "d",
            "tags": [{"name": "夕阳", "level": 2}, {"name": "壁纸", "level": 0}],
            "similarity": 0.8765432,
        }]

    monkeypatch.setattr(mcp.embedding_service, "get_embedding", fake_embedding)
    monkeypatch.setattr(mcp.image_repository, "hybrid_search", fake_hybrid)

    result = await mcp._tool_search_images(
        {"keyword": "雪山日出", "tags": ["夕阳"], "count": 5}, session=None, api_user=ANON
    )

    assert result["match"] == "semantic"
    assert result["sort"] == "relevance"
    assert "total" not in result
    assert result["images"][0]["score"] == 0.8765
    assert result["images"][0]["tags"] == ["夕阳"]
    assert hybrid_calls[0]["tags"] == ["夕阳"]
    assert hybrid_calls[0]["limit"] == 5
    assert hybrid_calls[0]["visible_to_user_id"] is None


@pytest.mark.asyncio
async def test_auto_falls_back_to_fuzzy_when_embedding_fails(monkeypatch) -> None:
    """auto 模式下 embedding 失败 → 自动降级模糊匹配。"""

    async def fake_embedding(text, **kwargs):
        raise RuntimeError("embedding service down")

    async def fake_search(session, **kwargs):
        return {"images": [_orm_image()], "total": 1}

    async def fake_urls(session, images):
        return {}

    monkeypatch.setattr(mcp.embedding_service, "get_embedding", fake_embedding)
    monkeypatch.setattr(mcp.image_repository, "search_images", fake_search)
    monkeypatch.setattr(mcp.storage_service, "get_read_urls_with_session", fake_urls)

    result = await mcp._tool_search_images(
        {"keyword": "夕阳"}, session=None, api_user=ANON
    )

    assert result["match"] == "fuzzy"
    assert result["sort"] == "latest"
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_explicit_semantic_does_not_fall_back(monkeypatch) -> None:
    """显式 match=semantic 时 embedding 失败直接报错，不降级。"""

    async def fake_embedding(text, **kwargs):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(mcp.embedding_service, "get_embedding", fake_embedding)

    with pytest.raises(ValueError, match="语义搜索暂不可用"):
        await mcp._tool_search_images(
            {"keyword": "夕阳", "match": "semantic"}, session=None, api_user=ANON
        )


@pytest.mark.asyncio
async def test_invalid_enum_rejected() -> None:
    """非法 match/sort 枚举值直接报错。"""
    with pytest.raises(ValueError, match="match 参数无效"):
        await mcp._tool_search_images({"match": "vector"}, session=None, api_user=ANON)
    with pytest.raises(ValueError, match="sort 参数无效"):
        await mcp._tool_search_images({"sort": "newest"}, session=None, api_user=ANON)


# ============================================================
# get_image_detail 可见性
# ============================================================

@pytest.mark.asyncio
async def test_detail_private_image_hidden_from_anonymous(monkeypatch) -> None:
    """匿名访问私有图 → 与不存在一致的错误。"""

    async def fake_get(session, image_id):
        return _orm_image(image_id=5, is_public=False, uploaded_by=7)

    monkeypatch.setattr(mcp.image_repository, "get_with_tags", fake_get)

    with pytest.raises(ValueError, match="not found"):
        await mcp._tool_get_image_detail({"image_id": 5}, session=None, api_user=ANON)


@pytest.mark.asyncio
async def test_detail_private_image_visible_to_owner_and_admin(monkeypatch) -> None:
    """私有图对上传者本人与 admin 可见。"""

    async def fake_get(session, image_id):
        return _orm_image(image_id=5, is_public=False, uploaded_by=7)

    async def fake_url(image):
        return "http://u/5"

    monkeypatch.setattr(mcp.image_repository, "get_with_tags", fake_get)
    monkeypatch.setattr(mcp.storage_service, "get_read_url", fake_url)

    for user in (USER, ADMIN):
        result = await mcp._tool_get_image_detail(
            {"image_id": 5}, session=None, api_user=user
        )
        assert result["id"] == 5
        assert result["tags"] == ["普通标签"]


# ============================================================
# execute_tool 作用域与权限边界
# ============================================================

@pytest.mark.asyncio
async def test_readonly_scope_blocks_write_tool() -> None:
    """公共只读端点调用写工具 → 拒绝（即使是 admin）。"""
    with pytest.raises(ValueError, match="只读"):
        await mcp.execute_tool(
            "add_image", {"image_url": "http://x"}, session=None,
            api_user=ADMIN, scope=mcp.SCOPE_READONLY,
        )


@pytest.mark.asyncio
async def test_full_scope_requires_upload_permission() -> None:
    """全功能端点下无 UPLOAD_IMAGE 权限的用户调用 add_image → 拒绝。"""
    with pytest.raises(ValueError, match="上传图片"):
        await mcp.execute_tool(
            "add_image", {"image_url": "http://x"}, session=None,
            api_user=USER, scope=mcp.SCOPE_FULL,
        )


@pytest.mark.asyncio
async def test_readonly_scope_with_key_expands_visibility(monkeypatch) -> None:
    """只读端点携带有效 Key：工具仍只读，但可见范围为 public + 本人上传。"""
    calls: list[dict] = []

    async def fake_random(session, tag_names, count, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(mcp.image_repository, "get_random_by_tags", fake_random)

    await mcp.execute_tool(
        "search_images", {}, session=None, api_user=USER, scope=mcp.SCOPE_READONLY,
    )

    assert calls[0]["visible_to_user_id"] == 7
    assert calls[0]["skip_visibility_filter"] is False


@pytest.mark.asyncio
async def test_unknown_tool_rejected() -> None:
    """未注册工具名 → 拒绝（tools/list 之外的防线）。"""
    with pytest.raises(ValueError, match="Unknown tool"):
        await mcp.execute_tool(
            "get_random_images", {}, session=None, api_user=ADMIN, scope=mcp.SCOPE_FULL,
        )


def test_registry_listing_by_scope_and_permission() -> None:
    """tools/list 过滤：readonly 只见只读工具；写工具按权限位显隐。"""
    readonly_names = [t["name"] for t in mcp.list_tools_for(mcp.SCOPE_READONLY, ADMIN)]
    assert readonly_names == ["search_images", "get_image_detail"]

    no_perm_names = [t["name"] for t in mcp.list_tools_for(mcp.SCOPE_FULL, USER)]
    assert "add_image" not in no_perm_names

    uploader = dict(USER, permissions=int(mcp.Permission.UPLOAD_IMAGE))
    uploader_names = [t["name"] for t in mcp.list_tools_for(mcp.SCOPE_FULL, uploader)]
    assert "add_image" in uploader_names


@pytest.mark.parametrize('limit,expected_ids', [(1,[3]), (20,[3,1])])
async def test_smart_search_handles_zero_vectors_before_ordering_and_limit(monkeypatch, limit, expected_ids):
    """执行实际搜索 SQL，仅将 pgvector 运算符适配为内存库的余弦函数。"""
    connection = sqlite3.connect(':memory:')
    def cosine_distance(stored, query):
        left, right = json.loads(stored), json.loads(query)
        norm = math.hypot(*left) * math.hypot(*right)
        return 1 - sum(a*b for a,b in zip(left,right)) / norm if norm else None
    connection.create_function('cosine_distance', 2, cosine_distance)
    connection.executescript("""
        CREATE TABLE images (id INTEGER, description TEXT, original_url TEXT,
            embedding TEXT, is_public BOOLEAN, uploaded_by INTEGER);
        CREATE TABLE image_tags (image_id INTEGER, tag_id INTEGER);
        CREATE TABLE tags (id INTEGER, name TEXT);
        CREATE TABLE users (id INTEGER, username TEXT);
        CREATE TABLE subjects (id INTEGER, primary_tag_id INTEGER,
            alias_tag_ids TEXT, is_active BOOLEAN);
        INSERT INTO images VALUES (1,'零向量标签命中',NULL,'[0,0]',1,1),
            (2,'零向量无标签',NULL,'[0,0]',1,1), (3,'正常向量',NULL,'[1,0]',1,1),
            (4,'反向向量',NULL,'[-1,0]',1,1), (5,'私有图片',NULL,'[1,0]',0,2);
        INSERT INTO tags VALUES (7,'拉电线');
        INSERT INTO image_tags VALUES (1,7);
    """)
    async def execute(statement, params=None):
        if isinstance(statement, (TextClause, TextualSelect)):
            compiled = statement.params(**params).compile(
                dialect=postgresql.dialect(paramstyle='named'),
                compile_kwargs={'render_postcompile': True},
            )
            params = compiled.params
            sql = str(compiled).replace('i.embedding <=> :vector','cosine_distance(i.embedding, :vector)')
            sql = re.sub(
                r'(\w+\.\w+) = ANY \(subjects.alias_tag_ids\)',
                r'\1 IN (SELECT value FROM json_each(subjects.alias_tag_ids))', sql,
            )
            return connection.execute(sql, params)
        return []  # 标签展示和上传者信息查询与本回归无关。
    session = SimpleNamespace(execute=execute, close=AsyncMock())
    monkeypatch.setattr(images.embedding_service, 'get_embedding', AsyncMock(return_value=[1.0,0.0]))
    monkeypatch.setattr(images.storage_service, 'get_read_urls_by_ids', AsyncMock(return_value={}))
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_current_user_optional] = lambda: None
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/images/smart-search', json={'text':'拉电线','size':limit})
        assert response.status_code == 200, response.text
        data = response.json()['data']
        assert [row['id'] for row in data] == expected_ids
        assert [row['similarity'] for row in data] == pytest.approx([0.7,0.3][:limit])
        json.dumps(response.json(), allow_nan=False)
    finally:
        connection.close()


@pytest.mark.parametrize('payload', [
    {'text': '字' * 201}, {'text': '字' * 100000},
    {'text': '猫', 'tags': ['字' * 201]},
])
async def test_smart_search_rejects_large_input_before_embedding_or_query(monkeypatch, payload):
    embed = AsyncMock()
    query = AsyncMock()
    monkeypatch.setattr(images.embedding_service, 'get_embedding', embed)
    monkeypatch.setattr(images.image_repository, 'hybrid_search', query)
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.dependency_overrides[get_async_session] = lambda: SimpleNamespace(close=AsyncMock(), rollback=AsyncMock())
    app.dependency_overrides[get_current_user_optional] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/images/smart-search', json=payload)
    assert response.status_code == 422, response.text
    embed.assert_not_awaited()
    query.assert_not_awaited()


@pytest.mark.parametrize('count', [21, 1001])
async def test_anonymous_smart_search_does_not_limit_tag_count(monkeypatch, count):
    tags = ['猫'] * count
    combined = AsyncMock(return_value=[1.0, 0.0])
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(images.embedding_service, 'get_embedding_combined', combined)
    monkeypatch.setattr(mcp.embedding_service, 'get_embedding', AsyncMock(return_value=[1.0, 0.0]))
    monkeypatch.setattr(images.image_repository, 'hybrid_search', query)
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.dependency_overrides[get_async_session] = lambda: SimpleNamespace(close=AsyncMock(), rollback=AsyncMock())
    app.dependency_overrides[get_current_user_optional] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/images/smart-search', json={'text': '猫', 'tags': tags})
    assert response.status_code == 200, response.text
    combined.assert_not_awaited()
    assert query.await_args.kwargs['tags'] == tags
    await mcp.execute_tool('search_images', {'keyword': '猫', 'tags': tags}, None, None, mcp.SCOPE_READONLY)
    assert query.await_count == 2
    assert query.await_args.kwargs['tags'] == tags


async def test_http_and_mcp_share_anonymous_ip_budget_but_fuzzy_search_is_unaffected(monkeypatch):
    monkeypatch.setattr(search_guard, 'load_policy', AsyncMock(return_value=SearchPolicy(rate_limit=1)))
    monkeypatch.setattr(mcp.embedding_service, 'get_embedding', AsyncMock(return_value=[1.0, 0.0]))
    monkeypatch.setattr(mcp.image_repository, 'hybrid_search', AsyncMock(return_value=[]))
    token = guard_module.search_client_host.set('127.0.0.1')
    try:
        await mcp._tool_search_images({'keyword': '猫'}, session=None, api_user=None)
    finally:
        guard_module.search_client_host.reset(token)
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.dependency_overrides[get_async_session] = lambda: SimpleNamespace(close=AsyncMock(), rollback=AsyncMock())
    app.dependency_overrides[get_current_user_optional] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/images/smart-search', json={'text': '猫'})
    assert response.status_code == 429
    assert int(response.headers['Retry-After']) >= 1
    browse = AsyncMock(return_value={'images': []})
    monkeypatch.setattr(mcp, '_browse_images', browse)
    assert await mcp._tool_search_images({'keyword': '字' * 1000, 'match': 'fuzzy'}, None, None) == {'images': []}
    browse.assert_awaited_once()


async def test_ordinary_http_search_is_not_limited(monkeypatch):
    monkeypatch.setattr(search_guard, 'load_policy', AsyncMock(side_effect=AssertionError('不应进入智能搜索保护')))
    monkeypatch.setattr(images.image_repository, 'search_images', AsyncMock(return_value={'images': [], 'total': 0}))
    monkeypatch.setattr(images.image_repository, 'get_batch_image_tags_with_source', AsyncMock(return_value={}))
    monkeypatch.setattr(images.image_subject_repository, 'list_by_image_ids', AsyncMock(return_value={}))
    monkeypatch.setattr(images, '_images_to_responses', AsyncMock(return_value=[]))
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.dependency_overrides[get_async_session] = lambda: SimpleNamespace(close=AsyncMock(), rollback=AsyncMock())
    app.dependency_overrides[get_current_user_optional] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/images/search', json={'keyword': '字' * 201, 'tags': ['猫'] * 21})
    assert response.status_code == 200, response.text
    random = AsyncMock(return_value=[])
    monkeypatch.setattr(mcp.image_repository, 'get_random_by_tags', random)
    await mcp.execute_tool('search_images', {'keyword': ' ' * 300}, None, USER, mcp.SCOPE_READONLY)
    random.assert_awaited_once()


@pytest.mark.parametrize('unit,multiplier', [('second', 1), ('minute', 60), ('hour', 3600)])
async def test_search_policy_loads_saved_units_and_values(monkeypatch, unit, multiplier):
    saved = SEARCH_DEFAULTS | {'search_max_text_length': '300', 'search_rate_interval': '2', 'search_rate_unit': unit}
    monkeypatch.setattr(guard_module.config_cache, 'get', AsyncMock(side_effect=lambda key, default, **kwargs: saved[key]))
    policy = await SearchGuardService().load_policy()
    assert policy.max_text_length == 300
    assert policy.window_seconds == 2 * multiplier
    assert policy.rate_limit == 20


async def test_sliding_window_has_exact_boundary_and_live_policy_changes(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(guard_module, 'monotonic', lambda: clock[0])
    policy = [SearchPolicy(rate_limit=2)]
    monkeypatch.setattr(search_guard, 'load_policy', AsyncMock(side_effect=lambda **kwargs: policy[0]))
    for _ in range(2):
        await search_guard.check('ip:a')
    with pytest.raises(SearchRejected) as error:
        await search_guard.check('ip:a')
    assert error.value.retry_after == 60
    await search_guard.check('ip:b')
    clock[0] = 69.9
    with pytest.raises(SearchRejected):
        await search_guard.check('ip:a')
    clock[0] = 70.0
    await search_guard.check('ip:a')
    policy[0] = SearchPolicy(max_text_length=1, rate_limit=1)
    with pytest.raises(SearchRejected, match='1 个字符'):
        await search_guard.check('ip:c', texts=('猫咪',))


async def test_search_limiter_bounds_memory_without_evicting_unexpired_budgets(monkeypatch):
    monkeypatch.setattr(search_guard, 'MAX_CALLERS', 2)
    clock = [0.0]
    monkeypatch.setattr(guard_module, 'monotonic', lambda: clock[0])
    for caller in ('a', 'b'):
        await search_guard.check(caller)
    with pytest.raises(SearchRejected, match='繁忙'):
        await search_guard.check('c')
    assert set(search_guard._callers) == {'a', 'b'}
    clock[0] = 60
    await search_guard.check('c')
    assert set(search_guard._callers) == {'c'}


@pytest.mark.parametrize('different_ips', [False, True])
async def test_simultaneous_requests_only_consume_frequency_budget(monkeypatch, different_ips):
    monkeypatch.setattr(search_guard, 'load_policy', AsyncMock(return_value=SearchPolicy()))
    release = asyncio.Event()
    entered = []

    async def run(index):
        caller = f'ip:{index}' if different_ips else 'ip:shared'
        try:
            await search_guard.check(caller)
        except SearchRejected:
            return 'rejected'
        entered.append(index)
        await release.wait()

    tasks = [asyncio.create_task(run(index)) for index in range(50)]
    await asyncio.sleep(0)
    expected = 50 if different_ips else 20
    assert entered == list(range(expected))
    # 允许多于原来的 2/8 个请求同时执行；同 IP 仍只获准 20 次。
    tasks[0].cancel()
    with pytest.raises(asyncio.CancelledError):
        await tasks[0]
    if not different_ips:
        assert len(search_guard._callers['ip:shared']) == 20
        with pytest.raises(SearchRejected, match='过于频繁'):
            await search_guard.check('ip:shared')
    release.set()
    results = await asyncio.gather(*tasks[1:])
    assert results.count('rejected') == 50 - expected
    assert sum(len(window) for window in search_guard._callers.values()) == expected


async def test_mcp_semantic_limits_can_be_increased_without_changing_fuzzy_limits(monkeypatch):
    monkeypatch.setattr(search_guard, 'load_policy', AsyncMock(return_value=SearchPolicy(max_text_length=700)))
    embed = AsyncMock(return_value=[1.0, 0.0])
    monkeypatch.setattr(mcp.embedding_service, 'get_embedding', embed)
    monkeypatch.setattr(mcp.image_repository, 'hybrid_search', AsyncMock(return_value=[]))
    arguments = {'keyword': '字' * 600, 'tags': ['猫' * 150] * 60}
    await mcp.execute_tool('search_images', arguments, None, None, mcp.SCOPE_READONLY)
    embed.assert_awaited_once_with('字' * 600, session=None)
    with pytest.raises(ValueError, match='参数校验失败'):
        await mcp.execute_tool('search_images', arguments | {'match': 'fuzzy'}, None, None, mcp.SCOPE_READONLY)


async def test_mcp_anonymous_budget_uses_request_source_and_resets_context(monkeypatch):
    monkeypatch.setattr(search_guard, 'load_policy', AsyncMock(return_value=SearchPolicy(rate_limit=1)))
    monkeypatch.setattr(mcp.embedding_service, 'get_embedding', AsyncMock(return_value=[1.0, 0.0]))
    monkeypatch.setattr(mcp.image_repository, 'hybrid_search', AsyncMock(return_value=[]))
    rpc = mcp.JsonRpcRequest(jsonrpc='2.0', id=1, method='tools/call', params={'name': 'search_images', 'arguments': {'keyword': '猫'}})
    first = await mcp.process_jsonrpc(rpc, scope=mcp.SCOPE_READONLY, api_user=None, session=None, client_host='192.0.2.1')
    blocked = await mcp.process_jsonrpc(rpc, scope=mcp.SCOPE_READONLY, api_user=None, session=None, client_host='192.0.2.1')
    other = await mcp.process_jsonrpc(rpc, scope=mcp.SCOPE_READONLY, api_user=None, session=None, client_host='192.0.2.2')
    assert not first.result.get('isError') and not other.result.get('isError')
    assert blocked.result['isError'] is True
    assert guard_module.search_client_host.get() == 'unknown'


@pytest.mark.parametrize('auth_type', ['jwt', 'admin', 'x-api-key', 'api_key', 'bearer_key', 'query_key'])
async def test_authenticated_http_search_bypasses_all_anonymous_limits(monkeypatch, auth_type):
    policy = AsyncMock(side_effect=AssertionError('已认证请求不应读取匿名限制'))
    monkeypatch.setattr(search_guard, 'load_policy', policy)
    monkeypatch.setattr(images.embedding_service, 'get_embedding', AsyncMock(return_value=[1.0, 0.0]))
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(images.image_repository, 'hybrid_search', query)
    user = ADMIN if auth_type == 'admin' else USER
    lookup = AsyncMock(return_value=user)
    monkeypatch.setattr(search_guards, 'get_user_by_api_key', lookup)
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.dependency_overrides[get_async_session] = lambda: SimpleNamespace(close=AsyncMock(), rollback=AsyncMock())
    app.dependency_overrides[get_current_user_optional] = lambda: user if auth_type in ('jwt', 'admin') else None
    headers = {
        'x-api-key': {'X-API-Key': 'valid-test-key'},
        'api_key': {'api_key': 'valid-test-key'},
        'bearer_key': {'Authorization': 'Bearer valid-test-key'},
    }.get(auth_type, {})
    params = {'api_key': 'valid-test-key'} if auth_type == 'query_key' else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/images/smart-search', headers=headers, params=params,
                                     json={'text': '字' * 1000, 'tags': ['猫'] * 1001})
    assert response.status_code == 200, response.text
    policy.assert_not_awaited()
    assert search_guard._callers == {}
    assert query.await_args.kwargs['skip_visibility_filter'] is (auth_type == 'admin')
    assert query.await_args.kwargs['visible_to_user_id'] == (None if auth_type == 'admin' else USER['id'])
    if auth_type in ('jwt', 'admin'):
        lookup.assert_not_awaited()
    else:
        assert lookup.await_count == 1
        assert lookup.await_args.args[1] == 'valid-test-key'


@pytest.mark.parametrize('status_code', [401, 403])
async def test_unverified_api_key_does_not_get_search_exemption(monkeypatch, status_code):
    lookup = AsyncMock(side_effect=HTTPException(status_code, detail='认证失败'))
    monkeypatch.setattr(search_guards, 'get_user_by_api_key', lookup)
    embed = AsyncMock()
    monkeypatch.setattr(images.embedding_service, 'get_embedding', embed)
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.dependency_overrides[get_async_session] = lambda: SimpleNamespace(close=AsyncMock(), rollback=AsyncMock())
    app.dependency_overrides[get_current_user_optional] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/images/smart-search', headers={'X-API-Key': 'invalid-test-key'}, json={'text': '猫'})
    assert response.status_code == status_code
    embed.assert_not_awaited()
    assert search_guard._callers == {}


@pytest.mark.parametrize('header_name', ['X-API-Key', 'Authorization', 'api_key'])
async def test_mcp_public_authenticated_headers_bypass_anonymous_budgets(monkeypatch, header_name):
    monkeypatch.setattr(search_guard, 'load_policy', AsyncMock(return_value=SearchPolicy(rate_limit=1)))
    monkeypatch.setattr(mcp, '_mcp_rate_windows', {})
    monkeypatch.setattr(auth_dependencies, 'get_user_by_api_key', AsyncMock(return_value=USER))
    monkeypatch.setattr(mcp.embedding_service, 'get_embedding', AsyncMock(return_value=[1.0, 0.0]))
    monkeypatch.setattr(mcp.image_repository, 'hybrid_search', AsyncMock(return_value=[]))
    app = FastAPI()
    app.include_router(mcp.router, prefix='/mcp')
    app.dependency_overrides[get_async_session] = lambda: SimpleNamespace(close=AsyncMock(), rollback=AsyncMock())
    payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
               'params': {'name': 'search_images', 'arguments': {'keyword': '猫'}}}
    headers = {header_name: 'Bearer valid-test-key' if header_name == 'Authorization' else 'valid-test-key'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        first = await client.post('/mcp/public', json=payload)
        blocked = await client.post('/mcp/public', json=payload)
        assert not first.json()['result'].get('isError')
        assert blocked.json()['result']['isError'] is True
        payload['params']['arguments'] = {'keyword': '字' * 1000, 'tags': ['猫'] * 1001}
        for _ in range(2):
            response = await client.post('/mcp/public', json=payload, headers=headers)
            assert response.status_code == 200, response.text
            assert not response.json()['result'].get('isError'), response.text
    assert search_guard.load_policy.await_count == 2
    assert set(search_guard._callers) == {'ip:127.0.0.1'}
    assert set(mcp._mcp_rate_windows) == {'ip:127.0.0.1'}
    assert mcp.image_repository.hybrid_search.await_args.kwargs['visible_to_user_id'] == USER['id']
    assert mcp.image_repository.hybrid_search.await_args.kwargs['skip_visibility_filter'] is False


async def test_authenticated_mcp_has_no_transport_frequency_limit(monkeypatch):
    monkeypatch.setattr(mcp, '_mcp_rate_windows', {})
    request = SimpleNamespace(client=SimpleNamespace(host='192.0.2.10'))
    for _ in range(350):
        mcp._check_rate_limit(request, USER)
    assert mcp._mcp_rate_windows == {}


@pytest.mark.parametrize('single', [False, True])
async def test_saved_search_settings_are_used_by_guard(monkeypatch, single):
    from imgtag.api.endpoints import config as config_api
    from imgtag.api.endpoints.auth import get_current_user

    saved = dict(SEARCH_DEFAULTS)

    async def batch_write(session, configs):
        saved.update(configs)
        return True

    async def one_write(session, key, value, **kwargs):
        saved[key] = value
        return True

    app = FastAPI()
    app.include_router(config_api.router, prefix='/config')
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    app.dependency_overrides[config_api.get_async_session] = lambda: SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(config_api.config_repository, 'update_multiple', batch_write)
    monkeypatch.setattr(config_api.config_repository, 'set_value', one_write)
    monkeypatch.setattr(config_api.config_cache, 'clear', lambda: None)
    monkeypatch.setattr(config_api.config_cache, 'preload', AsyncMock())
    monkeypatch.setattr(guard_module.config_cache, 'get', AsyncMock(side_effect=lambda key, default, **kwargs: saved[key]))
    values = {'search_max_text_length': '350', 'search_rate_interval': '2', 'search_rate_unit': 'hour'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        if single:
            for key, value in values.items():
                assert (await client.put(f'/config/{key}', params={'value': value})).status_code == 200
        else:
            assert (await client.put('/config/', json={'configs': values})).status_code == 200
    policy = await SearchGuardService().load_policy()
    assert policy.max_text_length == 350 and policy.window_seconds == 7200


@pytest.mark.parametrize('single', [False, True])
@pytest.mark.parametrize('key,value', [
    ('search_max_text_length', '0'),
    ('search_rate_limit', '-1'), ('search_rate_interval', '1.5'),
    ('search_rate_unit', 'day'),
])
async def test_search_config_rejects_invalid_settings_before_writing(monkeypatch, single, key, value):
    from imgtag.api.endpoints import config as config_api
    from imgtag.api.endpoints.auth import get_current_user

    app = FastAPI()
    app.include_router(config_api.router, prefix='/config')
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    app.dependency_overrides[config_api.get_async_session] = lambda: SimpleNamespace(close=AsyncMock(), rollback=AsyncMock())
    batch = AsyncMock()
    one = AsyncMock()
    monkeypatch.setattr(config_api.config_repository, 'update_multiple', batch)
    monkeypatch.setattr(config_api.config_repository, 'set_value', one)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        if single:
            response = await client.put(f'/config/{key}', params={'value': value})
        else:
            response = await client.put('/config/', json={'configs': {key: value}})
    assert response.status_code == 400
    batch.assert_not_awaited()
    one.assert_not_awaited()
