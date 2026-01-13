#!/usr/bin/env python
# -*- coding: utf-8 -*-

from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from .base import BaseSchema

class TaskBase(BaseModel):
    """任务基础模型"""
    type: str = Field(..., description="任务类型")
    payload: Dict[str, Any] = Field(default_factory=dict, description="任务数据")

class TaskCreate(TaskBase):
    """创建任务请求"""
    pass

class Task(BaseSchema):
    """任务响应模型"""
    id: str = Field(..., description="任务 ID")
    type: str = Field(..., description="任务类型")
    payload: Dict[str, Any] = Field(default_factory=dict, description="任务数据")
    status: str = Field(..., description="任务状态: pending/processing/completed/failed")
    result: Optional[Dict[str, Any]] = Field(default=None, description="任务结果")
    error: Optional[str] = Field(default=None, description="错误信息")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")

class TaskResponse(BaseSchema):
    """任务提交响应"""
    task_id: str = Field(..., description="任务 ID")
    message: str = Field(default="任务已提交", description="提示信息")
