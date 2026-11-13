"""存储端点相关 Schema

从 api/endpoints/storage_endpoints.py 迁移，集中管理响应类。
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, model_validator

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
    public_url_include_bucket: bool = True
    path_prefix: str = ""
    role: str
    is_enabled: bool
    is_default_upload: bool
    auto_sync_enabled: bool
    sync_from_endpoint_id: Optional[int] = None
    read_priority: int
    read_weight: int
    is_healthy: bool
    last_health_check: Optional[datetime] = None
    health_check_error: Optional[str] = None
    has_active_sync: bool = False
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
    public_url_include_bucket: bool = True
    path_prefix: str = ""
    role: str = Field(default="primary", pattern="^(primary|backup)$")
    is_enabled: bool = True
    is_default_upload: bool = False
    auto_sync_enabled: bool = False
    sync_from_endpoint_id: Optional[int] = None
    read_priority: int = 100
    read_weight: int = 1


class EndpointUpdate(BaseModel):
    """更新存储端点请求"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    provider: Optional[str] = Field(default=None, pattern="^(local|s3)$")
    endpoint_url: Optional[str] = None
    region: Optional[str] = None
    bucket_name: Optional[str] = None
    path_style: Optional[bool] = None
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    public_url_prefix: Optional[str] = None
    public_url_include_bucket: bool = True
    path_prefix: Optional[str] = None
    role: Optional[str] = Field(default=None, pattern="^(primary|backup)$")
    is_enabled: Optional[bool] = None
    is_default_upload: Optional[bool] = None
    auto_sync_enabled: Optional[bool] = None
    sync_from_endpoint_id: Optional[int] = None
    read_priority: Optional[int] = Field(default=None, ge=0)
    read_weight: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def reject_null_configuration(self):
        required = {"name", "provider", "path_style", "public_url_include_bucket", "path_prefix", "role",
                    "is_enabled", "is_default_upload", "auto_sync_enabled", "read_priority", "read_weight"}
        if any(getattr(self, key) is None for key in self.model_fields_set & required):
            raise ValueError("基础配置与读取策略不能设置为空值")
        return self


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


class ForceCleanupRequest(BaseModel):
    """只清理本地关联；远程文件与图片主数据始终保留。"""
    confirm: bool = False
    endpoint_name: str
    remove_endpoint: bool = True
