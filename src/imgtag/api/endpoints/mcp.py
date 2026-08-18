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
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Annotated, Any, Awaitable, Callable, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.dependencies import (
    extract_mcp_api_key,
    get_user_by_api_key,
    require_mcp_api_key,
    verify_mcp_api_key,
)
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
MAX_AUTHENTICATED_CONNECTIONS = 100
MAX_CONNECTIONS_PER_USER = 5
MCP_SESSION_TTL_SECONDS = 3600

# Streamable HTTP / SSE message 端点的基础保护。限流是进程级的；多实例部署
# 时仍应在网关配置全局限流，但服务端本身不能因缺少网关而完全裸奔。
MCP_RATE_LIMIT_WINDOW_SECONDS = 60.0
MCP_RATE_LIMIT_ANONYMOUS = 60
MCP_RATE_LIMIT_AUTHENTICATED = 300
MCP_MAX_REQUEST_BYTES = 1_048_576

# search_images 参数枚举
_MATCH_VALUES = {"auto", "semantic", "fuzzy"}
_SORT_VALUES = {"auto", "random", "latest", "relevance"}


class MCPUserError(ValueError):
    """可安全返回给 MCP 客户端的业务错误。"""


class MCPRequestTooLarge(ValueError):
    """请求体超过 MCP 传输边界。"""


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
        raise MCPUserError("count 和 page 必须为整数")
    if not 1 <= count <= 50:
        raise MCPUserError("count 必须在 1 到 50 之间")
    if not 1 <= page <= 10_000:
        raise MCPUserError("page 必须在 1 到 10000 之间")

    if match not in _MATCH_VALUES:
        raise MCPUserError(f"match 参数无效: {match}，可选 auto/semantic/fuzzy")
    if sort not in _SORT_VALUES:
        raise MCPUserError(f"sort 参数无效: {sort}，可选 auto/random/latest/relevance")

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
                raise MCPUserError("语义搜索暂不可用，请稍后重试") from e
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
        raise MCPUserError("image_id is required")

    image = await image_repository.get_with_tags(session, int(image_id))

    is_admin = bool(api_user and api_user.get("role") == "admin")
    is_owner = bool(
        api_user and image is not None and image.uploaded_by == api_user.get("id")
    )
    # 私有图对无权者与不存在返回一致错误，避免泄露图片存在性
    if image is None or (not image.is_public and not is_admin and not is_owner):
        raise MCPUserError("Image not found")

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
        raise MCPUserError("image_url is required")

    tags = arguments.get("tags", [])
    description = arguments.get("description", "")
    category_id = arguments.get("category_id")  # 主分类 ID
    auto_analyze = arguments.get("auto_analyze", True)
    is_public = arguments.get("is_public", True)  # 是否公开
    idempotency_key = (
        arguments.get("idempotency_key")
        or arguments.get("_mcp_request_id")
    )
    if idempotency_key:
        idempotency_key = str(idempotency_key)[:128]

    async def existing_result(image) -> dict:
        """返回幂等重试的既有记录，不重复下载、落库或入队。"""
        image_with_tags = await image_repository.get_with_tags(session, image.id)
        if image_with_tags is None:
            raise MCPUserError("幂等记录暂不可用，请稍后重试")
        display_url = await storage_service.get_read_url(image_with_tags) or ""
        return {
            "id": image_with_tags.id,
            "status": "已存在（幂等重试）",
            "url": display_url,
            "width": image_with_tags.width,
            "height": image_with_tags.height,
            "tags": [t.name for t in image_with_tags.tags if t.level == 2],
            "auto_analyze": False,
        }

    # JSON-RPC request id 由服务端自动作为默认幂等键；客户端也可显式提供
    # idempotency_key，以便跨请求重试时继续复用同一写入语义。
    uploaded_by = api_user.get("id")
    if idempotency_key and uploaded_by:
        existing = await image_repository.get_by_mcp_idempotency_key(
            session, uploaded_by, idempotency_key
        )
        if existing is not None:
            return await existing_result(existing)

    # 权限校验需在上传/落库前完成，避免产生副作用
    has_valid_tags = bool([t for t in tags if t and str(t).strip()])
    has_valid_desc = bool(description and str(description).strip())
    need_analysis = auto_analyze and not (has_valid_tags and has_valid_desc)
    if need_analysis and not check_permission(api_user, Permission.AI_ANALYZE):
        raise MCPUserError(permission_denied_detail(Permission.AI_ANALYZE))

    if tags:
        normalized_tags = [t.strip() for t in tags if t and str(t).strip()]
        name_levels = await tag_repository.get_name_levels(session, normalized_tags)
        reserved = [name for name, level in name_levels.items() if level in (0, 1)]
        if reserved:
            preview = ", ".join(reserved[:10])
            suffix = "..." if len(reserved) > 10 else ""
            raise MCPUserError(
                f"标签名已被主分类/分辨率占用，不能作为普通标签使用: {preview}{suffix}"
            )

        missing = [name for name in sorted(set(normalized_tags)) if name not in name_levels]
        if missing and not check_permission(api_user, Permission.CREATE_TAGS):
            raise MCPUserError(
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
        mcp_idempotency_key=idempotency_key,
    )

    # 保存到默认存储。没有可用端点或上传失败时不得提交一个无法访问的图片记录。
    object_key = storage_service.generate_object_key(file_hash, file_type)
    default_endpoint, _ = await storage_endpoint_repository.resolve_upload_endpoint(session, None)
    if default_endpoint is None:
        await upload_service.delete_temp_file(file_path)
        raise MCPUserError("未配置默认存储端点，无法保存图片")

    full_key = storage_service.get_full_object_key(object_key, None)
    uploaded = await storage_service.upload_to_endpoint(
        content, full_key, default_endpoint
    )
    if not uploaded:
        await upload_service.delete_temp_file(file_path)
        raise MCPUserError("图片存储失败，请稍后重试")

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

    try:
        # 判断是否需要 AI 分析。与图片、存储位置共享同一事务；入队失败时
        # 不会留下半成品图片记录。
        if need_analysis:
            await task_queue.add_tasks([new_image.id], session=session)
            status = "已加入 AI 分析队列"
        else:
            status = "已保存（跳过 AI 分析）"
        await session.commit()
    except IntegrityError:
        await upload_service.delete_temp_file(file_path)
        await session.rollback()
        if idempotency_key and uploaded_by:
            existing = await image_repository.get_by_mcp_idempotency_key(
                session, uploaded_by, idempotency_key
            )
            if existing is not None:
                return await existing_result(existing)
        raise
    except Exception:
        await upload_service.delete_temp_file(file_path)
        raise

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

_TagArgument = Annotated[StrictStr, Field(min_length=1, max_length=100)]


class _MCPArguments(BaseModel):
    """工具参数基类：类型严格，忽略客户端不认识的扩展字段。"""

    model_config = ConfigDict(extra="ignore")


class SearchImagesArguments(_MCPArguments):
    keyword: StrictStr | None = Field(default=None, max_length=500)
    tags: list[_TagArgument] = Field(default_factory=list, max_length=50)
    match: Literal["auto", "semantic", "fuzzy"] = "auto"
    sort: Literal["auto", "random", "latest", "relevance"] = "auto"
    count: StrictInt = Field(default=10, ge=1, le=50)
    page: StrictInt = Field(default=1, ge=1, le=10_000)


class GetImageDetailArguments(_MCPArguments):
    image_id: StrictInt = Field(..., ge=1)


class AddImageArguments(_MCPArguments):
    image_url: StrictStr = Field(..., min_length=1, max_length=2048)
    tags: list[_TagArgument] = Field(default_factory=list, max_length=50)
    description: StrictStr = Field(default="", max_length=10_000)
    category_id: StrictInt | None = Field(default=None, ge=1)
    auto_analyze: StrictBool = True
    is_public: StrictBool = True
    idempotency_key: StrictStr | None = Field(
        default=None, min_length=1, max_length=128
    )

@dataclass(frozen=True)
class McpToolDef:
    """MCP 工具定义：schema + 只读标记 + 所需权限 + 执行函数"""
    name: str
    description: str
    input_schema: dict
    readonly: bool
    handler: Callable[[dict, AsyncSession, Optional[dict]], Awaitable[dict]]
    input_model: type[BaseModel] | None = None
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
                    "maxLength": 500,
                    "description": "搜索关键词。不传时进入随机抽取模式"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 100},
                    "maxItems": 50,
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
                    "maximum": 10000,
                    "default": 1,
                    "description": "页码，仅 sort=latest 时生效"
                }
            }
        },
        readonly=True,
        handler=_tool_search_images,
        input_model=SearchImagesArguments,
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
        input_model=GetImageDetailArguments,
    ),
    McpToolDef(
        name="add_image",
        description="从 URL 添加图片到图库，可选择是否进行 AI 自动分析生成标签和描述。",
        input_schema={
            "type": "object",
            "properties": {
                "image_url": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 2048,
                    "description": "图片 URL（必须可公网访问）"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 100},
                    "maxItems": 50,
                    "description": "用户自定义标签列表"
                },
                "description": {
                    "type": "string",
                    "maxLength": 10000,
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
                },
                "idempotency_key": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "description": "跨请求重试时复用的幂等键"
                }
            },
            "required": ["image_url"]
        },
        readonly=False,
        handler=_tool_add_image,
        input_model=AddImageArguments,
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
        raise MCPUserError(f"Unknown tool: {name}")
    if scope == SCOPE_READONLY and not tool.readonly:
        raise MCPUserError(f"当前为公共只读端点，工具 {name} 不可用")
    if tool.required_permission and not check_permission(
        api_user or {}, tool.required_permission
    ):
        raise MCPUserError(permission_denied_detail(tool.required_permission))

    if tool.input_model is not None:
        try:
            validated = tool.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise MCPUserError("工具参数校验失败，请检查输入") from exc
        validated_arguments = validated.model_dump(exclude_none=True)
        # 该字段只由服务端注入，用于以 JSON-RPC request id 作为默认幂等键；
        # 不让它出现在公开 inputSchema 中，也不接受客户端伪造的内部字段。
        if name == "add_image" and arguments.get("_mcp_request_id"):
            validated_arguments["_mcp_request_id"] = arguments["_mcp_request_id"]
        arguments = validated_arguments

    return await tool.handler(arguments, session, api_user)


# ============================================================
# JSON-RPC 请求/响应模型
# ============================================================

class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 请求"""
    jsonrpc: Literal["2.0"]
    id: StrictInt | StrictStr | None = None
    method: StrictStr
    params: dict[str, Any] | None = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 响应"""
    jsonrpc: Literal["2.0"] = "2.0"
    id: StrictInt | StrictStr | None = None
    result: Any = None
    error: dict | None = None


class MCPProtocolError(ValueError):
    """需要通过 JSON-RPC 顶层 error 返回的协议错误。"""

    def __init__(self, message: str, *, code: int = -32602):
        super().__init__(message)
        self.code = code
        self.message = message


def _protocol_error_response(
    request_id: StrictInt | StrictStr | None,
    error: MCPProtocolError,
) -> JsonRpcResponse:
    """构造 JSON-RPC 顶层协议错误响应。"""
    return JsonRpcResponse(
        id=request_id,
        error={"code": error.code, "message": error.message},
    )


def _parse_tool_call_params(
    params: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    """校验 tools/call 的协议参数。

    工具名和 arguments 的容器类型属于 CallToolRequest 协议的一部分；
    参数值本身交由具体工具处理，并以 CallToolResult.isError 返回业务错误。
    """
    if params is None:
        raise MCPProtocolError("Invalid params: tools/call requires an object")

    tool_name = params.get("name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise MCPProtocolError("Invalid params: tools/call requires a non-empty name")

    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        raise MCPProtocolError("Invalid params: arguments must be an object")

    return tool_name, arguments


def _tool_success_result(result: Any) -> dict[str, Any]:
    """构造标准 CallToolResult，同时保留文本兼容层。"""
    tool_result: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False, indent=2),
            }
        ],
        "isError": False,
    }
    # 当前所有内置工具均返回 object。仅在结果满足 MCP structuredContent
    # 的 object 要求时输出，避免将未来的数组/标量结果伪装成结构化对象。
    if isinstance(result, dict):
        tool_result["structuredContent"] = result
    return tool_result


def _tool_error_result(error: Exception) -> dict[str, Any]:
    """构造工具执行错误（与 JSON-RPC 协议错误区分）。"""
    message = str(error) if isinstance(error, MCPUserError) else "工具执行失败，请稍后重试"
    return {
        "content": [
            {
                "type": "text",
                "text": f"Error: {message}",
            }
        ],
        "isError": True,
    }


def _parse_rpc_request(body: Any) -> JsonRpcRequest:
    """解析并校验 JSON-RPC 2.0 请求及 MCP 的请求/通知 ID 规则。"""
    try:
        request = JsonRpcRequest.model_validate(body)
    except (ValidationError, TypeError) as exc:
        raise MCPProtocolError("Invalid Request", code=-32600) from exc

    is_notification = request.method.startswith("notifications/")
    if is_notification and request.id is not None:
        raise MCPProtocolError(
            "Invalid Request: notifications must not include an id",
            code=-32600,
        )
    if not is_notification and request.id is None:
        raise MCPProtocolError(
            "Invalid Request: requests must include a string or integer id",
            code=-32600,
        )
    return request


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
        self.last_activity = monotonic()

    async def send(self, data: dict):
        """发送消息到队列"""
        self.touch()
        await self.message_queue.put(data)

    async def receive(self) -> dict:
        """从队列接收消息"""
        self.touch()
        return await self.message_queue.get()

    def touch(self) -> None:
        self.last_activity = monotonic()

    def is_expired(self) -> bool:
        return monotonic() - self.last_activity > MCP_SESSION_TTL_SECONDS


# 活跃连接存储
_connections: dict[str, MCPConnection] = {}
_mcp_rate_windows: dict[str, deque[float]] = {}


def _anonymous_connection_count() -> int:
    """当前匿名连接数"""
    return sum(1 for c in _connections.values() if c.api_user is None)


def _purge_expired_connections() -> None:
    """清理闲置 SSE 会话，防止 session_id 永久有效。"""
    expired = [sid for sid, connection in _connections.items() if connection.is_expired()]
    for sid in expired:
        _connections.pop(sid, None)
        logger.info("[MCP] 会话过期清理: session=%s", sid)


def _connection_user_key(api_user: dict | None) -> str | None:
    if not api_user:
        return None
    return str(api_user.get("id") or api_user.get("username") or "unknown")


def _authenticated_connection_count() -> int:
    return sum(1 for c in _connections.values() if c.api_user is not None)


def _user_connection_count(api_user: dict | None) -> int:
    user_key = _connection_user_key(api_user)
    if user_key is None:
        return 0
    return sum(
        1 for c in _connections.values()
        if _connection_user_key(c.api_user) == user_key
    )


def _check_connection_limit(api_user: dict | None) -> None:
    _purge_expired_connections()
    if api_user is None:
        if _anonymous_connection_count() >= MAX_ANONYMOUS_CONNECTIONS:
            raise HTTPException(status_code=429, detail="匿名连接数已达上限，请稍后重试")
        return
    if _authenticated_connection_count() >= MAX_AUTHENTICATED_CONNECTIONS:
        raise HTTPException(status_code=429, detail="认证连接数已达上限，请稍后重试")
    if _user_connection_count(api_user) >= MAX_CONNECTIONS_PER_USER:
        raise HTTPException(status_code=429, detail="当前用户连接数已达上限，请复用已有连接")


def _rate_limit_key(request: Request, api_user: dict | None) -> str:
    if api_user and api_user.get("id") is not None:
        return f"user:{api_user['id']}"
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) or "unknown"
    return f"ip:{host}"


def _check_rate_limit(request: Request, api_user: dict | None) -> None:
    """进程级滑动窗口限流，避免公共 MCP 被单一调用方打穿。"""
    now = monotonic()
    key = _rate_limit_key(request, api_user)
    window = _mcp_rate_windows.setdefault(key, deque())
    cutoff = now - MCP_RATE_LIMIT_WINDOW_SECONDS
    while window and window[0] <= cutoff:
        window.popleft()
    limit = MCP_RATE_LIMIT_AUTHENTICATED if api_user else MCP_RATE_LIMIT_ANONYMOUS
    if len(window) >= limit:
        raise HTTPException(
            status_code=429,
            detail="MCP 请求过于频繁，请稍后重试",
            headers={
                "Retry-After": str(max(1, int(MCP_RATE_LIMIT_WINDOW_SECONDS)))
            },
        )
    window.append(now)
    # 防止攻击者通过伪造大量来源地址让限流字典无界增长。
    if len(_mcp_rate_windows) > 10_000:
        for stale_key in list(_mcp_rate_windows)[:1_000]:
            _mcp_rate_windows.pop(stale_key, None)


def _request_content_length(request: Request) -> int | None:
    headers = getattr(request, "headers", None)
    raw = headers.get("content-length") if headers is not None else None
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise MCPRequestTooLarge("invalid content length")


async def _read_mcp_json(request: Request) -> Any:
    """读取有限大小的单个 JSON-RPC 请求。"""
    content_length = _request_content_length(request)
    if content_length is not None and content_length > MCP_MAX_REQUEST_BYTES:
        raise MCPRequestTooLarge("MCP request body is too large")

    # 测试桩/旧调用方可能只实现 json()；真实 Request 优先读取原始字节，
    # 这样可以在 JSON 解码前强制限制大小。
    if hasattr(request, "body"):
        raw = await request.body()
        if len(raw) > MCP_MAX_REQUEST_BYTES:
            raise MCPRequestTooLarge("MCP request body is too large")
        return json.loads(raw)
    return await request.json()


def _validate_protocol_version_header(request: Request) -> None:
    version = getattr(request, "headers", {}).get("mcp-protocol-version")
    if version and version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise MCPProtocolError("Unsupported MCP-Protocol-Version", code=-32602)


def _response_protocol_version(request: Request, rpc_request: "JsonRpcRequest") -> str:
    """确定响应中的 MCP-Protocol-Version，保持握手与后续请求一致。"""
    header_version = getattr(request, "headers", {}).get("mcp-protocol-version")
    if header_version in SUPPORTED_PROTOCOL_VERSIONS:
        return header_version
    if rpc_request.method == "initialize":
        requested = (rpc_request.params or {}).get("protocolVersion")
        if requested in SUPPORTED_PROTOCOL_VERSIONS:
            return requested
    return DEFAULT_PROTOCOL_VERSION


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
            try:
                tool_name, arguments = _parse_tool_call_params(request.params)
            except MCPProtocolError as error:
                return _protocol_error_response(request.id, error)

            # 未知工具属于协议错误，不是工具执行错误。
            if tool_name not in TOOL_REGISTRY:
                return _protocol_error_response(
                    request.id,
                    MCPProtocolError(f"Unknown tool: {tool_name}"),
                )

            try:
                # 对写工具默认启用 request-id 幂等，客户端可通过显式
                # idempotency_key 覆盖它以支持跨请求重试。
                if tool_name == "add_image" and request.id is not None:
                    arguments = dict(arguments)
                    fingerprint = hashlib.sha256(
                        json.dumps(
                            arguments,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()[:32]
                    request_token = hashlib.sha256(
                        str(request.id).encode("utf-8")
                    ).hexdigest()[:32]
                    arguments["_mcp_request_id"] = f"{request_token}:{fingerprint}"
                result = await execute_tool(
                    tool_name, arguments, session, api_user, scope,
                )
                return JsonRpcResponse(
                    id=request.id,
                    result=_tool_success_result(result),
                )
            except Exception as e:
                logger.error(f"[MCP] Tool 执行失败: {tool_name}", exc_info=True)
                if session is not None:
                    try:
                        await session.rollback()
                    except Exception:
                        logger.error("[MCP] 工具失败后的事务回滚失败", exc_info=True)
                return JsonRpcResponse(
                    id=request.id,
                    result=_tool_error_result(e),
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

    except Exception:
        logger.error("[MCP] 消息处理失败", exc_info=True)
        return JsonRpcResponse(
            id=request.id,
            error={
                "code": -32603,
                "message": "Internal server error",
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
    _check_rate_limit(request, api_user)
    try:
        body = await _read_mcp_json(request)
    except MCPRequestTooLarge:
        return JSONResponse(
            status_code=413,
            content={"error": "MCP request body is too large"},
        )
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
        rpc_request = _parse_rpc_request(body)
        _validate_protocol_version_header(request)
    except MCPProtocolError as error:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": error.code, "message": error.message},
            },
        )

    logger.debug(f"[MCP] Streamable 消息: method={rpc_request.method}, scope={scope}")

    response = await process_jsonrpc(
        rpc_request, scope=scope, api_user=api_user, session=session
    )

    if response is None:
        # 通知类消息：202 Accepted 无响应体
        return Response(
            status_code=202,
            headers={
                "MCP-Protocol-Version": _response_protocol_version(request, rpc_request)
            },
        )

    return JSONResponse(
        content=response.model_dump(exclude_none=True),
        headers={
            "MCP-Protocol-Version": _response_protocol_version(request, rpc_request)
        },
    )


@router.post("")
async def mcp_streamable_endpoint(
    request: Request,
    api_user: dict = Depends(require_mcp_api_key),
    session: AsyncSession = Depends(get_async_session),
):
    """MCP Streamable HTTP 端点（全功能）- 强制 API Key"""
    return await _handle_streamable_post(request, api_user, SCOPE_FULL, session)


@router.post("/public")
async def mcp_public_streamable_endpoint(
    request: Request,
    api_user: dict | None = Depends(verify_mcp_api_key),
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
                if connection.is_expired():
                    logger.info("[MCP] SSE 会话超时: session=%s", connection.session_id)
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
                    if connection.is_expired():
                        break
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
    _purge_expired_connections()
    connection = _connections.get(session_id)
    if not connection:
        return {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Session not found"}}
    if connection.is_expired():
        _connections.pop(session_id, None)
        return {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Session expired"}}

    # 旧 SSE 的 session_id 仍用于路由，但不再单独构成认证凭据。认证会话的
    # message 请求必须重新携带同一 API Key，泄露 session_id 也无法直接操作。
    if connection.api_user is not None:
        provided_key = extract_mcp_api_key(request)
        if not provided_key:
            raise HTTPException(status_code=401, detail="SSE message 请求需要 API Key 请求头")
        message_user = await get_user_by_api_key(session, provided_key)
        if message_user.get("id") != connection.api_user.get("id"):
            raise HTTPException(status_code=403, detail="SSE 会话与 API Key 不匹配")

    _check_rate_limit(request, connection.api_user)
    connection.touch()

    try:
        body = await _read_mcp_json(request)
    except MCPRequestTooLarge:
        await connection.send(
            JsonRpcResponse(
                id=None,
                error={"code": -32600, "message": "Request body is too large"},
            ).model_dump(exclude_none=True)
        )
        return {"status": "ok"}
    except Exception:
        # SSE 的 HTTP message 端点只负责确认入队；解析错误仍需通过
        # 连接对应的 SSE 响应通道返回 JSON-RPC error。
        await connection.send(
            JsonRpcResponse(
                id=None,
                error={"code": -32700, "message": "Parse error"},
            ).model_dump(exclude_none=True)
        )
        return {"status": "ok"}

    try:
        rpc_request = _parse_rpc_request(body)
        _validate_protocol_version_header(request)
    except MCPProtocolError as error:
        await connection.send(
            JsonRpcResponse(
                id=None,
                error={"code": error.code, "message": error.message},
            ).model_dump(exclude_none=True)
        )
        return {"status": "ok"}

    logger.debug(f"[MCP] 收到消息: method={rpc_request.method}, session={session_id}")

    response = await handle_message(rpc_request, connection, session)

    if response:
        # 通过 SSE 发送响应
        await connection.send(response.model_dump(exclude_none=True))

    return {"status": "ok"}


@router.get("/sse")
async def mcp_sse_endpoint(
    request: Request,
    api_user: dict = Depends(require_mcp_api_key),
):
    """MCP SSE 端点（全功能）- 强制 API Key

    创建 SSE 连接，返回 session_id 用于后续消息发送。
    """
    _check_connection_limit(api_user)
    _check_rate_limit(request, api_user)
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

    session_id 仅用于定位连接；认证会话仍需在每次 message 请求中重复
    携带同一 API Key 请求头。
    """
    return await _dispatch_message(request, session_id, session)


@router.get("/public/sse")
async def mcp_public_sse_endpoint(
    request: Request,
    api_user: dict | None = Depends(verify_mcp_api_key),
):
    """MCP SSE 端点（公共只读）- 允许匿名访问

    仅暴露只读工具；即使携带有效 API Key 也保持只读（作用域由 URL 决定）。
    匿名连接数超过上限时返回 429。
    """
    _check_connection_limit(api_user)
    _check_rate_limit(request, api_user)

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
