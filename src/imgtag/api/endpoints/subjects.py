#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""主体词典 API。"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import get_current_user, require_admin
from imgtag.db import get_async_session
from imgtag.db.repositories import subject_repository, tag_repository
from imgtag.schemas import SubjectCreate, SubjectResponse, SubjectUpdate

router = APIRouter()


def _subject_to_response(row) -> SubjectResponse:
    alias_tag_ids = [int(i) for i in (getattr(row, "alias_tag_ids", None) or []) if int(i) > 0]
    alias_names = [str(n) for n in (getattr(row, "aliases", None) or []) if n]
    category_name = row.category_tag.name if getattr(row, "category_tag", None) else ""
    primary_name = row.primary_tag.name if getattr(row, "primary_tag", None) else row.name
    return SubjectResponse(
        id=row.id,
        name=row.name,
        category_tag_id=int(row.category_tag_id),
        category_tag_name=category_name,
        primary_tag_id=int(row.primary_tag_id),
        primary_tag_name=primary_name,
        alias_tag_ids=alias_tag_ids,
        aliases=alias_names,
        description=row.description,
        is_active=row.is_active,
        created_by=row.created_by,
    )


async def _validate_subject_tag_links(
    session: AsyncSession,
    *,
    category_tag_id: int,
    primary_tag_id: int,
    alias_tag_ids: list[int] | None,
) -> tuple[Any, Any, list[Any], list[int]]:
    category_tag = await tag_repository.get_by_id(session, category_tag_id)
    if not category_tag:
        raise HTTPException(status_code=404, detail=f"分类标签 #{category_tag_id} 不存在")
    if category_tag.level != 0:
        raise HTTPException(status_code=400, detail="category_tag_id 必须是一级分类标签(level=0)")

    primary_tag = await tag_repository.get_by_id(session, primary_tag_id)
    if not primary_tag:
        raise HTTPException(status_code=404, detail=f"主名称标签 #{primary_tag_id} 不存在")
    if primary_tag.level != 2:
        raise HTTPException(status_code=400, detail="primary_tag_id 必须是普通标签(level=2)")
    if primary_tag.parent_id is not None and int(primary_tag.parent_id) != int(category_tag_id):
        raise HTTPException(status_code=400, detail="primary_tag_id 与 category_tag_id 的父子关系不匹配")

    alias_ids = sorted(
        set(
            int(i)
            for i in (alias_tag_ids or [])
            if int(i) > 0 and int(i) != int(primary_tag_id)
        )
    )
    if not alias_ids:
        return category_tag, primary_tag, [], []

    alias_tags = [t for t in await tag_repository.get_by_ids(session, alias_ids) if t]
    found_alias_ids = {int(t.id) for t in alias_tags}
    missing_alias_ids = [aid for aid in alias_ids if aid not in found_alias_ids]
    if missing_alias_ids:
        raise HTTPException(status_code=404, detail=f"别名标签不存在: {missing_alias_ids}")

    invalid_alias_tags = [int(t.id) for t in alias_tags if t.level != 2]
    if invalid_alias_tags:
        raise HTTPException(status_code=400, detail=f"别名标签必须是普通标签(level=2): {invalid_alias_tags}")

    wrong_parent_alias_ids = [
        int(t.id)
        for t in alias_tags
        if t.parent_id is not None and int(t.parent_id) != int(category_tag_id)
    ]
    if wrong_parent_alias_ids:
        raise HTTPException(
            status_code=400,
            detail=f"别名标签与 category_tag_id 的父子关系不匹配: {wrong_parent_alias_ids}",
        )

    return category_tag, primary_tag, alias_tags, alias_ids


@router.get("/", response_model=list[SubjectResponse])
async def list_subjects(
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    keyword: str | None = Query(default=None, description="名称/描述关键字"),
    active_only: bool = Query(default=True, description="仅显示启用的主体"),
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """主体词典列表（需登录：词典可能包含人名等敏感信息，不对匿名开放）。"""
    _ = user
    rows = await subject_repository.list_subjects(
        session,
        limit=size,
        offset=(page - 1) * size,
        keyword=keyword,
        active_only=active_only,
    )
    return [
        _subject_to_response(row)
        for row in rows
    ]


@router.post("/", response_model=SubjectResponse)
async def create_subject(
    data: SubjectCreate,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    category_tag, primary_tag, alias_tags, alias_ids = await _validate_subject_tag_links(
        session,
        category_tag_id=int(data.category_tag_id),
        primary_tag_id=int(data.primary_tag_id),
        alias_tag_ids=data.alias_tag_ids,
    )

    existing = await subject_repository.get_by_primary_tag_id(session, data.primary_tag_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"主体主名称标签 #{data.primary_tag_id} 已被占用")

    created = await subject_repository.create_with_tag_links(
        session,
        category_tag_id=data.category_tag_id,
        primary_tag_id=data.primary_tag_id,
        name=primary_tag.name,
        alias_tag_ids=alias_ids,
        alias_names=[str(t.name) for t in alias_tags],
        description=(data.description or "").strip() or None,
        is_active=True,
        created_by=admin.get("id"),
    )
    # 重新读取（带关系）以返回完整结构
    created_row = await subject_repository.get_by_id_with_relations(session, created.id)
    if created_row:
        return _subject_to_response(created_row)

    # 兜底（极小概率，关系加载失败）
    return SubjectResponse(
        id=created.id,
        name=created.name,
        category_tag_id=created.category_tag_id,
        category_tag_name=category_tag.name,
        primary_tag_id=created.primary_tag_id,
        primary_tag_name=primary_tag.name,
        alias_tag_ids=[int(t.id) for t in alias_tags],
        aliases=[str(t.name) for t in alias_tags],
        description=created.description,
        is_active=created.is_active,
        created_by=created.created_by,
    )


@router.patch("/{subject_id}", response_model=SubjectResponse)
async def update_subject(
    subject_id: int,
    data: SubjectUpdate,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    _ = admin
    subject = await subject_repository.get_by_id(session, subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail=f"主体 #{subject_id} 不存在")

    category_tag_id = int(data.category_tag_id) if data.category_tag_id is not None else int(subject.category_tag_id)
    primary_tag_id = int(data.primary_tag_id) if data.primary_tag_id is not None else int(subject.primary_tag_id)
    if "alias_tag_ids" in data.model_fields_set:
        alias_input = data.alias_tag_ids or []
    else:
        alias_input = [int(i) for i in (subject.alias_tag_ids or []) if int(i) > 0]

    category_tag, primary_tag, alias_tags, alias_ids = await _validate_subject_tag_links(
        session,
        category_tag_id=category_tag_id,
        primary_tag_id=primary_tag_id,
        alias_tag_ids=alias_input,
    )

    existing = await subject_repository.get_by_primary_tag_id(session, primary_tag_id)
    if existing and int(existing.id) != int(subject.id):
        raise HTTPException(status_code=409, detail=f"主体主名称标签 #{primary_tag_id} 已被占用")

    update_data: dict[str, Any] = {
        "name": str(primary_tag.name),
        "category_tag_id": category_tag_id,
        "primary_tag_id": primary_tag_id,
        "alias_tag_ids": alias_ids or None,
        "aliases": [str(t.name) for t in alias_tags],
    }
    if "description" in data.model_fields_set:
        update_data["description"] = (data.description or "").strip() or None
    if "is_active" in data.model_fields_set and data.is_active is not None:
        update_data["is_active"] = bool(data.is_active)

    await subject_repository.update(session, subject, **update_data)

    updated_row = await subject_repository.get_by_id_with_relations(session, subject.id)
    return _subject_to_response(updated_row if updated_row else subject)
