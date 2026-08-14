#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""MCP (Model Context Protocol) Server endpoints.

轻量级 MCP 实现，复用现有 API 逻辑，支持 Claude Desktop / Cursor 等 MCP 客户端接入。

传输协议（新旧并存）：
- Streamable HTTP（现行标准，推荐）：单端点 POST，纯请求-响应，无状态
  - POST /api/v1/mcp          全功能（强制 API Key，工具按用户权限过滤）
  - POST /api/v1/mcp/public   公共只读（允许匿名，仅只读工具）
- HTTP+SSE（2024-11-05 旧协议，已弃用，保留给旧客户端）：
  - GET  /api/v1/mcp/sse + POST /api/v1/mcp/message
  - GET  /api/v1/mcp/public/sse + POST /api/v1/mcp/public/message

两种传输共享同一套工具注册表与执行逻辑；公共端点无论传输方式均保持只读，
匿名仅可见 public 图片，携带有效 API Key 后可见范围扩大为 public + 本人上传。
"""

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.dependencies import require_api_key, verify_api_key
from imgtag.core.logging_config import get_logger
from imgtag.core.permissions import (
    Permission,
    check_permission,
    permission_denied_detail,
    permission_denied_with_missing_detail,
)
from imgtag.db import get_async_session
from imgtag.db.repositories import (
    image_location_repository,
    image_repository,
    image_tag_repository,
    storage_endpoint_repository,
    tag_repository,
)
from imgtag.services import embedding_service
from imgtag.services.storage_service import storage_service
from imgtag.services.task_queue import task_queue
from imgtag.services.upload_service import upload_service

logger = get_logger(__name__)

router = APIRouter()

# ============================================================
# MCP 协议常量
# ============================================================

# 协议版本协商：客户端请求的版本在支持集合内则回显，否则返回默认版本
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "imgtag-mcp"
SERVER_VERSION = "2.1.0"

# 端点作用域：full = 全部工具；readonly = 仅只读工具
SCOPE_FULL = "full"
SCOPE_READONLY = "readonly"

# 公共端点匿名 SSE 并发连接上限（防止无界内存占用）
MAX_ANONYMOUS_CONNECTIONS = 20

# search_images 参数枚举
_MATCH_VALUES = {"auto", "semantic", "fuzzy"}
_SORT_VALUES = {"auto", "random", "latest", "relevance"}


# ============================================================
# 可见性辅助
# ============================================================

def _visibility_kwargs(api_user: dict | None) -> dict[str, Any]:
    """按调用者身份生成仓库层可见性参数。

    - 匿名：仅 public 图片
    - 普通用户：public + 自己上传
    - admin：不过滤
    """
    if api_user and api_user.get("role") == "admin":
        return {"visible_to_user_id": None, "skip_visibility_filter": True}
    return {
        "visible_to_user_id": api_user.get("id") if api_user else None,
        "skip_visibility_filter": False,
    }


# ============================================================
# Tool 处理函数
# ============================================================

async def _browse_images(
    session: AsyncSession,
    *,
    tags: list[str],
    keyword: str | None,
    count: int,
    page: int,
    visibility: dict[str, Any],
    resolved_match: str | None,
) -> dict:
    """确定性浏览路径：模糊/标签过滤 + id 倒序 + 分页（唯一支持 page/total 的路径）"""
    offset = (page - 1) * count
    result = await image_repository.search_images(
        session,
        tags=tags or None,
        keyword=keyword,
        limit=count,
        offset=offset,
        **visibility,
    )
    images = result["images"]
    urls = await storage_service.get_read_urls(images)

    return {
        "match": resolved_match,
        "sort": "latest",
        "images": [
            {
                "id": img.id,
                "url": urls.get(img.id, ""),
                "description": img.description or "",
                "tags": [t.name for t in img.tags if t.level == 2],
            }
            for img in images
        ],
        "total": result["total"],
        "page": page,
    }


async def _tool_search_images(
    arguments: dict,
    session: AsyncSession,
    api_user: dict | None,
) -> dict:
    """合并检索工具：随机 / 语义向量 / 模糊匹配 三路分发"""
    keyword = str(arguments.get("keyword") or "").strip()
    raw_tags = arguments.get("tags") or []
    tags = [str(t).strip() for t in raw_tags if t and str(t).strip()]
    match = str(arguments.get("match") or "auto").lower()
    sort = str(arguments.get("sort") or "auto").lower()

    try:
        count = int(arguments.get("count") or 10)
        page = int(arguments.get("page") or 1)
    except (TypeError, ValueError):
        raise ValueError("count 和 page 必须为整数")
    count = max(1, min(count, 50))
    page = max(1, page)

    if match not in _MATCH_VALUES:
        raise ValueError(f"match 参数无效: {match}，可选 auto/semantic/fuzzy")
    if sort not in _SORT_VALUES:
        raise ValueError(f"sort 参数无效: {sort}，可选 auto/random/latest/relevance")

    visibility = _visibility_kwargs(api_user)

    # ---- 无 keyword：随机（默认）或 latest 浏览 ----
    if not keyword:
        if sort == "latest":
            return await _browse_images(
                session,
                tags=tags,
                keyword=None,
                count=count,
                page=page,
                visibility=visibility,
                resolved_match=None,
            )

        # sort 为 auto/random/relevance 时均落到随机（relevance 无 keyword 无意义）
        rows = await image_repository.get_random_by_tags(
            session, tags, count, **visibility
        )
        return {
            "match": None,
            "sort": "random",
            "images": [
                {
                    "id": row["id"],
                    "url": row["image_url"],
                    "description": row["description"],
                    "tags": row["tags"],
                }
                for row in rows
            ],
        }

    # ---- 有 keyword：优先语义，失败按 match 策略降级 ----
    if match in ("auto", "semantic"):
        try:
            query_vector = await embedding_service.get_embedding(keyword)
            results = await image_repository.hybrid_search(
                session,
                query_vector=query_vector,
                query_text=keyword,
                limit=count,
                tags=tags or None,
                **visibility,
            )
            return {
                "match": "semantic",
                "sort": "relevance",
                "images": [
                    {
                        "id": row["id"],
                        "url": row["image_url"],
                        "description": row["description"] or "",
                        "tags": [
                            t["name"] for t in row["tags"] if t.get("level") == 2
                        ],
                        "score": round(float(row["similarity"]), 4),
                    }
                    for row in results
                ],
            }
        except Exception as e:
            if match == "semantic":
                raise ValueError(f"语义搜索暂不可用: {e}")
            logger.warning(f"[MCP] 语义搜索失败，自动降级为模糊匹配: {e}")

    # 显式 fuzzy 或 auto 降级
    return await _browse_images(
        session,
        tags=tags,
        keyword=keyword,
        count=count,
        page=page,
        visibility=visibility,
        resolved_match="fuzzy",
    )


async def _tool_get_image_detail(
    arguments: dict,
    session: AsyncSession,
    api_user: dict | None,
) -> dict:
    """获取图片详情（含可见性校验）"""
    image_id = arguments.get("image_id")
    if not image_id:
        raise ValueError("image_id is required")

    image = await image_repository.get_with_tags(session, int(image_id))

    is_admin = bool(api_user and api_user.get("role") == "admin")
    is_owner = bool(
        api_user and image is not None and image.uploaded_by == api_user.get("id")
    )
    # 私有图对无权者与不存在返回一致错误，避免泄露图片存在性
    if image is None or (not image.is_public and not is_admin and not is_owner):
        raise ValueError(f"Image {image_id} not found")

    display_url = await storage_service.get_read_url(image) or ""

    return {
        "id": image.id,
        "url": display_url,
        "description": image.description or "",
        "tags": [t.name for t in image.tags if t.level == 2],
        "width": image.width,
        "height": image.height,
        "created_at": image.created_at.isoformat() if image.created_at else None,
    }


async def _tool_add_image(
    arguments: dict,
    session: AsyncSession,
    api_user: dict | None,
) -> dict:
    """从 URL 添加图片（写工具，注册表已校验 UPLOAD_IMAGE 权限）"""
    api_user = api_user or {}

    image_url = arguments.get("image_url")
    if not image_url:
        raise ValueError("image_url is required")

    tags = arguments.get("tags", [])
    description = arguments.get("description", "")
    category_id = arguments.get("category_id")  # 主分类 ID
    auto_analyze = arguments.get("auto_analyze", True)
    is_public = arguments.get("is_public", True)  # 是否公开

    # 权限校验需在上传/落库前完成，避免产生副作用
    has_valid_tags = bool([t for t in tags if t and str(t).strip()])
    has_valid_desc = bool(description and str(description).strip())
    need_analysis = auto_analyze and not (has_valid_tags and has_valid_desc)
    if need_analysis and not check_permission(api_user, Permission.AI_ANALYZE):
        raise ValueError(permission_denied_detail(Permission.AI_ANALYZE))

    if tags:
        normalized_tags = [t.strip() for t in tags if t and str(t).strip()]
        name_levels = await tag_repository.get_name_levels(session, normalized_tags)
        reserved = [name for name, level in name_levels.items() if level in (0, 1)]
        if reserved:
            preview = ", ".join(reserved[:10])
            suffix = "..." if len(reserved) > 10 else ""
            raise ValueError(f"标签名已被主分类/分辨率占用，不能作为普通标签使用: {preview}{suffix}")

        missing = [name for name in sorted(set(normalized_tags)) if name not in name_levels]
        if missing and not check_permission(api_user, Permission.CREATE_TAGS):
            raise ValueError(
                permission_denied_with_missing_detail(
                    Permission.CREATE_TAGS,
                    missing,
                    item_label="标签",
                )
            )

    # 下载并保存图片
    file_path, local_url, content = await upload_service.save_remote_image(image_url)
    file_hash = hashlib.md5(content).hexdigest()
    file_size = round(len(content) / (1024 * 1024), 2)
    width, height = upload_service.extract_image_dimensions(content)
    file_type = file_path.split(".")[-1] if "." in file_path else "jpg"

    # 创建图片记录
    new_image = await image_repository.create_image(
        session,
        file_hash=file_hash,
        file_type=file_type,
        file_size=file_size,
        width=width,
        height=height,
        description=description,
        original_url=image_url,
        embedding=None,
        uploaded_by=api_user.get("id"),
        is_public=is_public,
    )

    # 保存到本地存储
    object_key = storage_service.generate_object_key(file_hash, file_type)
    default_endpoint, _ = await storage_endpoint_repository.resolve_upload_endpoint(session, None)
    if default_endpoint:
        full_key = storage_service.get_full_object_key(object_key, None)
        await storage_service.upload_to_endpoint(content, full_key, default_endpoint)

        await image_location_repository.create(
            session,
            image_id=new_image.id,
            endpoint_id=default_endpoint.id,
            object_key=full_key,
            is_primary=True,
            sync_status="synced",
            synced_at=datetime.now(timezone.utc),
        )

    # 设置标签
    if tags:
        await image_tag_repository.set_image_tags(
            session, new_image.id, tags, source="user"
        )

    # 设置主分类标签
    if category_id:
        await image_tag_repository.add_tag_to_image(
            session, new_image.id, category_id, source="user", sort_order=0
        )

    await session.commit()

    # 判断是否需要 AI 分析
    if need_analysis:
        await task_queue.add_tasks([new_image.id])
        status = "已加入 AI 分析队列"
    else:
        status = "已保存（跳过 AI 分析）"

    return {
        "id": new_image.id,
        "status": status,
        "width": width,
        "height": height,
        "tags": tags,
        "auto_analyze": need_analysis,
    }


# ============================================================
# Tool 注册表
# ============================================================

@dataclass(frozen=True)
class McpToolDef:
    """MCP 工具定义：schema + 只读标记 + 所需权限 + 执行函数"""
    name: str
    description: str
    input_schema: dict
    readonly: bool
    handler: Callable[[dict, AsyncSession, Optional[dict]], Awaitable[dict]]
    required_permission: Permission | None = None


_TOOL_DEFS = [
    McpToolDef(
        name="search_images",
        description=(
            "图库检索。不传任何条件时随机抽取；传 tags 按标签筛选（AND 关系，所有模式硬过滤）；"
            "传 keyword 按关键词搜索：match=semantic 走语义向量搜索、fuzzy 走描述/标签名模糊匹配、"
            "auto 优先语义失败自动降级。sort=latest 时按最新排序且支持 page 分页浏览；"
            "random/relevance 不支持分页。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词。不传时进入随机抽取模式"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签名筛选列表（AND 关系，精确匹配标签名，所有模式下均为硬过滤）"
                },
                "match": {
                    "type": "string",
                    "enum": ["auto", "semantic", "fuzzy"],
                    "default": "auto",
                    "description": "keyword 匹配方式：semantic=语义向量搜索；fuzzy=描述/标签名子串模糊匹配；auto=优先语义、不可用时降级模糊。仅 keyword 存在时生效"
                },
                "sort": {
                    "type": "string",
                    "enum": ["auto", "random", "latest", "relevance"],
                    "default": "auto",
                    "description": "排序方式：auto=有 keyword 按相关度、无 keyword 随机；latest=按最新排序（唯一支持 page 分页）；random 仅在无 keyword 时有效"
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                    "description": "返回数量（latest 模式下为每页数量）"
                },
                "page": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1,
                    "description": "页码，仅 sort=latest 时生效"
                }
            }
        },
        readonly=True,
        handler=_tool_search_images,
    ),
    McpToolDef(
        name="get_image_detail",
        description="获取指定图片的详细信息，包括描述、标签、尺寸等。",
        input_schema={
            "type": "object",
            "properties": {
                "image_id": {
                    "type": "integer",
                    "description": "图片 ID"
                }
            },
            "required": ["image_id"]
        },
        readonly=True,
        handler=_tool_get_image_detail,
    ),
    McpToolDef(
        name="add_image",
        description="从 URL 添加图片到图库，可选择是否进行 AI 自动分析生成标签和描述。",
        input_schema={
            "type": "object",
            "properties": {
                "image_url": {
                    "type": "string",
                    "description": "图片 URL（必须可公网访问）"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "用户自定义标签列表"
                },
                "description": {
                    "type": "string",
                    "description": "图片描述（若同时提供 tags 和 description 则跳过 AI 分析）"
                },
                "category_id": {
                    "type": "integer",
                    "description": "主分类 ID（level=0 的标签 ID）"
                },
                "auto_analyze": {
                    "type": "boolean",
                    "default": True,
                    "description": "是否启用 AI 视觉分析"
                },
                "is_public": {
                    "type": "boolean",
                    "default": True,
                    "description": "是否公开可见"
                }
            },
            "required": ["image_url"]
        },
        readonly=False,
        handler=_tool_add_image,
        required_permission=Permission.UPLOAD_IMAGE,
    ),
]

TOOL_REGISTRY: dict[str, McpToolDef] = {t.name: t for t in _TOOL_DEFS}


def list_tools_for(scope: str, api_user: dict | None) -> list[dict]:
    """按端点作用域与用户权限过滤可见工具列表"""
    tools = []
    for tool in TOOL_REGISTRY.values():
        if scope == SCOPE_READONLY and not tool.readonly:
            continue
        if tool.required_permission and not check_permission(
            api_user or {}, tool.required_permission
        ):
            continue
        tools.append({
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        })
    return tools


async def execute_tool(
    name: str,
    arguments: dict,
    session: AsyncSession,
    api_user: dict | None,
    scope: str,
) -> dict:
    """执行 Tool 调用。

    tools/list 只是提示，此处的 scope / 权限校验才是真正边界
    （客户端可以直接调用未列出的工具名）。
    """
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        raise ValueError(f"Unknown tool: {name}")
    if scope == SCOPE_READONLY and not tool.readonly:
        raise ValueError(f"当前为公共只读端点，工具 {name} 不可用")
    if tool.required_permission and not check_permission(
        api_user or {}, tool.required_permission
    ):
        raise ValueError(permission_denied_detail(tool.required_permission))
    return await tool.handler(arguments, session, api_user)


# ============================================================
# JSON-RPC 请求/响应模型
# ============================================================

class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 请求"""
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict | None = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 响应"""
    jsonrpc: str = "2.0"
    id: int | str | None = None
    result: Any = None
    error: dict | None = None


# ============================================================
# SSE 连接管理
# ============================================================

class MCPConnection:
    """MCP 连接状态"""

    def __init__(self, session_id: str, api_user: dict | None, scope: str):
        self.session_id = session_id
        self.api_user = api_user  # None = 匿名（仅公共只读端点允许）
        self.scope = scope
        self.initialized = False
        self.message_queue: asyncio.Queue = asyncio.Queue()

    async def send(self, data: dict):
        """发送消息到队列"""
        await self.message_queue.put(data)

    async def receive(self) -> dict:
        """从队列接收消息"""
        return await self.message_queue.get()


# 活跃连接存储
_connections: dict[str, MCPConnection] = {}


def _anonymous_connection_count() -> int:
    """当前匿名连接数"""
    return sum(1 for c in _connections.values() if c.api_user is None)


# ============================================================
# JSON-RPC 消息处理
# ============================================================

async def process_jsonrpc(
    request: JsonRpcRequest,
    *,
    scope: str,
    api_user: dict | None,
    session: AsyncSession,
) -> JsonRpcResponse | None:
    """处理 JSON-RPC 消息（与传输方式无关，SSE 与 Streamable HTTP 共用）

    Returns:
        JsonRpcResponse，或 None（通知消息不需要响应）。
    """

    method = request.method
    params = request.params or {}

    try:
        if method == "initialize":
            # 初始化握手：协商协议版本
            requested_version = str(params.get("protocolVersion") or "")
            negotiated = (
                requested_version
                if requested_version in SUPPORTED_PROTOCOL_VERSIONS
                else DEFAULT_PROTOCOL_VERSION
            )
            result = {
                "protocolVersion": negotiated,
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            }
            if scope == SCOPE_READONLY:
                result["instructions"] = (
                    "此端点为公共只读端点，仅提供图库检索与图片详情查询。"
                    "未携带 API Key 时仅能访问公开图片；携带有效 API Key 后"
                    "可额外访问本人上传的图片，但工具仍保持只读。"
                )
            return JsonRpcResponse(id=request.id, result=result)

        elif method.startswith("notifications/"):
            # 通知类消息（initialized/cancelled 等）按 JSON-RPC 规范不回复
            return None

        elif method == "tools/list":
            # 返回可用 Tools 列表（按作用域与权限过滤）
            return JsonRpcResponse(
                id=request.id,
                result={"tools": list_tools_for(scope, api_user)}
            )

        elif method == "tools/call":
            # 执行 Tool 调用
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            try:
                result = await execute_tool(
                    tool_name, arguments, session, api_user, scope,
                )
                return JsonRpcResponse(
                    id=request.id,
                    result={
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, ensure_ascii=False, indent=2)
                            }
                        ]
                    }
                )
            except Exception as e:
                logger.error(f"[MCP] Tool 执行失败: {tool_name}, error={e}")
                return JsonRpcResponse(
                    id=request.id,
                    result={
                        "content": [
                            {
                                "type": "text",
                                "text": f"Error: {str(e)}"
                            }
                        ],
                        "isError": True
                    }
                )

        elif method == "ping":
            return JsonRpcResponse(id=request.id, result={})

        else:
            # 未知方法
            return JsonRpcResponse(
                id=request.id,
                error={
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            )

    except Exception as e:
        logger.error(f"[MCP] 消息处理失败: {e}")
        return JsonRpcResponse(
            id=request.id,
            error={
                "code": -32603,
                "message": str(e)
            }
        )


async def handle_message(
    request: JsonRpcRequest,
    connection: MCPConnection,
    session: AsyncSession
) -> JsonRpcResponse | None:
    """处理旧版 SSE 传输的 JSON-RPC 消息（基于连接状态的薄封装）"""
    response = await process_jsonrpc(
        request,
        scope=connection.scope,
        api_user=connection.api_user,
        session=session,
    )
    if request.method == "initialize":
        connection.initialized = True
    return response


# ============================================================
# Streamable HTTP 端点（现行标准传输）
# ============================================================
#
# 单端点纯请求-响应模式：每个 POST 独立认证、独立处理，服务端不持有任何
# 连接状态（不分配 Mcp-Session-Id，规范允许无会话服务器）。
# 本服务无服务端主动消息，因此不提供 GET 监听流（GET 自动返回 405，
# 这同时是规范定义的新旧传输探测信号）。


async def _handle_streamable_post(
    request: Request,
    api_user: dict | None,
    scope: str,
    session: AsyncSession,
) -> Response:
    """Streamable HTTP 消息处理（full / public 共用）"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            },
        )

    if isinstance(body, list):
        # JSON-RPC 批量请求已于 2025-06-18 版规范移除，不支持
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Batch requests are not supported"},
            },
        )

    try:
        rpc_request = JsonRpcRequest(**body)
    except (ValidationError, TypeError):
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request"},
            },
        )

    logger.debug(f"[MCP] Streamable 消息: method={rpc_request.method}, scope={scope}")

    response = await process_jsonrpc(
        rpc_request, scope=scope, api_user=api_user, session=session
    )

    if response is None:
        # 通知类消息：202 Accepted 无响应体
        return Response(status_code=202)

    return JSONResponse(content=response.model_dump(exclude_none=True))


@router.post("")
async def mcp_streamable_endpoint(
    request: Request,
    api_user: dict = Depends(require_api_key),
    session: AsyncSession = Depends(get_async_session),
):
    """MCP Streamable HTTP 端点（全功能）- 强制 API Key"""
    return await _handle_streamable_post(request, api_user, SCOPE_FULL, session)


@router.post("/public")
async def mcp_public_streamable_endpoint(
    request: Request,
    api_user: dict | None = Depends(verify_api_key),
    session: AsyncSession = Depends(get_async_session),
):
    """MCP Streamable HTTP 端点（公共只读）- 允许匿名

    匿名仅可见 public 图片；携带有效 API Key 可见 public + 本人上传，
    但工具始终只读（作用域由 URL 决定）。
    """
    return await _handle_streamable_post(request, api_user, SCOPE_READONLY, session)


# ============================================================
# HTTP+SSE 端点（2024-11-05 旧协议，已弃用，保留给旧客户端）
# ============================================================

def _create_sse_response(
    request: Request,
    connection: MCPConnection,
    message_path: str,
) -> StreamingResponse:
    """构建 SSE 流响应（full / public 共用）"""

    async def event_stream():
        try:
            # 发送 endpoint 事件，告知客户端消息端点
            endpoint_url = f"{message_path}?session_id={connection.session_id}"
            yield f"event: endpoint\ndata: {endpoint_url}\n\n"

            # 保持连接并发送消息
            while True:
                if await request.is_disconnected():
                    break

                try:
                    # 等待消息（带超时避免阻塞）
                    message = await asyncio.wait_for(
                        connection.receive(),
                        timeout=30.0
                    )
                    yield f"event: message\ndata: {json.dumps(message, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # 发送心跳
                    yield ": heartbeat\n\n"
        finally:
            # 清理连接
            _connections.pop(connection.session_id, None)
            logger.info(f"[MCP] 连接关闭: session={connection.session_id}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


async def _dispatch_message(
    request: Request,
    session_id: str,
    session: AsyncSession,
) -> dict:
    """message 端点共用逻辑：查连接、解析并处理 JSON-RPC 消息"""
    connection = _connections.get(session_id)
    if not connection:
        return {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Session not found"}}

    body = await request.json()
    rpc_request = JsonRpcRequest(**body)

    logger.debug(f"[MCP] 收到消息: method={rpc_request.method}, session={session_id}")

    response = await handle_message(rpc_request, connection, session)

    if response:
        # 通过 SSE 发送响应
        await connection.send(response.model_dump(exclude_none=True))

    return {"status": "ok"}


@router.get("/sse")
async def mcp_sse_endpoint(
    request: Request,
    api_user: dict = Depends(require_api_key),
):
    """MCP SSE 端点（全功能）- 强制 API Key

    创建 SSE 连接，返回 session_id 用于后续消息发送。
    """
    session_id = str(uuid.uuid4())
    connection = MCPConnection(session_id, api_user, SCOPE_FULL)
    _connections[session_id] = connection

    logger.info(f"[MCP] 新连接(full): session={session_id}, user={api_user.get('username')}")

    return _create_sse_response(request, connection, "/api/v1/mcp/message")


@router.post("/message")
async def mcp_message_endpoint(
    request: Request,
    session_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """MCP 消息端点（全功能）- 接收客户端 JSON-RPC 消息

    认证通过 session_id 关联的连接获取，无需重复传递 API Key。
    """
    return await _dispatch_message(request, session_id, session)


@router.get("/public/sse")
async def mcp_public_sse_endpoint(
    request: Request,
    api_user: dict | None = Depends(verify_api_key),
):
    """MCP SSE 端点（公共只读）- 允许匿名访问

    仅暴露只读工具；即使携带有效 API Key 也保持只读（作用域由 URL 决定）。
    匿名连接数超过上限时返回 429。
    """
    if api_user is None and _anonymous_connection_count() >= MAX_ANONYMOUS_CONNECTIONS:
        raise HTTPException(status_code=429, detail="匿名连接数已达上限，请稍后重试")

    session_id = str(uuid.uuid4())
    connection = MCPConnection(session_id, api_user, SCOPE_READONLY)
    _connections[session_id] = connection

    username = api_user.get("username") if api_user else "anonymous"
    logger.info(f"[MCP] 新连接(public): session={session_id}, user={username}")

    return _create_sse_response(request, connection, "/api/v1/mcp/public/message")


@router.post("/public/message")
async def mcp_public_message_endpoint(
    request: Request,
    session_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """MCP 消息端点（公共只读）- 接收客户端 JSON-RPC 消息"""
    return await _dispatch_message(request, session_id, session)
