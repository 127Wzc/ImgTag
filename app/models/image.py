#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
图像相关的数据模型
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class ImageBase(BaseModel):
    """图像基础模型"""
    image_url: str = Field(..., description="图像URL")
    tags: List[str] = Field(..., description="标签列表")
    description: Optional[str] = Field(None, description="图像描述")

class ImageCreate(ImageBase):
    """图像创建模型"""
    pass

class ImageUpdate(BaseModel):
    """图像更新模型"""
    image_url: Optional[str] = Field(None, description="图像URL")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    description: Optional[str] = Field(None, description="图像描述")

class ImageSearchRequest(BaseModel):
    """图像高级搜索请求模型"""
    tags: Optional[List[str]] = Field(None, description="标签列表（包含任一标签即匹配）")
    url_contains: Optional[str] = Field(None, description="URL包含的文本")
    description_contains: Optional[str] = Field(None, description="描述包含的文本")
    limit: int = Field(10, description="返回结果数量上限")
    offset: int = Field(0, description="结果偏移量，用于分页")
    sort_by: Optional[str] = Field("id", description="排序字段：id, url, created_at")
    sort_desc: bool = Field(False, description="是否降序排序")

class ImageResponse(ImageBase):
    """图像响应模型"""
    id: int
    similarity: Optional[float] = Field(None, description="相似度，仅在相似度搜索时返回")
    
    class Config:
        from_attributes = True

class ImageSearchResponse(BaseModel):
    """图像搜索响应模型"""
    images: List[ImageResponse] = Field(..., description="图像列表")
    total: int = Field(..., description="符合条件的总记录数")
    limit: int = Field(..., description="查询限制")
    offset: int = Field(..., description="查询偏移量")

class SearchByTags(BaseModel):
    """标签搜索请求模型"""
    tags: List[str] = Field(..., description="要搜索的标签列表")
    limit: int = Field(10, description="返回结果数量上限")

class TextSearchRequest(BaseModel):
    """文本搜索请求模型"""
    text: str = Field(..., description="搜索文本")
    tags: Optional[List[str]] = Field(None, description="搜索标签列表")
    limit: int = Field(10, description="返回结果数量上限")
    threshold: float = Field(0.7, description="相似度阈值")

class StatusResponse(BaseModel):
    """系统状态响应模型"""
    image_count: int = Field(..., description="图像数量")
    status: str = Field(..., description="系统状态")
    version: str = Field(..., description="API版本") 