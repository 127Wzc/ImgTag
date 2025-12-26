"""Repository package for data access layer.

Provides repository pattern implementations for all models.
"""

from imgtag.db.repositories.base import BaseRepository
from imgtag.db.repositories.collection import (
    CollectionRepository,
    ImageCollectionRepository,
    collection_repository,
    image_collection_repository,
)
from imgtag.db.repositories.image import ImageRepository, image_repository
from imgtag.db.repositories.tag import (
    ImageTagRepository,
    TagRepository,
    image_tag_repository,
    tag_repository,
)
from imgtag.db.repositories.user import UserRepository, user_repository

__all__ = [
    "BaseRepository",
    "ImageRepository",
    "image_repository",
    "TagRepository",
    "tag_repository",
    "ImageTagRepository",
    "image_tag_repository",
    "UserRepository",
    "user_repository",
    "CollectionRepository",
    "collection_repository",
    "ImageCollectionRepository",
    "image_collection_repository",
]
