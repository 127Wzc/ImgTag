"""外部 URL 与单文件上传共用的图片保存、标签及分析流程。"""

import asyncio
import hashlib
import io
import time
from datetime import datetime, timezone as tz
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from imgtag.core.category_cache import get_category_code_cached
from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger
from imgtag.db.repositories import (
    image_location_repository, image_repository, image_tag_repository,
    storage_endpoint_repository, tag_repository,
)
from imgtag.schemas.external import ExternalImageOptions
from imgtag.services import embedding_service
from imgtag.services.backup_service import trigger_backup_for_image
from imgtag.services.storage_service import storage_service
from imgtag.services.task_queue import task_queue
from imgtag.services.upload_service import upload_service

logger = get_logger(__name__)


def needs_analysis(options: ExternalImageOptions) -> bool:
    full = any(tag and tag.strip() for tag in options.tags) and bool(options.description.strip())
    return options.auto_analyze and (bool(options.analysis_instructions.strip()) or not full)


async def _read_uploaded_image(file: UploadFile, session) -> tuple[bytes, str, int, int]:
    max_size = await upload_service.get_max_upload_size(session=session)
    content = await file.read(max_size + 1)
    if len(content) > max_size:
        raise HTTPException(413, "图片超过上传大小限制")
    if not content:
        raise HTTPException(400, "图片文件不能为空")
    extension = Path(file.filename or "").suffix.lower().lstrip(".")
    if extension not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(415, "不支持的图片文件类型")

    def inspect():
        with Image.open(io.BytesIO(content)) as image:
            file_type = (image.format or "").lower()
            dimensions = image.size
            image.verify()
            return {"jpeg": "jpg", "mpo": "jpg"}.get(file_type, file_type), dimensions

    try:
        file_type, (width, height) = await asyncio.to_thread(inspect)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        logger.warning("上传文件不是有效图片: error_type=%s", type(error).__name__)
        raise HTTPException(400, "文件不是有效图片") from error
    if file_type not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(415, "不支持的图片文件类型")
    return content, file_type, width, height


async def create_external_image(session, api_user: dict, options: ExternalImageOptions,
                                *, image_url: str | None = None, file: UploadFile | None = None) -> dict:
    start_time = time.perf_counter()
    skip_analyze = not options.auto_analyze
    user_provided_full = any(tag and tag.strip() for tag in options.tags) and bool(options.description.strip())
    need_analysis = needs_analysis(options)
    # 获取目标端点
    target_endpoint, err = await storage_endpoint_repository.resolve_upload_endpoint(
        session, options.endpoint_id
    )
    if err:
        raise HTTPException(400, err)

    if file is None:
        file_path, _, content = await upload_service.save_remote_image(image_url, session=session)
        width, height = await asyncio.to_thread(upload_service.extract_image_dimensions, content)
        file_type = file_path.split(".")[-1] if "." in file_path else "jpg"
    else:
        content, file_type, width, height = await _read_uploaded_image(file, session)

    file_hash = await asyncio.to_thread(lambda: hashlib.md5(content).hexdigest())
    file_size = round(len(content) / (1024 * 1024), 2)

    new_image = await image_repository.create_image(
        session,
        file_hash=file_hash,
        file_type=file_type,
        file_size=file_size,
        width=width,
        height=height,
        description=options.description,
        original_url=image_url,
        embedding=None,
        uploaded_by=api_user.get("id"),
        is_public=options.is_public,
    )

    # 生成统一的 object_key
    object_key = storage_service.generate_object_key(file_hash, file_type)

    # 获取分类代码（如果指定了分类）
    category_code = None
    if options.category_id:
        category_code = await get_category_code_cached(session, options.category_id)

    full_object_key = storage_service.get_full_object_key(object_key, category_code)

    # 上传到目标端点
    upload_success = await storage_service.upload_to_endpoint(
        content, full_object_key, target_endpoint
    )
    if not upload_success:
        raise HTTPException(500, f"上传到端点 {target_endpoint.name} 失败")

    # 创建 ImageLocation 记录
    await image_location_repository.create(
        session,
        image_id=new_image.id,
        endpoint_id=target_endpoint.id,
        expected_generation=getattr(target_endpoint, "operation_generation", 0) or 0,
        object_key=full_object_key,
        category_code=category_code,
        is_primary=True,
        sync_status="synced",
        synced_at=datetime.now(tz.utc),
    )

    # Set tags if provided
    if options.tags:
        await image_tag_repository.set_image_tags(
            session,
            new_image.id,
            options.tags,
            source="user",
            added_by=api_user.get("id"),
        )

    # Set category tag if provided
    if options.category_id:
        await image_tag_repository.add_tag_to_image(
            session,
            new_image.id,
            options.category_id,
            source="user",
            sort_order=0,
            added_by=api_user.get("id"),
        )

    # Set resolution tag
    if width and height:
        resolution_name = upload_service.get_resolution_level(width, height)
        if resolution_name != "unknown":
            resolution_tag = await tag_repository.get_or_create(
                session, resolution_name, source="system", level=1
            )
            await image_tag_repository.add_tag_to_image(
                session, new_image.id, resolution_tag.id, source="system", sort_order=1
            )

    await session.commit()

    # 触发自动备份到备份端点（必须在 commit 之后）
    asyncio.create_task(
        trigger_backup_for_image(new_image.id, target_endpoint.id)
    )

    # 判断是否需要 AI 分析
    if need_analysis:
        # 加入 AI 分析任务队列
        # - 如果用户提供了部分标签，AI 会补充并合并
        await task_queue.add_tasks(
            [new_image.id],
            callback_url=options.callback_url,
            analysis_instructions=options.analysis_instructions,
            callback_headers=options.callback_headers,
        )
    elif user_provided_full:
        # 用户已提供完整内容，只需生成向量（后台执行）
        asyncio.create_task(
            embedding_service.save_embedding_for_image(
                new_image.id, options.description, options.tags
            )
        )

    process_time = time.perf_counter() - start_time

    display_url = await storage_service.get_read_url(new_image) or ""

    # 获取当前标签（用户标签 + 分类 + 分辨率）
    final_tags = await image_repository.get_image_tags_with_source(session, new_image.id)

    return {
        "id": new_image.id,
        "image_url": display_url,
        "original_url": image_url,
        "tags": final_tags,
        "description": new_image.description or options.description,
        "width": width,
        "height": height,
        "skip_analyze": skip_analyze,
        "process_time": f"{process_time:.4f}秒",
    }
