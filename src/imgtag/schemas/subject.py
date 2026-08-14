#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""主体相关 Schema。"""

from typing import Optional

from pydantic import BaseModel, Field

from .base import BaseSchema


class SubjectCreate(BaseModel):
    category_tag_id: int = Field(..., gt=0, description="归属一级分类标签ID(level=0)")
    primary_tag_id: int = Field(..., gt=0, description="主体主名称标签ID(level=2)")
    alias_tag_ids: list[int] = Field(default_factory=list, description="主体别名标签ID列表(level=2)")
    description: Optional[str] = Field(default=None, max_length=1000, description="主体描述")


class SubjectUpdate(BaseModel):
    category_tag_id: Optional[int] = Field(default=None, gt=0, description="归属一级分类标签ID(level=0)")
    primary_tag_id: Optional[int] = Field(default=None, gt=0, description="主体主名称标签ID(level=2)")
    alias_tag_ids: Optional[list[int]] = Field(default=None, description="主体别名标签ID列表(level=2)")
    description: Optional[str] = Field(default=None, max_length=1000, description="主体描述")
    is_active: Optional[bool] = Field(default=None, description="是否启用")


class SubjectResponse(BaseSchema):
    id: int
    name: str
    category_tag_id: int
    category_tag_name: str
    primary_tag_id: int
    primary_tag_name: str
    alias_tag_ids: list[int] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    description: Optional[str] = None
    is_active: bool = True
    created_by: Optional[int] = None


class ImageSubjectAssignment(BaseSchema):
    subject_id: int = Field(..., description="主体ID")
    subject_name: str = Field(..., description="主体名称")
    confidence: Optional[float] = Field(default=None, description="置信度")
    source: str = Field(default="manual", description="来源")
    state: str = Field(default="confirmed", description="状态")
    is_primary: bool = Field(default=False, description="是否主主体")


class SetPrimarySubjectRequest(BaseModel):
    subject_id: int = Field(..., gt=0, description="主体ID")
    confidence: Optional[float] = Field(default=None, ge=0, le=1, description="置信度")
    add_sample: bool = Field(
        default=False,
        description="是否登记主体样本引用（记录来源图片，供后续识别器回流训练）",
    )
    reanalyze: bool = Field(
        default=False,
        description="是否触发强制重新分析以修正描述（消耗一次视觉分析调用）",
    )
    comment: Optional[str] = Field(default=None, max_length=500, description="备注")


class SuggestSubjectRequest(BaseModel):
    subject_id: int = Field(..., gt=0, description="建议主体ID")
    confidence: Optional[float] = Field(default=None, ge=0, le=1, description="建议置信度")
    comment: Optional[str] = Field(default=None, max_length=1000, description="给管理员的备注")
    add_sample: bool = Field(
        default=False,
        description="审批通过后是否登记主体样本引用（记录来源图片）",
    )
