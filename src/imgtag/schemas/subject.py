#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""主体相关 Schema。"""

from typing import Literal, Optional
from datetime import datetime

from pydantic import BaseModel, Field

from imgtag.core.subject_extraction_limits import HARD_SUBJECT_EXTRACTION_MAX_IMAGES

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
    recognition_notes: str = ""
    image_count: int = Field(default=0, ge=0, description="当前关联图片数量")
    cover_image_id: int | None = None
    cover_image_url: str = ""
    definition_revision: int = 0
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
        default=True,
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


class SetImageSubjectsRequest(BaseModel):
    subject_ids: list[int] = Field(default_factory=list, max_length=30)
    primary_subject_id: int | None = Field(default=None, gt=0)
    reanalyze: bool = True


class SubjectTemplateInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=6000)
    is_active: bool = True


class SubjectTemplateResponse(BaseSchema):
    id: int
    name: str
    content: str
    is_active: bool
    is_builtin: bool


class ExtractionSampleInput(BaseModel):
    image_id: int = Field(gt=0)
    role: str = Field(default="positive", pattern="^(positive|negative|uncertain)$")
    target: str = Field(default="", max_length=300)


class ExtractionRuleInput(BaseModel):
    template_id: int = Field(gt=0)
    text: str | None = Field(default=None, max_length=6000)


class SubjectExtractionRequest(BaseModel):
    samples: list[ExtractionSampleInput] = Field(min_length=1, max_length=HARD_SUBJECT_EXTRACTION_MAX_IMAGES)
    rules: list[ExtractionRuleInput] = Field(default_factory=list, max_length=10)
    custom_supplement: str = Field(default="", max_length=6000)
    identity_background: str = Field(default="", max_length=2000)


class SaveSubjectContent(BaseModel):
    definition: str = Field(max_length=1000)
    recognition_notes: str = Field(default="", max_length=2000)
    expected_revision: int = Field(ge=0)


class RestoreSubjectRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class SubjectVersionResponse(BaseSchema):
    id: int
    subject_id: int
    state: str
    definition: str
    recognition_notes: str = ""
    edit_revision: int = 0
    payload: dict
    input_snapshot: dict
    base_revision: int
    published_revision: int | None
    created_by: int | None
    created_at: datetime
    published_at: datetime | None


class FeatureEvidence(BaseModel):
    feature: str = Field(min_length=1, max_length=2000)
    image_ids: list[int]
    scope: Literal["跨图重复", "单图可见", "用户提供"]


class VariationEvidence(BaseModel):
    variation: str = Field(min_length=1, max_length=2000)
    image_ids: list[int]


class ConfusionEvidence(BaseModel):
    image_ids: list[int]
    similarity: str = Field(default="", max_length=2000)
    differences: str = Field(default="", max_length=2000)
    limitations: str = Field(default="", max_length=2000)


class ExtractedSubjectDefinition(BaseModel):
    analysis_context: str = Field(max_length=1000)
    distinguishing_features: list[FeatureEvidence]
    observed_variations: list[VariationEvidence]
    confusions: list[ConfusionEvidence]
    unresolved: list[str]
    proposed_changes: list[str]


class SubjectReferenceImage(BaseModel):
    id: int
    image_url: str
    description: str | None = None
