"""Image repository for image-related database operations.

Provides image-specific queries including vector similarity search,
advanced filtering, and batch operations.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import and_, asc, desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from imgtag.core.config import settings
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
        image_url: str,
        file_path: Optional[str] = None,
        file_hash: Optional[str] = None,
        file_type: Optional[str] = None,
        file_size: Optional[float] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        description: Optional[str] = None,
        original_url: Optional[str] = None,
        embedding: Optional[list[float]] = None,
        storage_type: str = "local",
        s3_path: Optional[str] = None,
        local_exists: bool = True,
        uploaded_by: Optional[int] = None,
    ) -> Image:
        """Create a new image record.

        Args:
            session: Database session.
            image_url: Access URL for the image.
            file_path: Local file path.
            file_hash: MD5 hash for deduplication.
            file_type: File extension (jpg, png, etc).
            file_size: File size in MB.
            width: Image width in pixels.
            height: Image height in pixels.
            description: Image description.
            original_url: Original source URL.
            embedding: Vector embedding (512 dimensions).
            storage_type: Storage type (local/s3).
            s3_path: S3 storage path.
            local_exists: Whether local file exists.
            uploaded_by: User ID who uploaded.

        Returns:
            Created Image instance.
        """
        return await self.create(
            session,
            image_url=image_url,
            file_path=file_path,
            file_hash=file_hash,
            file_type=file_type,
            file_size=Decimal(str(file_size)) if file_size else None,
            width=width,
            height=height,
            description=description,
            original_url=original_url,
            embedding=embedding,
            storage_type=storage_type,
            s3_path=s3_path,
            local_exists=local_exists,
            uploaded_by=uploaded_by,
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
            .options(selectinload(Image.tags))
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

    async def update_image(
        self,
        session: AsyncSession,
        image: Image,
        *,
        image_url: Optional[str] = None,
        description: Optional[str] = None,
        embedding: Optional[list[float]] = None,
        original_url: Optional[str] = None,
    ) -> Image:
        """Update image fields.

        Args:
            session: Database session.
            image: Image to update.
            image_url: New access URL.
            description: New description.
            embedding: New vector embedding.
            original_url: New original URL.

        Returns:
            Updated Image instance.
        """
        update_data = {}
        if image_url is not None:
            update_data["image_url"] = image_url
        if description is not None:
            update_data["description"] = description
        if embedding is not None:
            update_data["embedding"] = embedding
        if original_url is not None:
            update_data["original_url"] = original_url

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
        stmt = select(Image).options(selectinload(Image.tags))
        count_stmt = select(func.count()).select_from(Image)

        conditions = []

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

        # Pending only (no embedding)
        if pending_only:
            conditions.append(Image.embedding.is_(None))

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
    ) -> Sequence[tuple[str, int]]:
        """Find duplicate images by file hash.

        Returns:
            List of (file_hash, count) tuples where count > 1.
        """
        stmt = (
            select(Image.file_hash, func.count().label("cnt"))
            .where(Image.file_hash.isnot(None))
            .group_by(Image.file_hash)
            .having(func.count() > 1)
        )
        result = await session.execute(stmt)
        return [(row.file_hash, row.cnt) for row in result]

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

        query = text(f"""
            WITH tag_match AS (
                SELECT DISTINCT it.image_id
                FROM image_tags it
                JOIN tags t ON it.tag_id = t.id
                WHERE t.name = :query_text
            )
            SELECT 
                i.id, 
                i.image_url, 
                i.description, 
                i.original_url,
                (1 - (i.embedding <=> :vector)) as vector_score,
                (CASE WHEN tm.image_id IS NOT NULL THEN 1.0 ELSE 0.0 END) as tag_score,
                i.s3_path, 
                i.local_exists
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

        # Get image IDs for tag lookup
        image_ids = [row[0] for row in rows]

        # Batch fetch tags
        tags_map = {}
        if image_ids:
            tag_query = text("""
                SELECT it.image_id, ARRAY_AGG(t.name ORDER BY it.sort_order ASC, it.added_at)
                FROM image_tags it
                JOIN tags t ON it.tag_id = t.id
                WHERE it.image_id = ANY(:image_ids) AND t.level = 2
                GROUP BY it.image_id
            """)
            tag_result = await session.execute(tag_query, {"image_ids": image_ids})
            for row in tag_result:
                tags_map[row[0]] = row[1]

        # Build response
        images = []
        for row in rows:
            vector_score = float(row[4])
            tag_score = float(row[5])
            final_score = vector_score * vector_weight + tag_score * tag_weight

            # Determine display URL
            display_url = row[1]  # Default to image_url
            if row[6]:  # Has s3_path
                display_url = f"{settings.BASE_URL.rstrip('/')}/uploads/s3/{row[6]}"
            elif row[7] is False:  # local_exists is False
                pass  # Keep image_url

            images.append({
                "id": row[0],
                "image_url": display_url,
                "tags": tags_map.get(row[0], []),
                "description": row[2],
                "original_url": row[3],
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
    ) -> tuple[int, list[str]]:
        """Bulk delete images by IDs.

        Also deletes related image_tags via CASCADE or manual cleanup.

        Args:
            session: Database session.
            image_ids: List of image IDs to delete.

        Returns:
            Tuple of (deleted_count, file_paths_to_delete).
        """
        if not image_ids:
            return 0, []

        # First get file paths for cleanup
        stmt = select(Image.id, Image.file_path).where(Image.id.in_(image_ids))
        result = await session.execute(stmt)
        rows = result.fetchall()
        file_paths = [row.file_path for row in rows if row.file_path]
        found_ids = [row.id for row in rows]

        if not found_ids:
            return 0, []

        # Delete related image_tags first (if no CASCADE)
        from sqlalchemy import delete as sa_delete

        await session.execute(
            sa_delete(ImageTag).where(ImageTag.image_id.in_(found_ids))
        )

        # Delete images
        delete_stmt = sa_delete(Image).where(Image.id.in_(found_ids))
        delete_result = await session.execute(delete_stmt)
        await session.flush()

        return delete_result.rowcount, file_paths

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

        return [
            {
                "id": img.id,
                "image_url": img.image_url,
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
        result = await session.execute(
            text(f"SELECT count(*) FROM images WHERE {col_name}::date = :dt"),
            {"dt": target_date},
        )
        return result.scalar() or 0

    async def find_duplicates(
        self,
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Find duplicate images by file hash.

        Groups images with same hash.

        Args:
            session: Database session.

        Returns:
            List of duplicate groups.
        """
        stmt = (
            select(Image.file_hash, func.count().label("count"))
            .where(Image.file_hash.isnot(None))
            .group_by(Image.file_hash)
            .having(func.count() > 1)
        )
        result = await session.execute(stmt)
        return [{"file_hash": row.file_hash, "count": row.count} for row in result]

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
            List of image dicts.
        """
        stmt = (
            select(Image.id, Image.file_path, Image.image_url)
            .where(Image.file_hash.is_(None))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return [
            {"id": row.id, "file_path": row.file_path, "image_url": row.image_url}
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
        await session.execute(
            text("UPDATE images SET file_hash = :hash WHERE id = :id"),
            {"hash": file_hash, "id": image_id},
        )

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
        await session.execute(
            text("UPDATE images SET width = :w, height = :h WHERE id = :id"),
            {"w": width, "h": height, "id": image_id},
        )

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

        for update in updates:
            await session.execute(
                text("UPDATE images SET file_hash = :hash WHERE id = :id"),
                {"hash": update["hash"], "id": update["id"]},
            )
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

        for update in updates:
            await session.execute(
                text("UPDATE images SET width = :w, height = :h WHERE id = :id"),
                {"w": update["width"], "h": update["height"], "id": update["id"]},
            )
        await session.flush()
        return len(updates)


# Singleton instance
image_repository = ImageRepository()
