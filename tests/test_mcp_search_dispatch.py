"""MCP 合并版 search_images 分发逻辑与作用域边界测试。

不依赖数据库：仓库层与 embedding 服务均以 monkeypatch 替换，
仅验证 mcp.py 内的分发矩阵、可见性参数传递与 scope/权限边界。
"""

import asyncio
import json
import math
import re
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI, HTTPException
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import TextualSelect

import pytest

from imgtag.api.endpoints import images, mcp
from imgtag.api.endpoints.auth import get_current_user_optional
from imgtag.api import dependencies as auth_dependencies, search_guards
from imgtag.db import get_async_session
from imgtag.core.search_limits import SEARCH_DEFAULTS, SearchPolicy
from imgtag.services import search_guard_service as guard_module
from imgtag.services.search_guard_service import SearchGuardService, SearchRejected, search_guard

ANON = None
USER = {"id": 7, "username": "u1", "role": "user", "is_active": True, "permissions": 0}
ADMIN = {"id": 1, "username": "root", "role": "admin", "is_active": True, "permissions": 0}


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

    async def fake_urls(images):
        return {img.id: f"http://u/{img.id}" for img in images}

    monkeypatch.setattr(mcp.image_repository, "search_images", fake_search)
    monkeypatch.setattr(mcp.storage_service, "get_read_urls", fake_urls)

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

    async def fake_embedding(text):
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

    async def fake_embedding(text):
        raise RuntimeError("embedding service down")

    async def fake_search(session, **kwargs):
        return {"images": [_orm_image()], "total": 1}

    async def fake_urls(images):
        return {}

    monkeypatch.setattr(mcp.embedding_service, "get_embedding", fake_embedding)
    monkeypatch.setattr(mcp.image_repository, "search_images", fake_search)
    monkeypatch.setattr(mcp.storage_service, "get_read_urls", fake_urls)

    result = await mcp._tool_search_images(
        {"keyword": "夕阳"}, session=None, api_user=ANON
    )

    assert result["match"] == "fuzzy"
    assert result["sort"] == "latest"
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_explicit_semantic_does_not_fall_back(monkeypatch) -> None:
    """显式 match=semantic 时 embedding 失败直接报错，不降级。"""

    async def fake_embedding(text):
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
            sql = str(statement).replace('i.embedding <=> :vector','cosine_distance(i.embedding, :vector)')
            sql = re.sub(
                r'(\w+\.\w+) = ANY \(subjects.alias_tag_ids\)',
                r'\1 IN (SELECT value FROM json_each(subjects.alias_tag_ids))', sql,
            )
            return connection.execute(sql, params)
        return []  # 标签展示和上传者信息查询与本回归无关。
    session = SimpleNamespace(execute=execute)
    monkeypatch.setattr(images.embedding_service, 'get_embedding', AsyncMock(return_value=[1.0,0.0]))
    monkeypatch.setattr(images.image_repository, 'get_by_ids', AsyncMock(return_value=[]))
    monkeypatch.setattr(images.storage_service, 'get_read_urls', AsyncMock(return_value={}))
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
    app.dependency_overrides[get_async_session] = lambda: object()
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
    app.dependency_overrides[get_async_session] = lambda: object()
    app.dependency_overrides[get_current_user_optional] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/images/smart-search', json={'text': '猫', 'tags': tags})
    assert response.status_code == 200, response.text
    combined.assert_awaited_once_with('猫', tags)
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
    app.dependency_overrides[get_async_session] = lambda: object()
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
    app.dependency_overrides[get_async_session] = lambda: object()
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
    monkeypatch.setattr(guard_module.config_cache, 'get', AsyncMock(side_effect=lambda key, default: saved[key]))
    policy = await SearchGuardService().load_policy()
    assert policy.max_text_length == 300
    assert policy.window_seconds == 2 * multiplier
    assert policy.rate_limit == 20


async def test_sliding_window_has_exact_boundary_and_live_policy_changes(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(guard_module, 'monotonic', lambda: clock[0])
    policy = [SearchPolicy(rate_limit=2)]
    monkeypatch.setattr(search_guard, 'load_policy', AsyncMock(side_effect=lambda: policy[0]))
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
    embed.assert_awaited_once_with('字' * 600)
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
    monkeypatch.setattr(images.embedding_service, 'get_embedding_combined', AsyncMock(return_value=[1.0, 0.0]))
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(images.image_repository, 'hybrid_search', query)
    user = ADMIN if auth_type == 'admin' else USER
    lookup = AsyncMock(return_value=user)
    monkeypatch.setattr(search_guards, 'get_user_by_api_key', lookup)
    app = FastAPI()
    app.include_router(images.router, prefix='/images')
    app.dependency_overrides[get_async_session] = lambda: object()
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
    app.dependency_overrides[get_async_session] = lambda: object()
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
    app.dependency_overrides[get_async_session] = lambda: object()
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
    monkeypatch.setattr(guard_module.config_cache, 'get', AsyncMock(side_effect=lambda key, default: saved[key]))
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
    app.dependency_overrides[config_api.get_async_session] = lambda: object()
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
