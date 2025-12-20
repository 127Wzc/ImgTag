#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""services 模块"""

from .vision_service import vision_service, VisionService
from .embedding_service import embedding_service, EmbeddingService
from .upload_service import upload_service, UploadService

__all__ = [
    "vision_service", "VisionService",
    "embedding_service", "EmbeddingService", 
    "upload_service", "UploadService",
]
