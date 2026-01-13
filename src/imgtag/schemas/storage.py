"""存储端点相关 Schema

从 api/endpoints/storage_endpoints.py 迁移，集中管理响应类。
"""

from typing import Optional, List
from pydantic import BaseModel, Field

from .base import BaseSchema


# ============= 响应类 =============

class ActiveTaskInfo(BaseSchema):
    """端点活动任务信息"""
    task_id: str
    task_type: str
    status: str
    progress_percent: float = 0.0
    success_count: int = 0
    failed_count: int = 0
    total_count: int = 0


class EndpointResponse(BaseSchema):
    """存储端点响应"""
    id: int
    name: str
    provider: str
    endpoint_url: Optional[str] = None
    region: Optional[str] = None
    bucket_name: Optional[str] = None
    path_style: bool = True
    has_credentials: bool = False
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    public_url_prefix: Optional[str] = None
    path_prefix: str = ""
    role: str
    is_enabled: bool
    is_default_upload: bool
    auto_sync_enabled: bool
    sync_from_endpoint_id: Optional[int] = None
    read_priority: int
    read_weight: int
    is_healthy: bool
    location_count: int = 0
    active_task: Optional[ActiveTaskInfo] = None


class SyncProgressResponse(BaseSchema):
    """同步任务进度响应"""
    task_id: str
    task_type: str = "storage_sync"
    status: str
    total_count: int
    success_count: int
    failed_count: int
    progress_percent: float
    batch_index: Optional[int] = None
    total_batches: Optional[int] = None


class DeletionImpactResponse(BaseSchema):
    """删除影响分析响应"""
    endpoint_id: int
    endpoint_name: str
    total_locations: int
    unique_images: int
    shared_images: int
    total_file_size_mb: float
    can_soft_delete: bool
    can_hard_delete: bool
    warnings: List[str]


# ============= 请求类 (保留在此处或原文件) =============

class EndpointCreate(BaseModel):
    """创建存储端点请求"""
    name: str = Field(..., min_length=1, max_length=50)
    provider: str = Field(..., pattern="^(local|s3)$")
    endpoint_url: Optional[str] = None
    region: Optional[str] = "auto"
    bucket_name: Optional[str] = None
    path_style: bool = True
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    public_url_prefix: Optional[str] = None
    path_prefix: str = ""
    role: str = "primary"
    is_enabled: bool = True
    is_default_upload: bool = False
    auto_sync_enabled: bool = False
    sync_from_endpoint_id: Optional[int] = None
    read_priority: int = 100
    read_weight: int = 1


class EndpointUpdate(BaseModel):
    """更新存储端点请求"""
    name: Optional[str] = None
    provider: Optional[str] = None
    endpoint_url: Optional[str] = None
    region: Optional[str] = None
    bucket_name: Optional[str] = None
    path_style: Optional[bool] = None
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    public_url_prefix: Optional[str] = None
    path_prefix: Optional[str] = None
    role: Optional[str] = None
    is_enabled: Optional[bool] = None
    is_default_upload: Optional[bool] = None
    auto_sync_enabled: Optional[bool] = None
    sync_from_endpoint_id: Optional[int] = None
    read_priority: Optional[int] = None
    read_weight: Optional[int] = None


class SyncStartRequest(BaseModel):
    """启动同步任务请求"""
    source_endpoint_id: int
    target_endpoint_id: int
    image_ids: Optional[List[int]] = None
    force_overwrite: bool = False


class SoftDeleteRequest(BaseModel):
    """软删除请求"""
    confirm: bool = False
    delete_files: bool = False


class HardDeleteRequest(BaseModel):
    """硬删除请求"""
    confirm: bool = False
    confirm_text: str = ""
