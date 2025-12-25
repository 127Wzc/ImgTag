#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Pydantic 模式定义
图像相关的请求和响应模型
"""

from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl


# ============= 图像分析结果 =============

class ImageAnalysisResult(BaseModel):
    """图像分析结果"""
    tags: List[str] = Field(default_factory=list, description="图像标签列表")
    description: str = Field(default="", description="图像描述")


# ============= 图像创建请求 =============

class ImageCreateByUrl(BaseModel):
    """通过 URL 创建图像"""
    image_url: str = Field(..., description="图像 URL")
    auto_analyze: bool = Field(default=True, description="是否自动分析图像")
    tags: Optional[List[str]] = Field(default=None, description="手动指定的标签")
    description: Optional[str] = Field(default=None, description="手动指定的描述")


class ImageCreateManual(BaseModel):
    """手动创建图像记录（带有已知标签和描述）"""
    image_url: str = Field(..., description="图像 URL")
    tags: List[str] = Field(..., description="标签列表")
    description: str = Field(default="", description="图像描述")


# ============= 图像响应 =============

class TagWithSource(BaseModel):
    """带来源的标签"""
    name: str = Field(..., description="标签名称")
    source: str = Field(default="ai", description="标签来源: user/ai")


class ImageResponse(BaseModel):
    """图像响应"""
    id: int = Field(..., description="图像 ID")
    image_url: str = Field(..., description="图像 URL")
    tags: List[str] = Field(default_factory=list, description="标签列表（向后兼容）")
    tags_with_source: List[TagWithSource] = Field(default_factory=list, description="带来源的标签列表")
    description: Optional[str] = Field(default=None, description="图像描述")
    original_url: Optional[str] = Field(default=None, description="原始 URL")
    width: Optional[int] = Field(default=None, description="图片宽度（像素）")
    height: Optional[int] = Field(default=None, description="图片高度（像素）")
    file_size: Optional[float] = Field(default=None, description="文件大小（MB）")


class ImageWithSimilarity(ImageResponse):
    """带相似度的图像响应"""
    similarity: float = Field(..., description="相似度分数")


# ============= 图像更新请求 =============

class ImageUpdate(BaseModel):
    """图像更新请求"""
    image_url: Optional[str] = Field(default=None, description="新的图像 URL")
    tags: Optional[List[str]] = Field(default=None, description="新的标签列表")
    description: Optional[str] = Field(default=None, description="新的描述")
    original_url: Optional[str] = Field(default=None, description="原始来源地址")


# ============= 搜索请求 =============

class ImageSearchRequest(BaseModel):
    """高级图像搜索请求"""
    tags: Optional[List[str]] = Field(default=None, description="标签列表（包含任一即匹配）")
    url_contains: Optional[str] = Field(default=None, description="URL 包含的文本")
    description_contains: Optional[str] = Field(default=None, description="描述包含的文本（向后兼容）")
    keyword: Optional[str] = Field(default=None, description="关键字，模糊匹配标签和描述")
    category_id: Optional[int] = Field(default=None, description="主分类 tag_id (level=0)")
    resolution_id: Optional[int] = Field(default=None, description="分辨率 tag_id (level=1)")
    pending_only: bool = Field(default=False, description="仅显示待分析的图片（无标签）")
    duplicates_only: bool = Field(default=False, description="仅显示重复的图片")
    limit: int = Field(default=10, ge=1, le=100, description="返回结果数量")
    offset: int = Field(default=0, ge=0, description="结果偏移量")
    sort_by: str = Field(default="id", description="排序字段")
    sort_desc: bool = Field(default=False, description="是否降序")


class SimilarSearchRequest(BaseModel):
    """相似度搜索请求"""
    text: str = Field(..., description="搜索文本")
    tags: Optional[List[str]] = Field(default=None, description="标签列表")
    category_id: Optional[int] = Field(default=None, description="主分类 tag_id (level=0)")
    resolution_id: Optional[int] = Field(default=None, description="分辨率 tag_id (level=1)")
    limit: int = Field(default=10, ge=1, le=100, description="返回结果数量")
    threshold: float = Field(default=0.7, ge=0, le=1, description="相似度阈值")
    vector_weight: float = Field(default=0.7, ge=0, le=1, description="向量相似度权重")
    tag_weight: float = Field(default=0.3, ge=0, le=1, description="标签匹配权重")


# ============= 搜索响应 =============

class ImageSearchResponse(BaseModel):
    """图像搜索响应"""
    images: List[ImageResponse] = Field(default_factory=list, description="图像列表")
    total: int = Field(default=0, description="总数")
    limit: int = Field(default=10, description="每页数量")
    offset: int = Field(default=0, description="偏移量")


class SimilarSearchResponse(BaseModel):
    """相似度搜索响应"""
    images: List[ImageWithSimilarity] = Field(default_factory=list, description="图像列表")
    total: int = Field(default=0, description="结果数量")


# ============= 上传响应 =============

class UploadAnalyzeResponse(BaseModel):
    """上传并分析响应"""
    id: int = Field(..., description="图像 ID")
    image_url: str = Field(..., description="图像访问 URL")
    tags: List[str] = Field(default_factory=list, description="提取的标签")
    description: str = Field(default="", description="图像描述")
    process_time: str = Field(..., description="处理耗时")
