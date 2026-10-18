"""图片分析历史，所有读取与写入仅限管理员或图片所有者。"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import get_current_user
from imgtag.api.permission_guards import ensure_create_tags_if_missing
from imgtag.db import get_async_session
from imgtag.db.repositories import image_repository
from imgtag.db.repositories.analysis_version import analysis_version_repository
from imgtag.schemas.analysis_review import (
    AnalysisVersionResponse, CurrentAnalysisSave, RestoreAnalysisRequest,
)
from imgtag.services.analysis_review_service import analysis_review_service, public_snapshot
from imgtag.services.task_queue import task_queue

router = APIRouter()


async def authorize(session, image_id, user):
    image = await image_repository.get_by_id(session, image_id)
    if image is None:
        raise HTTPException(404, "图片不存在")
    if user.get("role") != "admin" and image.uploaded_by != user["id"]:
        raise HTTPException(403, "只能查看编辑自己的图片")


@router.get("/{image_id}")
async def history(image_id: int, offset: int = Query(0, ge=0), user: dict = Depends(get_current_user),
                      session: AsyncSession = Depends(get_async_session)):
    await authorize(session, image_id, user)
    return {"current": await analysis_review_service.current(session, image_id),
            "versions": [AnalysisVersionResponse.model_validate(row).model_copy(update={"base_snapshot": public_snapshot(row.base_snapshot)}) for row in
                         await analysis_version_repository.versions(session, image_id, offset)]}


@router.put("/{image_id}/current")
async def save_current(image_id: int, data: CurrentAnalysisSave, user: dict = Depends(get_current_user),
                        session: AsyncSession = Depends(get_async_session)):
    await authorize(session, image_id, user)
    await ensure_create_tags_if_missing(session, user, data.tags)
    result = await analysis_review_service.save_current(session, image_id, data)
    await session.commit()
    asyncio.create_task(task_queue.start_processing())
    return result



@router.post("/{image_id}/{version_id}/restore")
async def restore_history(image_id: int, version_id: int, data: RestoreAnalysisRequest,
                          user: dict = Depends(get_current_user), session: AsyncSession = Depends(get_async_session)):
    await authorize(session, image_id, user)
    source = await analysis_version_repository.get_by_id(session, version_id)
    if source is None or source.image_id != image_id or source.state != "history":
        raise HTTPException(404, "历史备份不存在或已被清理，请刷新")
    await ensure_create_tags_if_missing(session, user, source.tags)
    result = await analysis_review_service.restore(session, image_id, version_id, data.expected_snapshot)
    await session.commit()
    asyncio.create_task(task_queue.start_processing())
    return result


@router.delete("/{image_id}/{version_id}", status_code=204)
async def delete_history(image_id: int, version_id: int, user: dict = Depends(get_current_user),
                         session: AsyncSession = Depends(get_async_session)):
    await authorize(session, image_id, user)
    await analysis_review_service.delete_history(session, image_id, version_id)
    await session.commit()
