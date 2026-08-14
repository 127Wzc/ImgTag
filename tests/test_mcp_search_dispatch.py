"""MCP 合并版 search_images 分发逻辑与作用域边界测试。

不依赖数据库：仓库层与 embedding 服务均以 monkeypatch 替换，
仅验证 mcp.py 内的分发矩阵、可见性参数传递与 scope/权限边界。
"""

from types import SimpleNamespace

import pytest

from imgtag.api.endpoints import mcp

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
