#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""External API endpoints.

Third-party integration using API key authentication.
"""

import json
import time
from math import ceil
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from python_multipart.exceptions import MultipartParseError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.dependencies import require_api_key
from imgtag.api.permission_guards import ensure_create_tags_if_missing, ensure_permission
from imgtag.core.logging_config import get_logger
from imgtag.core.search_logging import traced_search
from imgtag.core.permissions import Permission
from imgtag.db import get_async_session
from imgtag.db.repositories import image_repository
from imgtag.schemas.external import ExternalImageCreate, ExternalImageForm, ExternalImageOptions
from imgtag.services.external_image_service import create_external_image, needs_analysis
from imgtag.services.storage_service import storage_service
from imgtag.services.upload_service import UploadSizeExceeded, upload_service

logger = get_logger(__name__)

router = APIRouter()


@router.get("/images/random")
async def random_images(
    tags: list[str] = Query([], description="标签列表（AND 关系）"),
    count: int = Query(1, ge=1, le=50, description="返回数量"),
    include_full_url: bool = Query(True, description="是否返回完整 URL"),
    api_user: dict = Depends(require_api_key),
    session: AsyncSession = Depends(get_async_session),
):
    """Get random images by tags.

    Single query with JOIN for performance.

    Args:
        tags: Tag filter (AND logic).
        count: Number of images.
        include_full_url: Whether to include full URL.
        api_user: API user.
        session: Database session.

    Returns:
        Random images list.
    """
    start_time = time.perf_counter()
    logger.debug("外部随机图片请求: filter_tags=%s count=%s user_id=%s", len(tags), count, api_user.get("id"))

    try:
        # Single query with optional tag filter
        # 可见性:普通用户可见 public + 自己上传;admin 不过滤
        is_admin = api_user.get("role") == "admin"
        result = await image_repository.get_random_by_tags(
            session,
            tags,
            count,
            visible_to_user_id=None if is_admin else api_user.get("id"),
            skip_visibility_filter=is_admin,
        )

        # Process URLs - format determined by endpoint's public_url_prefix
        images = []
        for img in result:
            images.append({
                "id": img["id"],
                "url": img["image_url"],
                "description": img["description"],
                "tags": img["tags"],
            })

        process_time = time.perf_counter() - start_time
        logger.debug("随机图片查询耗时: elapsed_ms=%.2f", process_time * 1000)

        return {"images": images, "count": len(images)}
    except Exception as e:
        logger.error(f"随机图片查询失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {e}")


async def _add_external_image(options: ExternalImageOptions, api_user: dict, session: AsyncSession,
                              *, image_url: str | None = None, file: UploadFile | None = None):
    try:
        await ensure_create_tags_if_missing(session, api_user, options.tags)
        if needs_analysis(options):
            ensure_permission(api_user, Permission.AI_ANALYZE)
        return await create_external_image(session, api_user, options, image_url=image_url, file=file)
    except UploadSizeExceeded as error:
        raise HTTPException(413, str(error)) from error
    except HTTPException:
        raise
    except Exception as error:
        logger.error("外部添加图片失败: %s", error)
        raise HTTPException(500, "添加图片失败") from error


def _validate_upload(model, data):
    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise RequestValidationError([
            {**item, "loc": ("body", *item["loc"])} for item in error.errors()
        ]) from error


_form_schema = ExternalImageForm.model_json_schema()
_form_schema["properties"]["file"] = {"type": "string", "format": "binary", "description": "单张图片文件"}
_form_schema["required"] = ["file"]


@router.post("/images", openapi_extra={"requestBody": {"required": True, "content": {
    "application/json": {"schema": ExternalImageCreate.model_json_schema()},
    "multipart/form-data": {"schema": _form_schema},
}}})
async def analyze_image_from_url(
    request: Request,
    api_user: dict = Depends(require_api_key),
    session: AsyncSession = Depends(get_async_session),
):
    """添加图片：JSON 传 image_url，multipart/form-data 传单个 file。"""
    ensure_permission(api_user, Permission.UPLOAD_IMAGE)
    # 身份认证只读事务在接收请求体前结束，慢上传不占用数据库连接。
    await session.rollback()
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "multipart/form-data":
        try:
            form = await upload_service.parse_upload_form(request.headers, request.stream())
        except UploadSizeExceeded as error:
            raise HTTPException(413, str(error)) from error
        except MultiPartException as error:
            raise HTTPException(400, error.message) from error
        except MultipartParseError as error:
            raise HTTPException(400, "无效的表单数据") from error
        try:
            file = form.get("file")
            if not isinstance(file, UploadFile):
                raise RequestValidationError([{"type": "missing", "loc": ("body", "file"), "msg": "Field required", "input": None}])
            data = dict(form)
            data["tags"] = form.getlist("tags")
            for key in ("category_id", "endpoint_id"):
                if data.get(key) == "":
                    data[key] = None
            options = _validate_upload(ExternalImageForm, data)
            return await _add_external_image(options, api_user, session, file=file)
        finally:
            await form.close()
    if not content_type or content_type == "application/json" or content_type.startswith("application/") and content_type.endswith("+json"):
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RequestValidationError([{"type": "json_invalid", "loc": ("body",), "msg": "Invalid JSON", "input": None}]) from error
        options = _validate_upload(ExternalImageCreate, data)
        return await _add_external_image(options, api_user, session, image_url=options.image_url)
    raise HTTPException(415, "请使用 application/json 或 multipart/form-data")


@router.get("/images/search")
@traced_search("external")
async def search_images(
    keyword: str = Query(None, description="关键词搜索"),
    tags: list[str] = Query([], description="标签筛选"),
    page: int = Query(1, ge=1, description="页码 (从 1 开始)"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    threshold: float = Query(0.7, ge=0.0, le=1.0, description="相似度阈值（用于向量搜索）"),
    api_user: dict = Depends(require_api_key),
    session: AsyncSession = Depends(get_async_session),
):
    """Search images.

    Uses existing search_images Repository method.

    Args:
        keyword: Keyword search.
        tags: Tag filter.
        page: Page number (from 1).
        size: Page size.
        api_user: API user.
        session: Database session.

    Returns:
        Search results.
    """
    logger.debug("外部图片搜索: keyword_chars=%s filter_tags=%s user_id=%s",
                 len(keyword or ""), len(tags or []), api_user.get("id"))

    try:
        offset = (page - 1) * size
        result = await image_repository.search_images(
            session,
            tags=tags if tags else None,
            keyword=keyword,
            limit=size,
            offset=offset,
            load_uploader=False,
        )

        # Batch get URLs from storage service
        result_images = result["images"]
        urls = await storage_service.get_read_urls_with_session(session, result_images)
        
        # Process results - URL format determined by endpoint config
        images = []
        for img in result_images:
            images.append({
                "id": img.id,
                "image_url": urls.get(img.id, ""),
                "description": img.description or "",
                "tags": [t.name for t in img.tags] if hasattr(img, "tags") else [],
                "created_at": img.created_at.isoformat() if img.created_at else None,
            })

        total = result["total"]
        pages = ceil(total / size) if size > 0 else 0
        
        return {
            "data": images,
            "total": total,
            "page": page,
            "size": size,
            "pages": pages,
            "has_next": page < pages,
            "has_prev": page > 1,
        }
    except Exception as e:
        logger.error(f"搜索失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {e}")


@router.get("/images/{image_id}")
async def get_image_info(
    image_id: int,
    api_user: dict = Depends(require_api_key),
    session: AsyncSession = Depends(get_async_session),
):
    """Get image details.

    Args:
        image_id: Image ID.
        api_user: API user.
        session: Database session.

    Returns:
        Image details.
    """
    logger.debug("外部图片详情: image_id=%s user_id=%s", image_id, api_user.get("id"))

    image = await image_repository.get_with_tags(session, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="图片不存在")

    # Get display URL from storage service
    display_url = await storage_service.get_read_url(image) or ""

    return {
        "id": image.id,
        "url": display_url,
        "description": image.description or "",
        "tags": [t.name for t in image.tags if t.level == 2],
        "created_at": image.created_at.isoformat() if image.created_at else None,
    }
