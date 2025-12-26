"""Repository package for data access layer.

Provides repository pattern implementations for all models.
"""

from imgtag.db.repositories.approval import (
    ApprovalRepository,
    AuditLogRepository,
    approval_repository,
    audit_log_repository,
)
from imgtag.db.repositories.base import BaseRepository
from imgtag.db.repositories.collection import (
    CollectionRepository,
    ImageCollectionRepository,
    collection_repository,
    image_collection_repository,
)
from imgtag.db.repositories.config import ConfigRepository, config_repository
from imgtag.db.repositories.image import ImageRepository, image_repository
from imgtag.db.repositories.tag import (
    ImageTagRepository,
    TagRepository,
    image_tag_repository,
    tag_repository,
)
from imgtag.db.repositories.task import TaskRepository, task_repository
from imgtag.db.repositories.user import UserRepository, user_repository

__all__ = [
    "BaseRepository",
    # Approval
    "ApprovalRepository",
    "approval_repository",
    "AuditLogRepository",
    "audit_log_repository",
    # Collection
    "CollectionRepository",
    "collection_repository",
    "ImageCollectionRepository",
    "image_collection_repository",
    # Config
    "ConfigRepository",
    "config_repository",
    # Image
    "ImageRepository",
    "image_repository",
    # Tag
    "TagRepository",
    "tag_repository",
    "ImageTagRepository",
    "image_tag_repository",
    # Task
    "TaskRepository",
    "task_repository",
    # User
    "UserRepository",
    "user_repository",
]
