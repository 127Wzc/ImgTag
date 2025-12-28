#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Storage management API endpoints.

Admin backup to S3-compatible storage.
"""

import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import require_admin
from imgtag.core.config import settings
from imgtag.core.config_cache import config_cache
from imgtag.core.logging_config import get_logger
from imgtag.db import get_async_session
from imgtag.db.repositories import image_repository
from imgtag.models.image import Image
from imgtag.services.s3_service import s3_service

logger = get_logger(__name__)

router = APIRouter()


class SyncRequest(BaseModel):
    """Sync request."""

    image_ids: Optional[list[int]] = None


class SyncResult(BaseModel):
    """Sync result."""

    success: int
    failed: int
    errors: list[str]


@router.get("/status")
async def get_storage_status(
    _=Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Get storage status statistics.

    Args:
        session: Database session.

    Returns:
        Storage stats.
    """
    try:
        # Count by storage type
        total_stmt = select(func.count()).select_from(Image)
        total = (await session.execute(total_stmt)).scalar() or 0

        local_only_stmt = (
            select(func.count())
            .select_from(Image)
            .where(
                and_(
                    Image.local_exists == True,  # noqa: E712
                    or_(Image.s3_path.is_(None), Image.s3_path == ""),
                )
            )
        )
        local_only = (await session.execute(local_only_stmt)).scalar() or 0

        s3_only_stmt = (
            select(func.count())
            .select_from(Image)
            .where(
                and_(
                    Image.s3_path.isnot(None),
                    Image.s3_path != "",
                    Image.local_exists == False,  # noqa: E712
                )
            )
        )
        s3_only = (await session.execute(s3_only_stmt)).scalar() or 0

        both_stmt = (
            select(func.count())
            .select_from(Image)
            .where(
                and_(
                    Image.local_exists == True,  # noqa: E712
                    Image.s3_path.isnot(None),
                    Image.s3_path != "",
                )
            )
        )
        both = (await session.execute(both_stmt)).scalar() or 0

        return {
            "total": total,
            "local_only": local_only,
            "s3_only": s3_only,
            "both": both,
            "s3_enabled": await s3_service.is_enabled(),
        }
    except Exception as e:
        logger.error(f"获取存储状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/files")
async def get_storage_files(
    filter: str = "all",
    page: int = 1,
    page_size: int = 20,
    _=Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Get file storage status list.

    Args:
        filter: all/local_only/s3_only/both.
        page: Page number.
        page_size: Page size.
        session: Database session.

    Returns:
        Files list with pagination.
    """
    try:
        offset = (page - 1) * page_size

        # Build filter conditions
        conditions = []
        if filter == "local_only":
            conditions.append(Image.local_exists == True)  # noqa: E712
            conditions.append(or_(Image.s3_path.is_(None), Image.s3_path == ""))
        elif filter == "s3_only":
            conditions.append(Image.s3_path.isnot(None))
            conditions.append(Image.s3_path != "")
            conditions.append(Image.local_exists == False)  # noqa: E712
        elif filter == "both":
            conditions.append(Image.local_exists == True)  # noqa: E712
            conditions.append(Image.s3_path.isnot(None))
            conditions.append(Image.s3_path != "")

        # Count
        count_stmt = select(func.count()).select_from(Image)
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = (await session.execute(count_stmt)).scalar() or 0

        # Get files
        stmt = select(
            Image.id,
            Image.image_url,
            Image.file_path,
            Image.s3_path,
            Image.local_exists,
            Image.storage_type,
        )
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(Image.id.desc()).limit(page_size).offset(offset)

        result = await session.execute(stmt)
        files = [
            {
                "id": row.id,
                "image_url": row.image_url,
                "file_path": row.file_path,
                "s3_path": row.s3_path,
                "local_exists": row.local_exists,
                "storage_type": row.storage_type,
            }
            for row in result
        ]

        return {
            "files": files,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error(f"获取文件列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-connection")
async def test_s3_connection(_=Depends(require_admin)):
    """Test S3 connection.

    Returns:
        Connection test result.
    """
    try:
        result = await s3_service.test_connection()
        return result
    except Exception as e:
        logger.error(f"测试 S3 连接失败: {e}")
        return {"success": False, "message": str(e)}


@router.post("/sync-to-s3", response_model=SyncResult)
async def sync_to_s3(
    request: SyncRequest,
    _=Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Sync local files to S3.

    Args:
        request: Image IDs or sync all local-only files.
        session: Database session.

    Returns:
        Sync result.
    """
    if not await s3_service.is_enabled():
        raise HTTPException(status_code=400, detail="S3 未启用")

    # 读取强制重新上传配置
    force_reupload = await config_cache.get("s3_force_reupload", "false") == "true"
    
    try:
        success_count = 0
        failed_count = 0
        errors = []

        if request.image_ids:
            # Get specified images
            logger.info(f"同步指定图片到 S3: {request.image_ids}")
            images = await image_repository.get_by_ids(session, request.image_ids)
        else:
            # Get local-only images (or all with local file if force_reupload)
            if force_reupload:
                # 强制模式：获取所有有本地文件的图片
                stmt = (
                    select(Image)
                    .where(
                        and_(
                            Image.local_exists == True,  # noqa: E712
                            Image.file_path.isnot(None),
                        )
                    )
                    .limit(1000)
                )
            else:
                # 普通模式：只获取没有 S3 路径的图片
                stmt = (
                    select(Image)
                    .where(
                        and_(
                            Image.local_exists == True,  # noqa: E712
                            or_(Image.s3_path.is_(None), Image.s3_path == ""),
                            Image.file_path.isnot(None),
                        )
                    )
                    .limit(1000)
                )
            result = await session.execute(stmt)
            images = result.scalars().all()

        logger.info(f"找到 {len(images)} 张待同步图片 (force_reupload={force_reupload})")

        # Process each image (I/O bound - loop is necessary)
        for image in images:
            try:
                logger.info(f"处理图片 {image.id}: file_path={image.file_path}, s3_path={image.s3_path}, local_exists={image.local_exists}")
                
                # 如果已经有 s3_path 且不是强制模式，跳过
                if image.s3_path and not force_reupload:
                    logger.info(f"图片 {image.id} 已有 S3 路径，跳过")
                    continue
                
                if not image.file_path:
                    failed_count += 1
                    if len(errors) < 10:
                        errors.append(f"ID {image.id}: file_path 为空")
                    continue

                # 构建完整的本地文件路径
                if os.path.isabs(image.file_path):
                    local_path = image.file_path
                else:
                    local_path = str(settings.UPLOADS_DIR / image.file_path.lstrip("/"))

                if not os.path.exists(local_path):
                    failed_count += 1
                    if len(errors) < 10:
                        errors.append(f"ID {image.id}: 本地文件不存在 ({local_path})")
                    continue

                # Generate S3 key and upload
                filename = os.path.basename(local_path)
                s3_key = await s3_service.generate_s3_key(filename)
                logger.info(f"上传图片 {image.id}: {local_path} -> {s3_key}")
                await s3_service.upload_file(local_path, s3_key)

                # Update database
                stmt = update(Image).where(Image.id == image.id).values(
                    s3_path=s3_key, storage_type="both"
                )
                await session.execute(stmt)
                success_count += 1

            except Exception as e:
                logger.error(f"同步图片 {image.id} 失败: {e}")
                failed_count += 1
                if len(errors) < 10:
                    errors.append(f"ID {image.id}: {e}")

        await session.flush()
        logger.info(f"S3 同步完成: 成功 {success_count}, 失败 {failed_count}")
        return SyncResult(success=success_count, failed=failed_count, errors=errors)
    except Exception as e:
        logger.error(f"批量同步到 S3 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-to-local", response_model=SyncResult)
async def sync_to_local(
    request: SyncRequest,
    _=Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Sync files from S3 to local.

    Args:
        request: Image IDs or sync all S3-only files.
        session: Database session.

    Returns:
        Sync result.
    """
    if not await s3_service.is_enabled():
        raise HTTPException(status_code=400, detail="S3 未启用")

    try:
        success_count = 0
        failed_count = 0
        errors = []

        if request.image_ids:
            images = await image_repository.get_by_ids(session, request.image_ids)
        else:
            # Get S3-only images
            stmt = (
                select(Image)
                .where(
                    and_(
                        Image.s3_path.isnot(None),
                        Image.s3_path != "",
                        Image.local_exists == False,  # noqa: E712
                    )
                )
                .limit(1000)
            )
            result = await session.execute(stmt)
            images = result.scalars().all()

        # Process each image (I/O bound - loop is necessary)
        for image in images:
            try:
                if not image.s3_path:
                    failed_count += 1
                    if len(errors) < 10:
                        errors.append(f"ID {image.id}: S3 路径为空")
                    continue

                # Download from S3
                filename = os.path.basename(image.s3_path)
                local_path = str(settings.UPLOADS_DIR / filename)
                await s3_service.download_file(image.s3_path, local_path)

                # Update database
                stmt = update(Image).where(Image.id == image.id).values(
                    local_exists=True, storage_type="both", file_path=local_path
                )
                await session.execute(stmt)
                success_count += 1

            except Exception as e:
                failed_count += 1
                if len(errors) < 10:
                    errors.append(f"ID {image.id}: {e}")

        await session.flush()
        return SyncResult(success=success_count, failed=failed_count, errors=errors)
    except Exception as e:
        logger.error(f"批量同步到本地失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
