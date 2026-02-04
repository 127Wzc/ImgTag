#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""图片更新相关的解析与辅助服务

用于收敛 endpoint 内的 SQL/解析逻辑，确保语义一致且便于扩展/测试。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.db.repositories import image_tag_repository, tag_repository
from imgtag.models.image import Image
from imgtag.models.tag import Tag
from imgtag.utils.ids import dedup_positive_ints_keep_order


@dataclass(frozen=True)
class ParsedTagIds:
    """从 tag_ids 解析出的结构化结果。

    约定：
    - level=0：主分类（最多一个）
    - level=2：普通标签（按输入顺序）
    - level=1：分辨率标签由系统维护，解析时忽略
    """

    category_id: int | None
    category_name: str | None
    normal_tag_ids: list[int]
    normal_tag_names: list[str]


class ImageUpdateService:
    """图片更新服务（无状态）。"""

    def normalize_int_ids_keep_order(self, values: list[int]) -> list[int]:
        return dedup_positive_ints_keep_order(values)

    async def parse_tag_ids(
        self,
        session: AsyncSession,
        *,
        tag_ids: list[int],
    ) -> ParsedTagIds:
        """解析 tag_ids，提取主分类与普通标签，并校验“最多一个主分类”约束。"""
        tag_ids_input = dedup_positive_ints_keep_order(tag_ids)
        if not tag_ids_input:
            return ParsedTagIds(
                category_id=None,
                category_name=None,
                normal_tag_ids=[],
                normal_tag_names=[],
            )

        stmt = select(Tag.id, Tag.name, Tag.level).where(Tag.id.in_(tag_ids_input))
        result = await session.execute(stmt)
        meta = {int(row.id): (row.name, int(row.level)) for row in result.fetchall()}

        category_id: int | None = None
        category_name: str | None = None
        normal_tag_ids: list[int] = []
        normal_tag_names: list[str] = []

        for tid in tag_ids_input:
            m = meta.get(int(tid))
            if not m:
                continue
            name, level = m
            if level == 0:
                if category_id is not None and category_id != int(tid):
                    raise ValueError("只能选择一个主分类（level=0）")
                category_id = int(tid)
                category_name = str(name)
            elif level == 2:
                normal_tag_ids.append(int(tid))
                normal_tag_names.append(str(name))
            else:
                # level=1 分辨率标签由系统维护，忽略客户端输入
                continue

        return ParsedTagIds(
            category_id=category_id,
            category_name=category_name,
            normal_tag_ids=normal_tag_ids,
            normal_tag_names=normal_tag_names,
        )

    async def resolve_category(
        self,
        session: AsyncSession,
        *,
        image_id: int,
    ) -> tuple[int | None, str | None]:
        """获取图片当前主分类（level=0），用于“未显式指定分类时保持不变”的语义。"""
        tags = await image_tag_repository.get_image_tags(session, image_id)
        category = next((t for t in tags if getattr(t, "level", None) == 0), None)
        if not category:
            return None, None
        return int(category.id), str(category.name)

    async def validate_category_id(
        self,
        session: AsyncSession,
        *,
        category_id: int | None,
    ) -> str | None:
        """校验 category_id 存在且为 level=0，返回分类名。"""
        if category_id is None:
            return None
        if int(category_id) <= 0:
            raise ValueError("category_id 非法")
        category = await tag_repository.get_by_id(session, int(category_id))
        if not category:
            raise ValueError("目标主分类不存在")
        if getattr(category, "level", None) != 0:
            raise ValueError("目标标签不是主分类（level=0）")
        return str(category.name)

    async def validate_normal_tag_ids(
        self,
        session: AsyncSession,
        *,
        normal_tag_ids: list[int],
    ) -> list[str]:
        """校验 normal_tag_ids 全部存在且为 level=2，返回对应的标签名（按输入顺序）。"""
        ids, names = await self.normalize_and_validate_normal_tag_ids(
            session,
            normal_tag_ids=normal_tag_ids,
        )
        return names

    async def normalize_and_validate_normal_tag_ids(
        self,
        session: AsyncSession,
        *,
        normal_tag_ids: list[int],
    ) -> tuple[list[int], list[str]]:
        """归一化并校验 normal_tag_ids（去重、过滤非法、校验存在与 level=2）。"""
        normalized = self.normalize_int_ids_keep_order(normal_tag_ids or [])
        if not normalized:
            return [], []

        stmt = select(Tag.id, Tag.name, Tag.level).where(Tag.id.in_(normalized))
        result = await session.execute(stmt)
        rows = result.fetchall()
        found = {int(row.id): (str(row.name), int(row.level)) for row in rows}

        missing = [tid for tid in normalized if tid not in found]
        if missing:
            raise ValueError(f"存在不存在的标签ID: {missing[:10]}")

        wrong_level = [tid for tid in normalized if found[tid][1] != 2]
        if wrong_level:
            raise ValueError("normal_tag_ids 只能包含普通标签（level=2）")

        return normalized, [found[tid][0] for tid in normalized]

    async def filter_owned_image_ids(
        self,
        session: AsyncSession,
        *,
        image_ids: list[int],
        owner_id: int | None,
    ) -> list[int]:
        """若 owner_id 非空，则过滤出属于该用户的图片 ID 列表。"""
        if owner_id is None:
            return image_ids
        if not image_ids:
            return []

        stmt = select(Image.id).where(
            and_(Image.id.in_(image_ids), Image.uploaded_by == owner_id)
        )
        result = await session.execute(stmt)
        return [int(row.id) for row in result]


image_update_service = ImageUpdateService()
