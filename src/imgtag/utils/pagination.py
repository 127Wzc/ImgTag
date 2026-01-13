"""分页工具模块

提供类似 Java PageHelper 的优雅分页处理，统一前后端分页约定。

核心设计：
1. 前端使用 page/size 风格（从 1 开始）
2. Repository 层继续使用 limit/offset（底层 SQL 语义）
3. PageParams 负责转换和验证
4. PaginatedResponse 负责统一输出格式
"""

from dataclasses import dataclass
from math import ceil
from typing import TypeVar, Generic, List, Any

from pydantic import BaseModel, Field, field_validator


# ============= 分页参数 =============

@dataclass
class PageParams:
    """分页参数（前端 page/size 风格 -> 后端 limit/offset）
    
    类似 Java PageHelper，提供分页参数的统一处理。
    
    Example:
        ```python
        # 在 endpoint 中使用
        @router.get("/items")
        async def list_items(
            page: int = Query(1, ge=1),
            size: int = Query(20, ge=1, le=100),
        ):
            params = PageParams(page=page, size=size)
            items, total = await repo.search(limit=params.limit, offset=params.offset)
            return params.paginate(items, total)
        ```
    """
    page: int = 1
    size: int = 20
    
    def __post_init__(self):
        """验证参数"""
        if self.page < 1:
            self.page = 1
        if self.size < 1:
            self.size = 20
        if self.size > 100:
            self.size = 100
    
    @property
    def limit(self) -> int:
        """获取 SQL LIMIT 值"""
        return self.size
    
    @property
    def offset(self) -> int:
        """获取 SQL OFFSET 值"""
        return (self.page - 1) * self.size
    
    @classmethod
    def from_request(cls, page: int = 1, size: int = 20) -> "PageParams":
        """从请求参数创建（提供默认值）"""
        return cls(page=page, size=size)
    
    @classmethod
    def from_schema(cls, schema: BaseModel) -> "PageParams":
        """从 Pydantic Schema 提取分页参数
        
        Schema 需要有 page 和 size 字段。
        """
        return cls(
            page=getattr(schema, 'page', 1),
            size=getattr(schema, 'size', 20)
        )
    
    def paginate(self, items: List[Any], total: int) -> dict:
        """创建分页响应字典
        
        返回适合 PaginatedResponse 的字典格式。
        
        Args:
            items: 当前页数据
            total: 总记录数
            
        Returns:
            分页响应字典
        """
        pages = ceil(total / self.size) if self.size > 0 else 0
        return {
            "data": items,
            "total": total,
            "page": self.page,
            "size": self.size,
            "pages": pages,
            "has_next": self.page < pages,
            "has_prev": self.page > 1,
        }


# ============= 分页请求 Mixin =============

class PageRequestMixin(BaseModel):
    """分页请求 Mixin，可被其他 Schema 继承
    
    Example:
        ```python
        class MySearchRequest(PageRequestMixin):
            keyword: str | None = None
            category_id: int | None = None
        ```
    """
    page: int = Field(default=1, ge=1, description="页码 (从 1 开始)")
    size: int = Field(default=20, ge=1, le=100, description="每页数量")
    
    @property
    def limit(self) -> int:
        """获取 SQL LIMIT 值"""
        return self.size
    
    @property
    def offset(self) -> int:
        """获取 SQL OFFSET 值"""
        return (self.page - 1) * self.size
    
    def to_params(self) -> PageParams:
        """转换为 PageParams"""
        return PageParams(page=self.page, size=self.size)


# ============= 便捷函数 =============

def paginate_result(
    items: List[Any],
    total: int,
    page: int = 1,
    size: int = 20,
) -> dict:
    """创建分页响应字典的便捷函数
    
    Example:
        ```python
        return paginate_result(images, total, page=1, size=20)
        ```
    """
    return PageParams(page=page, size=size).paginate(items, total)
