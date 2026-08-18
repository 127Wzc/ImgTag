"""MCP 双挂载点 HTTP 层测试。

不依赖数据库：
- 握手流程直接驱动端点函数与 SSE body_iterator（避免流式传输框架差异）；
- 鉴权边界通过 ASGI 客户端验证（401 / Session not found 均在触达 DB 前返回）。
"""

import asyncio
import json

import httpx
import pytest

from imgtag.api.endpoints import mcp
from imgtag.main import app

USER = {"id": 7, "username": "u1", "role": "user", "is_active": True, "permissions": 0}


class _FakeRequest:
    """最小化 Request 桩：SSE 循环只用 is_disconnected，message 端点只用 json()"""

    def __init__(self, body: dict | None = None):
        self._body = body

    async def is_disconnected(self) -> bool:
        return False

    async def json(self) -> dict:
        return self._body


async def _next_sse_data(body_iter) -> str:
    """读取下一个 SSE 事件中的 data 行内容"""
    chunk = await asyncio.wait_for(body_iter.__anext__(), timeout=5)
    for line in str(chunk).splitlines():
        if line.startswith("data: "):
            return line[len("data: "):]
    raise AssertionError(f"SSE 块中未找到 data 行: {chunk!r}")


@pytest.mark.asyncio
async def test_public_anonymous_handshake_and_readonly_boundary() -> None:
    """匿名走通 public 握手：endpoint 事件 → initialize → tools/list → 写工具被拒。"""
    sse_response = await mcp.mcp_public_sse_endpoint(
        request=_FakeRequest(), api_user=None
    )
    body_iter = sse_response.body_iterator

    try:
        # 1. endpoint 事件必须指向 public 消息路径
        message_url = await _next_sse_data(body_iter)
        assert message_url.startswith("/api/v1/mcp/public/message?session_id=")
        session_id = message_url.split("session_id=")[1]
        assert session_id in mcp._connections
        assert mcp._connections[session_id].scope == mcp.SCOPE_READONLY

        # 2. initialize：旧客户端请求旧协议版本，应原样回显
        ack = await mcp.mcp_public_message_endpoint(
            request=_FakeRequest({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }),
            session_id=session_id,
            session=None,
        )
        assert ack == {"status": "ok"}
        payload = json.loads(await _next_sse_data(body_iter))
        assert payload["result"]["protocolVersion"] == "2024-11-05"
        assert "只读" in payload["result"]["instructions"]

        # 3. tools/list：匿名只见两个只读工具
        await mcp.mcp_public_message_endpoint(
            request=_FakeRequest({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            session_id=session_id,
            session=None,
        )
        payload = json.loads(await _next_sse_data(body_iter))
        names = [t["name"] for t in payload["result"]["tools"]]
        assert names == ["search_images", "get_image_detail"]

        # 4. tools/call 写工具：在触达 session 前即被作用域拒绝
        await mcp.mcp_public_message_endpoint(
            request=_FakeRequest({
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "add_image", "arguments": {"image_url": "http://x"}},
            }),
            session_id=session_id,
            session=None,
        )
        payload = json.loads(await _next_sse_data(body_iter))
        assert payload["result"]["isError"] is True
        assert "只读" in payload["result"]["content"][0]["text"]
    finally:
        await body_iter.aclose()

    # 连接关闭后应从注册表清理
    assert session_id not in mcp._connections


@pytest.mark.asyncio
async def test_public_anonymous_connection_cap(monkeypatch) -> None:
    """匿名连接数达到上限时返回 429；携带 Key 的连接不受该上限约束。"""
    monkeypatch.setattr(mcp, "MAX_ANONYMOUS_CONNECTIONS", 0)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await mcp.mcp_public_sse_endpoint(request=_FakeRequest(), api_user=None)
    assert exc_info.value.status_code == 429

    # 带 Key 不受匿名上限影响
    sse_response = await mcp.mcp_public_sse_endpoint(
        request=_FakeRequest(), api_user=USER
    )
    body_iter = sse_response.body_iterator
    try:
        message_url = await _next_sse_data(body_iter)
        session_id = message_url.split("session_id=")[1]
        connection = mcp._connections[session_id]
        # 带 Key 的只读连接：身份保留（可见性扩大），作用域仍为只读
        assert connection.api_user == USER
        assert connection.scope == mcp.SCOPE_READONLY
    finally:
        await body_iter.aclose()


@pytest.mark.asyncio
async def test_full_endpoint_requires_api_key_public_does_not() -> None:
    """ASGI 层鉴权边界：/sse 无 Key 401;/public/message 未知会话返回 JSON-RPC 错误。"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/mcp/sse")
        assert resp.status_code == 401

        resp = await client.post(
            "/api/v1/mcp/public/message",
            params={"session_id": "not-exist"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert resp.status_code == 200
        assert resp.json()["error"]["code"] == -32000


# ============================================================
# Streamable HTTP 端点（现行标准传输）
# ============================================================

@pytest.mark.asyncio
async def test_streamable_public_full_flow() -> None:
    """匿名走通 public Streamable HTTP：initialize → 通知 202 → tools/list → 写工具被拒。"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # initialize：请求现行版本，原样回显，带只读说明
        resp = await client.post("/api/v1/mcp/public", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        })
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.headers["MCP-Protocol-Version"] == "2025-06-18"
        result = resp.json()["result"]
        assert result["protocolVersion"] == "2025-06-18"
        assert "只读" in result["instructions"]

        # 通知类消息：202 无响应体
        resp = await client.post("/api/v1/mcp/public", json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        assert resp.status_code == 202
        assert resp.content == b""

        # tools/list：匿名只见只读工具
        resp = await client.post("/api/v1/mcp/public", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list",
        })
        names = [t["name"] for t in resp.json()["result"]["tools"]]
        assert names == ["search_images", "get_image_detail"]

        # 写工具被作用域拒绝
        resp = await client.post("/api/v1/mcp/public", json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "add_image", "arguments": {"image_url": "http://x"}},
        })
        payload = resp.json()["result"]
        assert payload["isError"] is True
        assert "只读" in payload["content"][0]["text"]


@pytest.mark.asyncio
async def test_streamable_protocol_and_error_edges() -> None:
    """协议协商回退、批量拒绝、解析错误、GET 405、全功能端点 401。"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 未知协议版本 → 回退默认版本
        resp = await client.post("/api/v1/mcp/public", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "1999-01-01"},
        })
        assert resp.json()["result"]["protocolVersion"] == mcp.DEFAULT_PROTOCOL_VERSION

        # 批量请求 → 400（2025-06-18 起移除批量）
        resp = await client.post("/api/v1/mcp/public", json=[
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        ])
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == -32600

        # 非法 JSON → 400 解析错误
        resp = await client.post(
            "/api/v1/mcp/public",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == -32700

        # GET 无监听流 → 405（规范定义的新旧传输探测信号）
        resp = await client.get("/api/v1/mcp/public")
        assert resp.status_code == 405

        # 全功能 Streamable 端点无 Key → 401
        resp = await client.post("/api/v1/mcp", json={
            "jsonrpc": "2.0", "id": 3, "method": "ping",
        })
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_tools_call_protocol_and_result_shapes(monkeypatch) -> None:
    """tools/call 遵循 JSON-RPC 2.0 与标准 CallToolResult 分层。"""

    async def fake_execute(name, arguments, session, api_user, scope):
        assert name == "search_images"
        assert arguments == {"keyword": "夕阳"}
        return {"images": [], "total": 0}

    monkeypatch.setattr(mcp, "execute_tool", fake_execute)

    success = await mcp.process_jsonrpc(
        mcp.JsonRpcRequest(
            jsonrpc="2.0",
            id=10,
            method="tools/call",
            params={"name": "search_images", "arguments": {"keyword": "夕阳"}},
        ),
        scope=mcp.SCOPE_READONLY,
        api_user=None,
        session=None,
    )
    assert success is not None
    payload = success.model_dump(exclude_none=True)
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == 10
    assert payload["result"]["content"][0]["type"] == "text"
    assert json.loads(payload["result"]["content"][0]["text"]) == {
        "images": [], "total": 0
    }
    assert payload["result"]["structuredContent"] == {"images": [], "total": 0}
    assert payload["result"]["isError"] is False

    unknown = await mcp.process_jsonrpc(
        mcp.JsonRpcRequest(
            jsonrpc="2.0",
            id=11,
            method="tools/call",
            params={"name": "not_registered", "arguments": {}},
        ),
        scope=mcp.SCOPE_READONLY,
        api_user=None,
        session=None,
    )
    assert unknown is not None
    unknown_payload = unknown.model_dump(exclude_none=True)
    assert unknown_payload["error"]["code"] == -32602
    assert "result" not in unknown_payload

    invalid_params = await mcp.process_jsonrpc(
        mcp.JsonRpcRequest(
            jsonrpc="2.0",
            id=12,
            method="tools/call",
            params={"name": "search_images", "arguments": []},
        ),
        scope=mcp.SCOPE_READONLY,
        api_user=None,
        session=None,
    )
    assert invalid_params is not None
    invalid_payload = invalid_params.model_dump(exclude_none=True)
    assert invalid_payload["error"]["code"] == -32602
    assert "result" not in invalid_payload


@pytest.mark.asyncio
async def test_streamable_rejects_non_jsonrpc2_requests() -> None:
    """Streamable HTTP 拒绝错误版本、缺失请求 ID 与带 ID 的通知。"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for body in (
            {"jsonrpc": "1.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "ping"},
            {"jsonrpc": "2.0", "id": 1, "method": "notifications/initialized"},
        ):
            resp = await client.post("/api/v1/mcp/public", json=body)
            assert resp.status_code == 400
            assert resp.json()["error"]["code"] == -32600


@pytest.mark.asyncio
async def test_mcp_input_validation_and_safe_internal_errors(monkeypatch) -> None:
    """工具参数严格校验，内部异常不把实现细节返回给客户端。"""
    invalid = await mcp.process_jsonrpc(
        mcp.JsonRpcRequest(
            jsonrpc="2.0",
            id=20,
            method="tools/call",
            params={
                "name": "search_images",
                "arguments": {"count": "10"},
            },
        ),
        scope=mcp.SCOPE_READONLY,
        api_user=None,
        session=None,
    )
    assert invalid is not None
    invalid_payload = invalid.model_dump(exclude_none=True)
    assert invalid_payload["result"]["isError"] is True
    assert "参数校验" in invalid_payload["result"]["content"][0]["text"]

    async def exploding_execute(*args, **kwargs):
        raise RuntimeError("database password=do-not-return")

    monkeypatch.setattr(mcp, "execute_tool", exploding_execute)
    failed = await mcp.process_jsonrpc(
        mcp.JsonRpcRequest(
            jsonrpc="2.0",
            id=21,
            method="tools/call",
            params={"name": "search_images", "arguments": {}},
        ),
        scope=mcp.SCOPE_READONLY,
        api_user=None,
        session=None,
    )
    assert failed is not None
    text = failed.result["content"][0]["text"]
    assert "工具执行失败" in text
    assert "password" not in text


@pytest.mark.asyncio
async def test_streamable_protocol_header_query_key_and_body_limits(monkeypatch) -> None:
    """MCP 认证凭据不走 query，协议版本和请求体均有边界。"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unsupported = await client.post(
            "/api/v1/mcp/public",
            json={"jsonrpc": "2.0", "id": 30, "method": "ping"},
            headers={"MCP-Protocol-Version": "1999-01-01"},
        )
        assert unsupported.status_code == 400
        assert unsupported.json()["error"]["code"] == -32602

        query_key = await client.post(
            "/api/v1/mcp/public?api_key=secret",
            json={"jsonrpc": "2.0", "id": 31, "method": "ping"},
        )
        assert query_key.status_code == 400

        monkeypatch.setattr(mcp, "MCP_MAX_REQUEST_BYTES", 32)
        too_large = await client.post(
            "/api/v1/mcp/public",
            content=b"{" + b"a" * 64,
            headers={"content-type": "application/json"},
        )
        assert too_large.status_code == 413
