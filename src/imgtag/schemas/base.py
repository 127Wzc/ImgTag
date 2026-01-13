"""Pydantic Schema 基类模块

提供统一的响应 Schema 基类。
"""

from pydantic import BaseModel, ConfigDict
class BaseSchema(BaseModel):
    """API Schema 基类
    
    所有 API 响应/请求类都应继承此基类，便于全局控制 Schema 配置。
    
    特性:
        - from_attributes: 支持从 ORM 模型创建 (如 Image -> ImageResponse)
        - populate_by_name: 支持别名输入
    
    扩展点:
        - 如需添加 camelCase 转换，可在此添加 alias_generator
        - 如需全局字段验证，可在此添加 validators
    """
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )




# ============= 通用分页响应 =============

from typing import Generic, TypeVar, List
from pydantic import Field
from math import ceil

T = TypeVar("T")


class PaginatedResponse(BaseSchema, Generic[T]):
    """通用分页响应基类 (Page/Size 风格)
    
    所有分页响应应使用此基类，确保前端可统一处理分页逻辑。
    
    字段说明:
        - data: 数据列表
        - total: 总记录数
        - page: 当前页码 (从 1 开始)
        - size: 每页数量
        - pages: 总页数 (计算属性)
        - has_next: 是否有下一页
        - has_prev: 是否有上一页
    
    Example:
        ```python
        @router.get("/images", response_model=PaginatedResponse[ImageResponse])
        async def list_images(page: int = 1, size: int = 20):
            images, total = await image_service.search(...)
            return PaginatedResponse.create(images, total, page, size)
        ```
    """
    data: List[T] = Field(default_factory=list, description="数据列表")
    total: int = Field(default=0, description="总记录数")
    page: int = Field(default=1, ge=1, description="当前页码 (从 1 开始)")
    size: int = Field(default=20, ge=1, le=100, description="每页数量")
    pages: int = Field(default=0, description="总页数")
    has_next: bool = Field(default=False, description="是否有下一页")
    has_prev: bool = Field(default=False, description="是否有上一页")
    
    @classmethod
    def create(
        cls,
        items: List[T],
        total: int,
        page: int = 1,
        size: int = 20,
    ) -> "PaginatedResponse[T]":
        """创建分页响应的工厂方法
        
        Args:
            items: 当前页数据列表
            total: 总记录数
            page: 当前页码 (从 1 开始)
            size: 每页数量
            
        Returns:
            PaginatedResponse 实例
        """
        pages = ceil(total / size) if size > 0 else 0
        return cls(
            data=items,
            total=total,
            page=page,
            size=size,
            pages=pages,
            has_next=page < pages,
            has_prev=page > 1,
        )

