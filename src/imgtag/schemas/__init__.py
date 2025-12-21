#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""schemas 模块"""

from .image import (
    ImageAnalysisResult,
    ImageCreateByUrl,
    ImageCreateManual,
    ImageResponse,
    ImageWithSimilarity,
    ImageUpdate,
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

__all__ = [
    "ImageAnalysisResult",
    "ImageCreateByUrl",
    "ImageCreateManual",
    "ImageResponse",
    "ImageWithSimilarity",
    "ImageUpdate",
    "ImageSearchRequest",
    "SimilarSearchRequest",
    "ImageSearchResponse",
    "SimilarSearchResponse",
    "UploadAnalyzeResponse",
    "TagWithSource",
    "CollectionBase",
    "CollectionCreate",
    "CollectionUpdate",
    "Collection",
    "CollectionList",
    "CollectionImageAdd",
    "TagBase",
    "TagCreate",
    "TagUpdate",
    "Tag",
    "TagList",
    "TaskCreate",
    "Task",
    "TaskResponse",
    "UserBase",
    "UserCreate",
    "UserLogin",
    "UserResponse",
    "Token",
    "TokenPayload",
    "ApprovalCreate",
    "ApprovalResponse",
    "ApprovalList",
    "ApprovalAction",
    "BatchApproveRequest",
]

