"""Image repository for image-related database operations.

Provides image-specific queries including vector similarity search,
advanced filtering, and batch operations.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import and_, asc, desc, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from imgtag.core.config import settings
from imgtag.core.config_cache import config_cache
from imgtag.db.repositories.base import BaseRepository
from imgtag.models.image import Image
from imgtag.models.tag import ImageTag, Tag


class ImageRepository(BaseRepository[Image]):
    """Repository for Image model with specialized queries.

    Includes methods for:
    - CRUD with embedded tags
    - Vector similarity search
    - Advanced search with filters
    - Batch operations
    - Deduplication by file hash
    """

    model = Image

    async def create_image(
        self,
        session: AsyncSession,
        *,
        file_hash: Optional[str] = None,
        file_type: Optional[str] = None,
        file_size: Optional[float] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        description: Optional[str] = None,
        original_url: Optional[str] = None,
        embedding: Optional[list[float]] = None,
        uploaded_by: Optional[int] = None,
        is_public: bool = True,
    ) -> Image:
        """Create a new image record.

        Note: Storage locations are created separately via ImageLocation.

        Args:
            session: Database session.
            file_hash: MD5 hash for deduplication.
            file_type: File extension (jpg, png, etc).
            file_size: File size in MB.
            width: Image width in pixels.
            height: Image height in pixels.
            description: Image description.
            original_url: Original source URL.
            embedding: Vector embedding (512 dimensions).
            uploaded_by: User ID who uploaded.
            is_public: Whether image is publicly visible.

        Returns:
            Created Image instance.
        """
        return await self.create(
            session,
            file_hash=file_hash,
            file_type=file_type,
            file_size=Decimal(str(file_size)) if file_size else None,
            width=width,
            height=height,
            description=description,
            original_url=original_url,
            embedding=embedding,
            uploaded_by=uploaded_by,
            is_public=is_public,
        )

    async def get_by_hash(
        self,
        session: AsyncSession,
        file_hash: str,
    ) -> Optional[Image]:
        """Find image by file hash.

        Args:
            session: Database session.
            file_hash: MD5 hash of the file.

        Returns:
            Image instance or None if not found.
        """
        return await self.get_by_field(session, "file_hash", file_hash)

    async def get_with_tags(
        self,
        session: AsyncSession,
        image_id: int,
    ) -> Optional[Image]:
        """Get image with eager-loaded tags.

        Args:
            session: Database session.
            image_id: Image primary key.

        Returns:
            Image with tags loaded or None.
        """
        stmt = (
            select(Image)
            .options(selectinload(Image.tags), selectinload(Image.uploader))
            .where(Image.id == image_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_image_tags_with_source(
        self,
        session: AsyncSession,
        image_id: int,
    ) -> list[dict[str, Any]]:
        """Get image tags with source information.

        Args:
            session: Database session.
            image_id: Image ID.

        Returns:
            List of tag dicts with source, level, and sort_order.
        """
        stmt = (
            select(
                Tag.id,
                Tag.name,
                Tag.level,
                ImageTag.source,
                ImageTag.sort_order,
            )
            .join(ImageTag, Tag.id == ImageTag.tag_id)
            .where(ImageTag.image_id == image_id)
            .order_by(ImageTag.sort_order, Tag.level)
        )
        result = await session.execute(stmt)
        return [
            {
                "id": row.id,
                "name": row.name,
                "level": row.level,
                "source": row.source,
                "sort_order": row.sort_order,
            }
            for row in result
        ]

    async def get_batch_image_tags_with_source(
        self,
        session: AsyncSession,
        image_ids: list[int],
    ) -> dict[int, list[dict[str, Any]]]:
        """Get tags with source for multiple images in one query.

        Args:
            session: Database session.
            image_ids: List of image IDs.

        Returns:
            Dict mapping image_id to list of tag dicts with source, level, sort_order.
        """
        if not image_ids:
            return {}

        stmt = (
            select(
                ImageTag.image_id,
                Tag.id,
                Tag.name,
                Tag.level,
                ImageTag.source,
                ImageTag.sort_order,
            )
            .join(Tag, Tag.id == ImageTag.tag_id)
            .where(ImageTag.image_id.in_(image_ids))
            .order_by(ImageTag.image_id, Tag.level, ImageTag.sort_order)
        )
        result = await session.execute(stmt)

        # Group by image_id
        tags_map: dict[int, list[dict[str, Any]]] = {img_id: [] for img_id in image_ids}
        for row in result:
            tags_map[row.image_id].append({
                "id": row.id,
                "name": row.name,
                "level": row.level,
                "source": row.source,
                "sort_order": row.sort_order,
            })

        return tags_map

    async def update_image(
        self,
        session: AsyncSession,
        image: Image,
        *,
        description: Optional[str] = None,
        embedding: Optional[list[float]] = None,
        original_url: Optional[str] = None,
        is_public: Optional[bool] = None,
    ) -> Image:
        """Update image fields.

        Args:
            session: Database session.
            image: Image to update.
            description: New description.
            embedding: New vector embedding.
            original_url: New original URL.
            is_public: New visibility status.

        Returns:
            Updated Image instance.
        """
        update_data = {}
        if description is not None:
            update_data["description"] = description
        if embedding is not None:
            update_data["embedding"] = embedding
        if original_url is not None:
            update_data["original_url"] = original_url
        if is_public is not None:
            update_data["is_public"] = is_public

        if update_data:
            update_data["updated_at"] = datetime.now(timezone.utc)
            return await self.update(session, image, **update_data)
        return image

    async def search_by_vector(
        self,
        session: AsyncSession,
        embedding: list[float],
        *,
        limit: int = 20,
        threshold: float = 0.7,
    ) -> Sequence[tuple[Image, float]]:
        """Search images by vector similarity.

        Uses cosine distance for similarity comparison.

        Args:
            session: Database session.
            embedding: Query vector (512 dimensions).
            limit: Maximum results to return.
            threshold: Minimum similarity score (0-1).

        Returns:
            List of (Image, similarity_score) tuples.
        """
        distance = Image.embedding.cosine_distance(embedding)

        stmt = (
            select(Image, (1 - distance).label("similarity"))
            .where(Image.embedding.isnot(None))
            .where((1 - distance) >= threshold)
            .order_by(distance)
            .limit(limit)
        )
        result = await session.execute(stmt)
        return [(row.Image, row.similarity) for row in result]

    async def search_images(
        self,
        session: AsyncSession,
        *,
        tags: Optional[list[str]] = None,
        keyword: Optional[str] = None,
        category_id: Optional[int] = None,
        resolution_id: Optional[int] = None,
        user_id: Optional[int] = None,
        visible_to_user_id: Optional[int] = None,
        skip_visibility_filter: bool = False,
        pending_only: bool = False,
        duplicates_only: bool = False,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "id",
        sort_desc: bool = True,
    ) -> dict[str, Any]:
        """Advanced image search with multiple filters.

        Args:
            session: Database session.
            tags: Filter by tag names (AND logic).
            keyword: Search in description and tags.
            category_id: Filter by category (level=0 tag).
            resolution_id: Filter by resolution (level=1 tag).
            user_id: Filter by uploader user ID.
            visible_to_user_id: If set, only return public images or images uploaded by this user.
            pending_only: Only images without embeddings.
            duplicates_only: Only duplicated images (by hash).
            limit: Maximum results.
            offset: Pagination offset.
            sort_by: Sort field (id, created_at).
            sort_desc: Descending order if True.

        Returns:
            Dict with images, total, limit, offset.
        """
        # Base query - eager load tags to avoid lazy-load issues
        stmt = select(Image).options(selectinload(Image.tags), selectinload(Image.uploader))
        count_stmt = select(func.count()).select_from(Image)

        conditions = []

        # Visibility filter:
        # - skip_visibility_filter=True: no filter (admin mode)
        # - visible_to_user_id set: show public OR owned by user
        # - visible_to_user_id=None: show only public (anonymous user)
        if not skip_visibility_filter:
            if visible_to_user_id is not None:
                conditions.append(
                    or_(Image.is_public == True, Image.uploaded_by == visible_to_user_id)
                )
            else:
                # Anonymous user: only public images
                conditions.append(Image.is_public == True)

        # User filter
        if user_id is not None:
            conditions.append(Image.uploaded_by == user_id)

        # Tag filter (AND - must have all tags)
        if tags:
            subquery = (
                select(ImageTag.image_id)
                .join(Tag, ImageTag.tag_id == Tag.id)
                .where(Tag.name.in_(tags))
                .group_by(ImageTag.image_id)
                .having(func.count(func.distinct(Tag.id)) == len(tags))
            )
            conditions.append(Image.id.in_(subquery))

        # Category filter
        if category_id:
            cat_subquery = (
                select(ImageTag.image_id)
                .where(ImageTag.tag_id == category_id)
            )
            conditions.append(Image.id.in_(cat_subquery))

        # Resolution filter
        if resolution_id:
            res_subquery = (
                select(ImageTag.image_id)
                .where(ImageTag.tag_id == resolution_id)
            )
            conditions.append(Image.id.in_(res_subquery))

        # Keyword search (description OR tags)
        if keyword:
            keyword_pattern = f"%{keyword}%"
            keyword_subquery = (
                select(ImageTag.image_id)
                .join(Tag, ImageTag.tag_id == Tag.id)
                .where(Tag.name.ilike(keyword_pattern))
            )
            conditions.append(
                or_(
                    Image.description.ilike(keyword_pattern),
                    Image.id.in_(keyword_subquery),
                )
            )

        # Pending only: description 为空
        if pending_only:
            conditions.append(
                or_(Image.description.is_(None), Image.description == "")
            )

        # Duplicates only
        if duplicates_only:
            dup_subquery = (
                select(Image.file_hash)
                .where(Image.file_hash.isnot(None))
                .group_by(Image.file_hash)
                .having(func.count() > 1)
            )
            conditions.append(Image.file_hash.in_(dup_subquery))

        # Apply conditions
        if conditions:
            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))

        # Count total
        total = (await session.execute(count_stmt)).scalar() or 0

        # Sorting
        sort_column = getattr(Image, sort_by, Image.id)
        if sort_desc:
            stmt = stmt.order_by(desc(sort_column))
        else:
            stmt = stmt.order_by(asc(sort_column))

        # Pagination
        stmt = stmt.limit(limit).offset(offset)

        result = await session.execute(stmt)
        images = result.scalars().all()

        return {
            "images": images,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def count_images(self, session: AsyncSession) -> int:
        """Get total image count.

        Args:
            session: Database session.

        Returns:
            Total number of images.
        """
        stmt = select(func.count()).select_from(Image)
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def count_pending(self, session: AsyncSession) -> int:
        """Get count of images without embeddings.

        Args:
            session: Database session.

        Returns:
            Count of pending images.
        """
        stmt = (
            select(func.count())
            .select_from(Image)
            .where(Image.embedding.is_(None))
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def find_duplicates(
        self,
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Find duplicate images by file hash with full details.

        Returns:
            List of duplicate groups with image details.
        """
        # Step 1: Find duplicate hashes
        hash_stmt = (
            select(Image.file_hash, func.count().label("cnt"))
            .where(Image.file_hash.isnot(None))
            .group_by(Image.file_hash)
            .having(func.count() > 1)
        )
        hash_result = await session.execute(hash_stmt)
        dup_hashes = [row.file_hash for row in hash_result]

        if not dup_hashes:
            return []

        # Step 2: Get all images for duplicate hashes
        images_stmt = (
            select(Image)
            .where(Image.file_hash.in_(dup_hashes))
            .order_by(Image.file_hash, Image.created_at)
        )
        images_result = await session.execute(images_stmt)
        images = images_result.scalars().all()

        # Step 3: Group by hash
        from imgtag.services.storage_service import storage_service
        url_map = await storage_service.get_read_urls_with_session(session, list(images))
        
        groups: dict[str, list[dict]] = {}
        for img in images:
            if img.file_hash not in groups:
                groups[img.file_hash] = []
            groups[img.file_hash].append({
                "id": img.id,
                "image_url": url_map.get(img.id, ""),
                "file_size": float(img.file_size) if img.file_size else 0,
                "width": img.width,
                "height": img.height,
                "created_at": img.created_at.isoformat() if img.created_at else None,
            })

        return [
            {"hash": h, "count": len(imgs), "images": imgs}
            for h, imgs in groups.items()
        ]

    async def get_paginated(
        self,
        session: AsyncSession,
        *,
        page: int = 1,
        per_page: int = 20,
        order_desc: bool = True,
    ) -> tuple[Sequence[Image], int]:
        """Get paginated images with total count.

        Args:
            session: Database session.
            page: Page number (1-indexed).
            per_page: Items per page.
            order_desc: Sort by ID descending if True.

        Returns:
            Tuple of (images, total_count).
        """
        count_stmt = select(func.count()).select_from(Image)
        total = (await session.execute(count_stmt)).scalar() or 0

        offset = (page - 1) * per_page
        stmt = select(Image).limit(per_page).offset(offset)

        if order_desc:
            stmt = stmt.order_by(Image.id.desc())
        else:
            stmt = stmt.order_by(Image.id)

        result = await session.execute(stmt)
        images = result.scalars().all()

        return images, total

    async def hybrid_search(
        self,
        session: AsyncSession,
        *,
        query_vector: list[float],
        query_text: str,
        limit: int = 20,
        threshold: float = 0.5,
        vector_weight: float = 0.7,
        tag_weight: float = 0.3,
        category_id: Optional[int] = None,
        resolution_id: Optional[int] = None,
        visible_to_user_id: Optional[int] = None,
        skip_visibility_filter: bool = False,
    ) -> list[dict[str, Any]]:
        """Hybrid search: vector similarity + tag matching.

        Combines vector cosine similarity with tag matching for
        weighted relevance scoring.

        Args:
            session: Database session.
            query_vector: Query embedding (512 dimensions).
            query_text: Search text for tag matching.
            limit: Maximum results.
            threshold: Minimum vector similarity.
            vector_weight: Weight for vector score (0-1).
            tag_weight: Weight for tag score (0-1).
            category_id: Filter by category (level=0 tag).
            resolution_id: Filter by resolution (level=1 tag).
            visible_to_user_id: If set, only return public images or images uploaded by this user.

        Returns:
            List of image dicts with similarity scores.
        """
        # Use raw SQL for complex hybrid query
        # This is a pragmatic choice for performance-critical search
        vector_str = ",".join(map(str, query_vector))

        # Build extra conditions
        extra_conditions = []
        params = {
            "query_text": query_text,
            "vector": f"[{vector_str}]",
            "threshold": threshold,
            "vector_weight": vector_weight,
            "tag_weight": tag_weight,
            "limit": limit,
        }

        filter_sql = ""
        if category_id:
            filter_sql += " AND i.id IN (SELECT image_id FROM image_tags WHERE tag_id = :category_id)"
            params["category_id"] = category_id
        if resolution_id:
            filter_sql += " AND i.id IN (SELECT image_id FROM image_tags WHERE tag_id = :resolution_id)"
            params["resolution_id"] = resolution_id
        # Visibility filter:
        # - skip_visibility_filter=True: no filter (admin mode)
        # - visible_to_user_id set: show public OR owned by user
        # - visible_to_user_id=None: show only public (anonymous user)
        if not skip_visibility_filter:
            if visible_to_user_id is not None:
                filter_sql += " AND (i.is_public = true OR i.uploaded_by = :visible_to_user_id)"
                params["visible_to_user_id"] = visible_to_user_id
            else:
                filter_sql += " AND i.is_public = true"

        query = text(f"""
            WITH tag_match AS (
                SELECT DISTINCT it.image_id
                FROM image_tags it
                JOIN tags t ON it.tag_id = t.id
                WHERE t.name = :query_text
            )
            SELECT 
                i.id, 
                i.description, 
                i.original_url,
                (1 - (i.embedding <=> :vector)) as vector_score,
                (CASE WHEN tm.image_id IS NOT NULL THEN 1.0 ELSE 0.0 END) as tag_score
            FROM images i
            LEFT JOIN tag_match tm ON i.id = tm.image_id
            WHERE i.embedding IS NOT NULL
              AND ((1 - (i.embedding <=> :vector)) > :threshold OR tm.image_id IS NOT NULL)
              {filter_sql}
            ORDER BY (
                (1 - (i.embedding <=> :vector)) * :vector_weight + 
                (CASE WHEN tm.image_id IS NOT NULL THEN 1.0 ELSE 0.0 END) * :tag_weight
            ) DESC
            LIMIT :limit
        """)

        result = await session.execute(query, params)
        rows = result.fetchall()

        # Get image IDs for tag lookup and URL generation
        image_ids = [row[0] for row in rows]

        # Batch fetch tags with full info (level, source) - SQLAlchemy 2.0 ORM style
        tags_map: dict[int, list[dict[str, Any]]] = {img_id: [] for img_id in image_ids}
        if image_ids:
            tag_stmt = (
                select(
                    ImageTag.image_id,
                    Tag.id,
                    Tag.name,
                    Tag.level,
                    ImageTag.source,
                    ImageTag.sort_order,
                )
                .join(Tag, Tag.id == ImageTag.tag_id)
                .where(ImageTag.image_id.in_(image_ids))
                .order_by(ImageTag.image_id, Tag.level, ImageTag.sort_order)
            )
            tag_result = await session.execute(tag_stmt)
            for tag_row in tag_result:
                tags_map[tag_row.image_id].append({
                    "id": tag_row.id,
                    "name": tag_row.name,
                    "level": tag_row.level,
                    "source": tag_row.source,
                    "sort_order": tag_row.sort_order,
                })
        
        # Batch fetch URLs using storage service (avoids N+1)
        url_map: dict[int, str] = {}
        if image_ids:
            from imgtag.services.storage_service import storage_service
            images_for_url = await self.get_by_ids(session, image_ids)
            url_map = await storage_service.get_read_urls(list(images_for_url))

        # Batch fetch uploader info（用于前端展示与权限判断）
        uploader_map: dict[int, dict[str, Any]] = {}
        if image_ids:
            from imgtag.models.user import User

            uploader_stmt = (
                select(
                    Image.id.label("image_id"),
                    Image.uploaded_by,
                    User.username.label("uploaded_by_username"),
                )
                .outerjoin(User, User.id == Image.uploaded_by)
                .where(Image.id.in_(image_ids))
            )
            uploader_result = await session.execute(uploader_stmt)
            for row in uploader_result:
                uploader_map[int(row.image_id)] = {
                    "uploaded_by": row.uploaded_by,
                    "uploaded_by_username": row.uploaded_by_username,
                }

        # Build response
        images = []
        for row in rows:
            image_id = row[0]
            vector_score = float(row[3])
            tag_score = float(row[4])
            final_score = vector_score * vector_weight + tag_score * tag_weight
            
            # Get URL from storage service (fallback to empty string)
            display_url = url_map.get(image_id, "")
            uploader = uploader_map.get(int(image_id)) or {}

            images.append({
                "id": image_id,
                "image_url": display_url,
                "tags": tags_map.get(image_id, []),
                "description": row[1],
                "original_url": row[2],
                "uploaded_by": uploader.get("uploaded_by"),
                "uploaded_by_username": uploader.get("uploaded_by_username"),
                "similarity": final_score,
                "vector_score": vector_score,
                "tag_score": tag_score,
            })

        return images

    # ==================== Batch Operations ====================

    async def get_by_ids(
        self,
        session: AsyncSession,
        image_ids: list[int],
    ) -> Sequence[Image]:
        """Get multiple images by IDs in single query.

        Args:
            session: Database session.
            image_ids: List of image IDs.

        Returns:
            List of Image instances (may be fewer than requested if some not found).
        """
        if not image_ids:
            return []

        stmt = select(Image).where(Image.id.in_(image_ids))
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_by_ids_with_tags(
        self,
        session: AsyncSession,
        image_ids: list[int],
    ) -> Sequence[Image]:
        """Get multiple images with tags by IDs in single query.

        Args:
            session: Database session.
            image_ids: List of image IDs.

        Returns:
            List of Image instances with tags loaded.
        """
        if not image_ids:
            return []

        stmt = (
            select(Image)
            .where(Image.id.in_(image_ids))
            .options(selectinload(Image.tags))
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def delete_by_ids(
        self,
        session: AsyncSession,
        image_ids: list[int],
        owner_id: Optional[int] = None,
    ) -> tuple[int, list[str]]:
        """Bulk delete images by IDs.

        Also deletes related image_tags via CASCADE or manual cleanup.
        ImageLocations are deleted via CASCADE.

        Args:
            session: Database session.
            image_ids: List of image IDs to delete.
            owner_id: If provided, only delete images uploaded by this user (for permission check).

        Returns:
            Tuple of (deleted_count, empty_list for backward compatibility).
        """
        if not image_ids:
            return 0, []

        # Build base condition
        conditions = [Image.id.in_(image_ids)]
        if owner_id is not None:
            conditions.append(Image.uploaded_by == owner_id)

        # Get IDs that match the conditions (for permission filtering)
        stmt = select(Image.id).where(and_(*conditions))
        result = await session.execute(stmt)
        found_ids = [row[0] for row in result.fetchall()]

        if not found_ids:
            return 0, []

        # Delete related image_tags first (if no CASCADE)
        from sqlalchemy import delete as sa_delete

        await session.execute(
            sa_delete(ImageTag).where(ImageTag.image_id.in_(found_ids))
        )

        # Delete images (ImageLocations deleted via CASCADE)
        delete_stmt = sa_delete(Image).where(Image.id.in_(found_ids))
        delete_result = await session.execute(delete_stmt)
        await session.flush()

        # Return empty list for file_paths (backward compatibility)
        # Physical files on endpoints should be cleaned separately if needed
        return delete_result.rowcount, []

    async def batch_update_embeddings(
        self,
        session: AsyncSession,
        updates: list[dict],
    ) -> int:
        """Batch update embeddings for multiple images.

        Uses efficient bulk update instead of N individual updates.

        Args:
            session: Database session.
            updates: List of dicts with 'id' and 'embedding' keys.

        Returns:
            Number of rows updated.
        """
        if not updates:
            return 0

        # Use executemany pattern for efficiency
        updated_count = 0
        for batch in [updates[i : i + 100] for i in range(0, len(updates), 100)]:
            for update in batch:
                await session.execute(
                    text("""
                        UPDATE images 
                        SET embedding = :embedding::vector, updated_at = NOW()
                        WHERE id = :id
                    """),
                    {"id": update["id"], "embedding": str(update["embedding"])},
                )
                updated_count += 1

        await session.flush()
        return updated_count

    async def get_random_by_tags(
        self,
        session: AsyncSession,
        tag_names: list[str],
        count: int = 1,
    ) -> list[dict[str, Any]]:
        """Get random images filtered by tags (AND logic).

        Single query with JOIN for efficiency.

        Args:
            session: Database session.
            tag_names: Tag names to filter (all must match).
            count: Number of random images.

        Returns:
            List of image dicts with tags.
        """
        # Build query with optional tag filter
        if tag_names:
            # AND logic: must have all specified tags
            subquery = (
                select(ImageTag.image_id)
                .join(Tag, ImageTag.tag_id == Tag.id)
                .where(Tag.name.in_(tag_names))
                .group_by(ImageTag.image_id)
                .having(func.count(func.distinct(Tag.id)) == len(tag_names))
            )
            stmt = (
                select(Image)
                .where(Image.id.in_(subquery))
                .options(selectinload(Image.tags))
                .order_by(func.random())
                .limit(count)
            )
        else:
            stmt = (
                select(Image)
                .options(selectinload(Image.tags))
                .order_by(func.random())
                .limit(count)
            )

        result = await session.execute(stmt)
        images = result.scalars().all()

        # Batch fetch URLs using storage service (avoids N+1)
        from imgtag.services.storage_service import storage_service
        url_map = await storage_service.get_read_urls_with_session(session, list(images))

        return [
            {
                "id": img.id,
                "image_url": url_map.get(img.id, ""),
                "description": img.description or "",
                "tags": [t.name for t in img.tags if t.level == 2],
            }
            for img in images
        ]

    async def get_pending_analysis_ids(
        self,
        session: AsyncSession,
    ) -> list[int]:
        """Get IDs of images pending analysis.

        Images without embedding are considered pending.

        Args:
            session: Database session.

        Returns:
            List of image IDs needing analysis.
        """
        stmt = (
            select(Image.id)
            .where(Image.embedding.is_(None))
            .order_by(Image.id)
        )
        result = await session.execute(stmt)
        return [row[0] for row in result]

    # ==================== Stats & Maintenance ====================

    async def count_pending_images(
        self,
        session: AsyncSession,
    ) -> int:
        """Count images pending analysis (no embedding).

        Args:
            session: Database session.

        Returns:
            Count of pending images.
        """
        stmt = select(func.count()).select_from(Image).where(Image.embedding.is_(None))
        return (await session.execute(stmt)).scalar() or 0

    async def count_by_date(
        self,
        session: AsyncSession,
        target_date: date,
        count_type: str = "uploaded",
    ) -> int:
        """Count images by date.

        Args:
            session: Database session.
            target_date: Target date object.
            count_type: 'uploaded' or 'analyzed'.

        Returns:
            Count of images.
        """
        col_name = "created_at" if count_type == "uploaded" else "updated_at"
        # 使用 Asia/Shanghai 时区转换后再提取日期，确保"今日"统计正确
        result = await session.execute(
            text(f"SELECT count(*) FROM images WHERE ({col_name} AT TIME ZONE 'Asia/Shanghai')::date = :dt"),
            {"dt": target_date},
        )
        return result.scalar() or 0

    async def count_without_hash(
        self,
        session: AsyncSession,
    ) -> int:
        """Count images without file hash.

        Args:
            session: Database session.

        Returns:
            Count of images without hash.
        """
        stmt = select(func.count()).select_from(Image).where(Image.file_hash.is_(None))
        return (await session.execute(stmt)).scalar() or 0

    async def get_without_hash(
        self,
        session: AsyncSession,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get images without file hash.

        Args:
            session: Database session.
            limit: Max results.

        Returns:
            List of dicts with 'id' key only.
        """
        stmt = (
            select(Image.id)
            .where(Image.file_hash.is_(None))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return [
            {"id": row.id}
            for row in result
        ]

    async def update_hash(
        self,
        session: AsyncSession,
        image_id: int,
        file_hash: str,
    ) -> None:
        """Update image file hash.

        Args:
            session: Database session.
            image_id: Image ID.
            file_hash: MD5 hash.
        """
        stmt = update(Image).where(Image.id == image_id).values(file_hash=file_hash)
        await session.execute(stmt)

    async def count_without_resolution(
        self,
        session: AsyncSession,
    ) -> int:
        """Count images without resolution.

        Args:
            session: Database session.

        Returns:
            Count of images without width/height.
        """
        stmt = select(func.count()).select_from(Image).where(Image.width.is_(None))
        return (await session.execute(stmt)).scalar() or 0

    async def get_without_resolution(
        self,
        session: AsyncSession,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get images without resolution.

        Args:
            session: Database session.
            limit: Max results.

        Returns:
            List of image dicts.
        """
        stmt = (
            select(Image.id, Image.file_path)
            .where(Image.width.is_(None), Image.file_path.isnot(None))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return [{"id": row.id, "file_path": row.file_path} for row in result]

    async def update_resolution(
        self,
        session: AsyncSession,
        image_id: int,
        width: int,
        height: int,
    ) -> None:
        """Update image resolution.

        Args:
            session: Database session.
            image_id: Image ID.
            width: Image width.
            height: Image height.
        """
        stmt = update(Image).where(Image.id == image_id).values(width=width, height=height)
        await session.execute(stmt)

    async def batch_update_hashes(
        self,
        session: AsyncSession,
        updates: list[dict],
    ) -> int:
        """Batch update file hashes.

        Args:
            session: Database session.
            updates: List of {'id': int, 'hash': str}.

        Returns:
            Number of updates.
        """
        if not updates:
            return 0

        for upd in updates:
            stmt = update(Image).where(Image.id == upd["id"]).values(file_hash=upd["hash"])
            await session.execute(stmt)
        await session.flush()
        return len(updates)

    async def batch_update_resolutions(
        self,
        session: AsyncSession,
        updates: list[dict],
    ) -> int:
        """Batch update resolutions.

        Args:
            session: Database session.
            updates: List of {'id': int, 'width': int, 'height': int}.

        Returns:
            Number of updates.
        """
        if not updates:
            return 0

        for upd in updates:
            stmt = update(Image).where(Image.id == upd["id"]).values(
                width=upd["width"], height=upd["height"]
            )
            await session.execute(stmt)
        await session.flush()
        return len(updates)


# Singleton instance
image_repository = ImageRepository()
