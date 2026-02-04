#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""schemas 模块"""

from .base import (
    BaseSchema,
    PaginatedResponse,
)
from .image import (
    ImageAnalysisResult,
    ImageCreateByUrl,
    ImageCreateManual,
    ImageResponse,
    ImageWithSimilarity,
    ImageUpdate,
    ImageUpdateSuggestion,
    ImageSearchRequest,
    SimilarSearchRequest,
    ImageSearchResponse,
    SimilarSearchResponse,
    UploadAnalyzeResponse,
    TagWithSource,
)
from .collection import (
    CollectionBase,
    CollectionCreate,
    CollectionUpdate,
    Collection,
    CollectionList,
    CollectionImageAdd,
)
from .tag import (
    TagBase,
    TagCreate,
    TagUpdate,
    Tag,
    TagList,
)
from .task import (
    TaskCreate,
    Task,
    TaskResponse,
)
from .user import (
    UserBase,
    UserCreate,
    UserLogin,
    UserResponse,
    Token,
    TokenPayload,
)
from .approval import (
    ApprovalCreate,
    ApprovalResponse,
    ApprovalList,
    ApprovalAction,
    BatchApproveRequest,
)
from .storage import (
    EndpointCreate,
    EndpointUpdate,
    EndpointResponse,
    SyncStartRequest,
    SyncProgressResponse,
    SoftDeleteRequest,
    HardDeleteRequest,
    DeletionImpactResponse,
    ActiveTaskInfo,
)

__all__ = [
    # Base
    "BaseSchema",
    "PaginatedResponse",
    # Image
    "ImageAnalysisResult",
    "ImageCreateByUrl",
    "ImageCreateManual",
    "ImageResponse",
    "ImageWithSimilarity",
    "ImageUpdate",
    "ImageUpdateSuggestion",
    "ImageSearchRequest",
    "SimilarSearchRequest",
    "ImageSearchResponse",
    "SimilarSearchResponse",
    "UploadAnalyzeResponse",
    "TagWithSource",
    # Collection
    "CollectionBase",
    "CollectionCreate",
    "CollectionUpdate",
    "Collection",
    "CollectionList",
    "CollectionImageAdd",
    # Tag
    "TagBase",
    "TagCreate",
    "TagUpdate",
    "Tag",
    "TagList",
    # Task
    "TaskCreate",
    "Task",
    "TaskResponse",
    # User
    "UserBase",
    "UserCreate",
    "UserLogin",
    "UserResponse",
    "Token",
    "TokenPayload",
    # Approval
    "ApprovalCreate",
    "ApprovalResponse",
    "ApprovalList",
    "ApprovalAction",
    "BatchApproveRequest",
    # Storage
    "EndpointCreate",
    "EndpointUpdate",
    "EndpointResponse",
    "SyncStartRequest",
    "SyncProgressResponse",
    "SoftDeleteRequest",
    "HardDeleteRequest",
    "DeletionImpactResponse",
    "ActiveTaskInfo",
]
