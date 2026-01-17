#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""MCP (Model Context Protocol) Server endpoints.

轻量级 MCP 实现，使用 SSE 传输，复用现有 API 逻辑。
支持 Claude Desktop / Cursor 等 MCP 客户端接入。
"""

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.dependencies import require_api_key
from imgtag.core.logging_config import get_logger
from imgtag.db import get_async_session
from imgtag.db.repositories import image_repository
from imgtag.services.storage_service import storage_service
from imgtag.services.upload_service import upload_service
from imgtag.services.task_queue import task_queue

logger = get_logger(__name__)

router = APIRouter()

# ============================================================
# MCP 协议常量
# ============================================================

MCP_VERSION = "2024-11-05"
SERVER_NAME = "imgtag-mcp"
SERVER_VERSION = "1.0.0"

# ============================================================
# Tools 定义
# ============================================================

TOOLS = [
    {
        "name": "search_images",
        "description": "搜索图库中的图片，支持关键词和标签筛选，返回分页结果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词，模糊匹配图片描述"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签筛选列表"
                },
                "page": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1,
                    "description": "页码"
                },
                "size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                    "description": "每页数量"
                }
            }
        }
    },
    {
        "name": "get_random_images",
        "description": "从图库中随机获取符合条件的图片，支持按标签筛选。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "标签筛选列表（AND 关系）"
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 1,
                    "description": "返回图片数量"
                }
            }
        }
    },
    {
        "name": "get_image_detail",
        "description": "获取指定图片的详细信息，包括描述、标签、尺寸等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_id": {
                    "type": "integer",
                    "description": "图片 ID"
                }
            },
            "required": ["image_id"]
        }
    },
    {
        "name": "add_image",
        "description": "从 URL 添加图片到图库，可选择是否进行 AI 自动分析生成标签和描述。",
        "inputSchema": {
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
        }
    }
]


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
    
    def __init__(self, session_id: str, api_user: dict):
        self.session_id = session_id
        self.api_user = api_user
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


# ============================================================
# Tool 执行逻辑
# ============================================================

async def execute_tool(
    name: str, 
    arguments: dict,
    session: AsyncSession
) -> dict:
    """执行 Tool 调用，复用现有 Repository 逻辑"""
    
    if name == "search_images":
        keyword = arguments.get("keyword")
        tags = arguments.get("tags", [])
        page = arguments.get("page", 1)
        size = min(arguments.get("size", 10), 50)
        offset = (page - 1) * size
        
        result = await image_repository.search_images(
            session,
            tags=tags if tags else None,
            keyword=keyword,
            limit=size,
            offset=offset,
        )
        
        images = result["images"]
        urls = await storage_service.get_read_urls(images)
        
        return {
            "images": [
                {
                    "id": img.id,
                    "url": urls.get(img.id, ""),
                    "description": img.description or "",
                    "tags": [t.name for t in img.tags] if hasattr(img, "tags") else [],
                }
                for img in images
            ],
            "total": result["total"],
            "page": page,
            "size": size
        }
    
    elif name == "get_random_images":
        tags = arguments.get("tags", [])
        count = min(arguments.get("count", 1), 20)
        
        result = await image_repository.get_random_by_tags(session, tags, count)
        
        return {
            "images": [
                {
                    "id": img["id"],
                    "url": img["image_url"],
                    "description": img["description"],
                    "tags": img["tags"],
                }
                for img in result
            ],
            "count": len(result)
        }
    
    elif name == "get_image_detail":
        image_id = arguments.get("image_id")
        if not image_id:
            raise ValueError("image_id is required")
        
        image = await image_repository.get_with_tags(session, image_id)
        if not image:
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
    
    elif name == "add_image":
        # 复用 external API 的逻辑
        from imgtag.api.endpoints.external import ExternalImageCreate
        
        image_url = arguments.get("image_url")
        if not image_url:
            raise ValueError("image_url is required")
        
        tags = arguments.get("tags", [])
        description = arguments.get("description", "")
        category_id = arguments.get("category_id")  # 主分类 ID
        auto_analyze = arguments.get("auto_analyze", True)
        is_public = arguments.get("is_public", True)  # 是否公开
        
        # 下载并保存图片
        import hashlib
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
            uploaded_by=None,
            is_public=is_public,
        )
        
        # 保存到本地存储
        object_key = storage_service.generate_object_key(file_hash, file_type)
        from imgtag.db.repositories import storage_endpoint_repository
        default_endpoint, _ = await storage_endpoint_repository.resolve_upload_endpoint(session, None)
        if default_endpoint:
            full_key = storage_service.get_full_object_key(object_key, None)
            await storage_service.upload_to_endpoint(content, full_key, default_endpoint)
            
            from imgtag.db.repositories import image_location_repository
            from datetime import datetime, timezone as tz
            await image_location_repository.create(
                session,
                image_id=new_image.id,
                endpoint_id=default_endpoint.id,
                object_key=full_key,
                is_primary=True,
                sync_status="synced",
                synced_at=datetime.now(tz.utc),
            )
        
        # 设置标签
        from imgtag.db.repositories import image_tag_repository
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
        has_valid_tags = bool([t for t in tags if t and t.strip()])
        has_valid_desc = bool(description and description.strip())
        need_analysis = auto_analyze and not (has_valid_tags and has_valid_desc)
        
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
    
    else:
        raise ValueError(f"Unknown tool: {name}")


# ============================================================
# JSON-RPC 消息处理
# ============================================================

async def handle_message(
    request: JsonRpcRequest,
    connection: MCPConnection,
    session: AsyncSession
) -> JsonRpcResponse:
    """处理 JSON-RPC 消息"""
    
    method = request.method
    params = request.params or {}
    
    try:
        if method == "initialize":
            # 初始化握手
            connection.initialized = True
            return JsonRpcResponse(
                id=request.id,
                result={
                    "protocolVersion": MCP_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    }
                }
            )
        
        elif method == "notifications/initialized":
            # 客户端确认初始化完成（无需响应）
            return None
        
        elif method == "tools/list":
            # 返回可用 Tools 列表
            return JsonRpcResponse(
                id=request.id,
                result={"tools": TOOLS}
            )
        
        elif method == "tools/call":
            # 执行 Tool 调用
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            try:
                result = await execute_tool(tool_name, arguments, session)
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


# ============================================================
# HTTP 端点
# ============================================================

@router.get("/sse")
async def mcp_sse_endpoint(
    request: Request,
    api_user: dict = Depends(require_api_key),
):
    """MCP SSE 端点 - Streamable HTTP 传输
    
    创建 SSE 连接，返回 session_id 用于后续消息发送。
    """
    session_id = str(uuid.uuid4())
    connection = MCPConnection(session_id, api_user)
    _connections[session_id] = connection
    
    logger.info(f"[MCP] 新连接: session={session_id}, user={api_user.get('username')}")
    
    async def event_stream():
        try:
            # 发送 endpoint 事件，告知客户端消息端点
            endpoint_url = f"/api/v1/mcp/message?session_id={session_id}"
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
            _connections.pop(session_id, None)
            logger.info(f"[MCP] 连接关闭: session={session_id}")
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/message")
async def mcp_message_endpoint(
    request: Request,
    session_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """MCP 消息端点 - 接收客户端 JSON-RPC 消息
    
    认证通过 session_id 关联的连接获取，无需重复传递 API Key。
    """
    
    connection = _connections.get(session_id)
    if not connection:
        return {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Session not found"}}
    
    # 解析请求体
    body = await request.json()
    rpc_request = JsonRpcRequest(**body)
    
    logger.debug(f"[MCP] 收到消息: method={rpc_request.method}, session={session_id}")
    
    # 处理消息
    response = await handle_message(rpc_request, connection, session)
    
    if response:
        # 通过 SSE 发送响应
        await connection.send(response.model_dump(exclude_none=True))
    
    return {"status": "ok"}

