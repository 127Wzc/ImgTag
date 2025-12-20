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
]
