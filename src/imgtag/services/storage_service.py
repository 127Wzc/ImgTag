"""Unified storage service for multi-endpoint operations.

Provides abstraction layer for uploading, downloading, and managing
files across multiple storage endpoints (local, S3, R2, etc.).
"""

import asyncio
import hashlib
import io
import os
import random
from typing import Optional, Sequence

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import DEFAULT_PRIORITY, StorageProvider
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import (
    image_location_repository,
    storage_endpoint_repository,
)
from imgtag.models.image import Image
from imgtag.models.image_location import ImageLocation
from imgtag.models.storage_endpoint import StorageEndpoint

logger = get_logger(__name__)


def _select_by_weight(
    locations: Sequence[ImageLocation],
    endpoint_map: dict[int, StorageEndpoint],
) -> ImageLocation | None:
    """Select a location using weighted random among same-priority endpoints.
    
    Groups locations by endpoint priority, then within the highest priority
    group, selects randomly based on endpoint read_weight.
    
    Args:
        locations: List of image locations to choose from.
        endpoint_map: Mapping of endpoint_id to StorageEndpoint.
        
    Returns:
        Selected ImageLocation or None if no valid locations.
    """
    if not locations:
        return None
    
    # Filter and sort by priority
    valid_locations = [
        loc for loc in locations 
        if loc.endpoint_id in endpoint_map and endpoint_map[loc.endpoint_id].is_enabled
    ]
    if not valid_locations:
        return None
    
    # Sort by priority (lower = higher priority)
    valid_locations.sort(
        key=lambda loc: endpoint_map[loc.endpoint_id].read_priority
    )
    
    # Get the best (lowest) priority
    best_priority = endpoint_map[valid_locations[0].endpoint_id].read_priority
    
    # Get all locations with best priority
    top_tier = [
        loc for loc in valid_locations
        if endpoint_map[loc.endpoint_id].read_priority == best_priority
    ]
    
    # If only one, return it directly
    if len(top_tier) == 1:
        return top_tier[0]
    
    # Weighted random selection based on read_weight (clamp negative to 0)
    weights = [max(0, endpoint_map[loc.endpoint_id].read_weight) for loc in top_tier]
    total_weight = sum(weights)
    
    # If all weights are 0, pick random uniformly
    if total_weight == 0:
        return random.choice(top_tier)
    
    # Weighted random choice
    return random.choices(top_tier, weights=weights, k=1)[0]


class StorageService:
    """Unified storage service for multi-endpoint file operations.
    
    Handles file upload/download across multiple storage backends
    with automatic endpoint selection and failover support.
    """

    def generate_object_key(self, file_hash: str, extension: str) -> str:
        """Generate unified object key based on file hash.
        
        Uses hash-based directory structure for even distribution:
        {hash[0:2]}/{hash[2:4]}/{full_hash}.{ext}
        
        Note: This returns only the hash-based path. Use get_full_object_key()
        to include the category_code prefix for actual storage.
        
        Args:
            file_hash: MD5 or SHA256 hash of the file.
            extension: File extension without dot (e.g., 'jpg').
            
        Returns:
            Object key string for storage.
        """
        ext = extension.lstrip(".")
        return f"{file_hash[:2]}/{file_hash[2:4]}/{file_hash}.{ext}"

    @staticmethod
    def get_full_object_key(
        object_key: str,
        category_code: str | None = None,
    ) -> str:
        """Build full object key with optional category prefix.
        
        Args:
            object_key: Base object key (hash-based path).
            category_code: Optional category code for subdirectory.
            
        Returns:
            Full object key: "{category_code}/{object_key}" or "{object_key}".
        """
        if category_code:
            return f"{category_code}/{object_key}"
        return object_key

    @staticmethod
    def _apply_path_prefix(object_key: str, path_prefix: str | None) -> str:
        """Apply path_prefix to object_key if configured.
        
        Unified method for both local and S3 storage.
        
        Args:
            object_key: Base object key.
            path_prefix: Optional path prefix from endpoint config.
            
        Returns:
            "{path_prefix}/{object_key}" if prefix exists, else "{object_key}".
        """
        if path_prefix:
            return f"{path_prefix.strip('/')}/{object_key}"
        return object_key

    def _resolve_local_path(self, endpoint: StorageEndpoint) -> str:
        """Resolve bucket_name to absolute physical path for local storage.
        
        All local storage buckets are under the DATA_DIR directory.
        For example, bucket_name='uploads' -> /project/data/uploads
        
        Args:
            endpoint: Storage endpoint with bucket_name.
            
        Returns:
            Absolute path string for file storage.
        """
        bucket = endpoint.bucket_name or "uploads"
        
        # If bucket_name is an absolute path, use as-is
        if os.path.isabs(bucket):
            return bucket
        
        # Relative path - resolve relative to DATA_DIR
        data_path = settings.get_data_path()
        return str(data_path / bucket)

    async def get_default_upload_endpoint(self) -> Optional[StorageEndpoint]:
        """Get the default endpoint for uploads."""
        async with async_session_maker() as session:
            endpoint = await storage_endpoint_repository.get_default_upload(session)
            if not endpoint:
                # Fallback to first enabled endpoint
                endpoints = await storage_endpoint_repository.get_enabled(session)
                endpoint = endpoints[0] if endpoints else None
            return endpoint

    async def get_endpoints(
        self,
        enabled_only: bool = True,
        healthy_only: bool = False,
    ) -> list[StorageEndpoint]:
        """Get all storage endpoints.
        
        Args:
            enabled_only: Only return enabled endpoints.
            healthy_only: Only return healthy endpoints.
            
        Returns:
            List of StorageEndpoint instances.
        """
        async with async_session_maker() as session:
            if healthy_only:
                return list(await storage_endpoint_repository.get_healthy_for_read(session))
            elif enabled_only:
                return list(await storage_endpoint_repository.get_enabled(session))
            else:
                return list(await storage_endpoint_repository.get_all(session))

    async def get_read_url(self, image: Image) -> str:
        """Get best accessible URL for an image.
        
        Selects from available locations based on endpoint priority
        and health status.
        
        NOTE: For batch operations, use get_read_urls() to avoid N+1 queries.
        
        Args:
            image: Image instance with locations relationship loaded.
            
        Returns:
            URL string for accessing the image.
        """
        urls = await self.get_read_urls([image])
        return urls.get(image.id, "")

    async def get_local_file_path(self, image_id: int) -> str | None:
        """Get local file path for an image.
        
        Looks up the image's local endpoint location and returns the full
        filesystem path.
        
        Args:
            image_id: Image ID.
            
        Returns:
            Local file path string, or None if not found.
        """
        async with async_session_maker() as session:
            locations = await image_location_repository.get_by_image(session, image_id)
            endpoints = await storage_endpoint_repository.get_enabled(session)
            
            # Find local endpoint
            local_endpoint = None
            for ep in endpoints:
                if ep.provider == StorageProvider.LOCAL:
                    local_endpoint = ep
                    break
            
            if not local_endpoint:
                return None
            
            # Find location for local endpoint
            for loc in locations:
                if loc.endpoint_id == local_endpoint.id:
                    base_path = self._resolve_local_path(local_endpoint)
                    full_key = self._apply_path_prefix(loc.object_key, local_endpoint.path_prefix)
                    return os.path.join(base_path, full_key)
            
            return None

    async def get_file_content(self, image_id: int) -> bytes | None:
        """Get file content for an image from any available source.
        
        Tries local file first, then remote endpoints in priority order.
        
        Args:
            image_id: Image ID.
            
        Returns:
            File content bytes, or None if not available.
        """
        async with async_session_maker() as session:
            # Single query for locations
            locations = await image_location_repository.get_by_image(session, image_id)
            if not locations:
                return None
            
            # Get healthy endpoints once (includes enabled check)
            endpoints = await storage_endpoint_repository.get_healthy_for_read(session)
            endpoint_map = {ep.id: ep for ep in endpoints}
            
            # Use weighted selection to pick best location
            selected = _select_by_weight(locations, endpoint_map)
            if not selected:
                return None
            
            endpoint = endpoint_map.get(selected.endpoint_id)
            if not endpoint:
                return None
            
            # Read based on endpoint type
            if endpoint.provider == StorageProvider.LOCAL:
                base_path = self._resolve_local_path(endpoint)
                full_key = self._apply_path_prefix(selected.object_key, endpoint.path_prefix)
                local_path = os.path.join(base_path, full_key)
                if os.path.exists(local_path):
                    def _read():
                        with open(local_path, "rb") as f:
                            return f.read()
                    return await asyncio.to_thread(_read)
            else:
                content = await self.download_from_endpoint(selected.object_key, endpoint)
                if content:
                    return content
        
        return None

    async def get_read_urls(self, images: list[Image]) -> dict[int, str]:
        """Get accessible URLs for multiple images efficiently.
        
        Creates its own session for standalone usage.
        For better performance when you already have a session, use
        get_read_urls_with_session() instead.
        
        Args:
            images: List of Image instances.
            
        Returns:
            Dictionary mapping image_id to URL.
        """
        if not images:
            return {}
        
        async with async_session_maker() as session:
            return await self.get_read_urls_with_session(session, images)

    async def get_read_urls_with_session(
        self,
        session: "AsyncSession",
        images: list[Image],
    ) -> dict[int, str]:
        """Get accessible URLs for multiple images using existing session.
        
        Preferred method when caller already has an active session, as it
        avoids creating additional database connections.
        
        Args:
            session: Existing database session.
            images: List of Image instances.
            
        Returns:
            Dictionary mapping image_id to URL.
        """
        if not images:
            return {}
        
        image_ids = [img.id for img in images]
        result = {img.id: "" for img in images}
        
        # Get healthy endpoints once
        endpoints = await storage_endpoint_repository.get_healthy_for_read(session)
        endpoint_map = {ep.id: ep for ep in endpoints}
        
        if not endpoint_map:
            return result
        
        # Batch get all locations for all images (single query)
        all_locations = await image_location_repository.get_by_image_ids(session, image_ids)
        
        # Build URLs for each image using weighted selection
        for image_id in image_ids:
            locations = all_locations.get(image_id, [])
            
            # Select location using priority + weight-based load balancing
            selected = _select_by_weight(locations, endpoint_map)
            if selected:
                endpoint = endpoint_map.get(selected.endpoint_id)
                if endpoint:
                    url = self._build_url(endpoint, selected.object_key)
                    if url:
                        result[image_id] = url
        
        return result

    async def download_from_any_endpoint(
        self,
        session,
        image_id: int,
        target_path: str,
    ) -> bool:
        """Download file from any available endpoint for an image.
        
        Uses weighted selection with fallback to try all endpoints.
        
        Args:
            session: Database session.
            image_id: Image ID to download file for.
            target_path: Local path to save the file.
            
        Returns:
            True if download successful.
        """
        
        locations = await image_location_repository.get_by_image(session, image_id)
        if not locations:
            return False
        
        endpoints = await storage_endpoint_repository.get_healthy_for_read(session)
        endpoint_map = {ep.id: ep for ep in endpoints}
        
        # Try weighted selection first
        selected = _select_by_weight(locations, endpoint_map)
        if selected:
            endpoint = endpoint_map.get(selected.endpoint_id)
            if endpoint:
                content = await self.download_from_endpoint(selected.object_key, endpoint)
                if content:
                    def _write():
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        with open(target_path, "wb") as f:
                            f.write(content)
                    await asyncio.to_thread(_write)
                    logger.info(f"Downloaded from {endpoint.name} to {target_path}")
                    return True
        
        # Fallback: try remaining endpoints in priority order
        tried = {selected.endpoint_id} if selected else set()
        remaining = [loc for loc in locations if loc.endpoint_id not in tried]
        remaining.sort(key=lambda loc: endpoint_map.get(loc.endpoint_id, StorageEndpoint()).read_priority)
        
        for location in remaining:
            endpoint = endpoint_map.get(location.endpoint_id)
            if not endpoint:
                continue
            content = await self.download_from_endpoint(location.object_key, endpoint)
            if content:
                def _write():
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with open(target_path, "wb") as f:
                        f.write(content)
                await asyncio.to_thread(_write)
                logger.info(f"Downloaded from {endpoint.name} (fallback) to {target_path}")
                return True
        
        return False

    def _build_url(self, endpoint: StorageEndpoint, object_key: str) -> str:
        """Build public URL for an object.
        
        URL 构建优先级：
        1. public_url_prefix - 用于 CDN 或自定义域名
        2. 本地端点 - 使用 /data/{bucket}/... 格式
        3. S3 端点 - 使用 endpoint_url/{bucket}/... 格式
        
        Args:
            endpoint: Storage endpoint configuration.
            object_key: Object key/path.
            
        Returns:
            Public URL string.
        """
        bucket = endpoint.bucket_name or "uploads"
        path_prefix = (endpoint.path_prefix or "").strip("/")
        
        # 构建完整路径（path_prefix + object_key）
        full_path = f"{path_prefix}/{object_key}" if path_prefix else object_key
        
        # 1. 优先使用 public_url_prefix（CDN 或自定义域名）
        if endpoint.public_url_prefix:
            prefix = endpoint.public_url_prefix.rstrip("/")
            if endpoint.provider == StorageProvider.LOCAL:
                # 本地端点需要 /data/ 路由前缀
                return f"{prefix}/data/{bucket}/{full_path}"
            # S3 等远程端点直接拼接
            return f"{prefix}/{bucket}/{full_path}"
        
        # 2. 本地端点使用动态路由
        if endpoint.provider == StorageProvider.LOCAL:
            return f"/data/{bucket}/{full_path}"
        
        # 3. S3 端点使用 endpoint_url
        if endpoint.endpoint_url and bucket:
            base = endpoint.endpoint_url.rstrip("/")
            return f"{base}/{bucket}/{full_path}"
        
        return ""

    async def upload_to_endpoint(
        self,
        file_content: bytes,
        object_key: str,
        endpoint: StorageEndpoint,
    ) -> bool:
        """Upload file content to a specific endpoint.
        
        Args:
            file_content: Raw file bytes.
            object_key: Target object key.
            endpoint: Target endpoint configuration.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            if endpoint.provider == StorageProvider.LOCAL:
                return await self._upload_local(file_content, object_key, endpoint)
            else:
                return await self._upload_s3(file_content, object_key, endpoint)
        except Exception as e:
            logger.error(f"Upload failed to {endpoint.name}: {e}")
            return False

    async def _upload_local(
        self,
        file_content: bytes,
        object_key: str,
        endpoint: StorageEndpoint,
    ) -> bool:
        """Upload to local filesystem."""
        base_path = self._resolve_local_path(endpoint)
        full_key = self._apply_path_prefix(object_key, endpoint.path_prefix)
        full_path = os.path.join(base_path, full_key)
        
        # Create directories
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        # Write file asynchronously
        def _write():
            with open(full_path, "wb") as f:
                f.write(file_content)
        
        await asyncio.to_thread(_write)
        logger.info(f"Uploaded to local: {full_path}")
        return True

    async def _upload_s3(
        self,
        file_content: bytes,
        object_key: str,
        endpoint: StorageEndpoint,
    ) -> bool:
        """Upload to S3-compatible storage."""
        full_key = self._apply_path_prefix(object_key, endpoint.path_prefix)
        
        def _do_upload():
            # Use path style or virtual-hosted based on endpoint config
            addressing_style = "path" if endpoint.path_style else "virtual"
            config = BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": addressing_style},
            )
            
            client = boto3.client(
                "s3",
                endpoint_url=endpoint.endpoint_url,
                aws_access_key_id=endpoint.access_key_id,
                aws_secret_access_key=endpoint.secret_access_key,
                region_name=endpoint.region or "auto",
                config=config,
            )
            
            client.put_object(
                Bucket=endpoint.bucket_name,
                Key=full_key,
                Body=file_content,
            )
        
        await asyncio.to_thread(_do_upload)
        logger.info(f"Uploaded to {endpoint.name}: {object_key}")
        return True

    async def download_from_endpoint(
        self,
        object_key: str,
        endpoint: StorageEndpoint,
    ) -> Optional[bytes]:
        """Download file from a specific endpoint.
        
        Args:
            object_key: Object key to download.
            endpoint: Source endpoint configuration.
            
        Returns:
            File content bytes or None if failed.
        """
        try:
            if endpoint.provider == StorageProvider.LOCAL:
                return await self._download_local(object_key, endpoint)
            else:
                return await self._download_s3(object_key, endpoint)
        except Exception as e:
            logger.error(f"Download failed from {endpoint.name}: {e}")
            return None

    async def _download_local(
        self,
        object_key: str,
        endpoint: StorageEndpoint,
    ) -> Optional[bytes]:
        """Download from local filesystem."""
        base_path = self._resolve_local_path(endpoint)
        full_key = self._apply_path_prefix(object_key, endpoint.path_prefix)
        full_path = os.path.join(base_path, full_key)
        
        if not os.path.exists(full_path):
            return None
        
        def _read():
            with open(full_path, "rb") as f:
                return f.read()
        
        return await asyncio.to_thread(_read)

    async def _download_s3(
        self,
        object_key: str,
        endpoint: StorageEndpoint,
    ) -> Optional[bytes]:
        """Download from S3-compatible storage."""
        full_key = self._apply_path_prefix(object_key, endpoint.path_prefix)
        
        def _do_download():
            addressing_style = "path" if endpoint.path_style else "virtual"
            config = BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": addressing_style},
            )
            
            client = boto3.client(
                "s3",
                endpoint_url=endpoint.endpoint_url,
                aws_access_key_id=endpoint.access_key_id,
                aws_secret_access_key=endpoint.secret_access_key,
                region_name=endpoint.region or "auto",
                config=config,
            )
            
            buffer = io.BytesIO()
            client.download_fileobj(endpoint.bucket_name, full_key, buffer)
            return buffer.getvalue()
        
        return await asyncio.to_thread(_do_download)

    async def file_exists(
        self,
        object_key: str,
        endpoint: StorageEndpoint,
    ) -> bool:
        """Check if file exists on endpoint.
        
        Args:
            object_key: Object key to check.
            endpoint: Target endpoint.
            
        Returns:
            True if file exists.
        """
        try:
            if endpoint.provider == StorageProvider.LOCAL:
                base_path = self._resolve_local_path(endpoint)
                full_key = self._apply_path_prefix(object_key, endpoint.path_prefix)
                full_path = os.path.join(base_path, full_key)
                return os.path.exists(full_path)
            else:
                return await self._s3_file_exists(object_key, endpoint)
        except Exception:
            return False

    async def _s3_file_exists(
        self,
        object_key: str,
        endpoint: StorageEndpoint,
    ) -> bool:
        """Check if file exists in S3."""
        full_key = self._apply_path_prefix(object_key, endpoint.path_prefix)
        
        def _check():
            addressing_style = "path" if endpoint.path_style else "virtual"
            config = BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": addressing_style},
            )
            
            client = boto3.client(
                "s3",
                endpoint_url=endpoint.endpoint_url,
                aws_access_key_id=endpoint.access_key_id,
                aws_secret_access_key=endpoint.secret_access_key,
                region_name=endpoint.region or "auto",
                config=config,
            )
            
            try:
                client.head_object(Bucket=endpoint.bucket_name, Key=full_key)
                return True
            except ClientError:
                return False
        
        return await asyncio.to_thread(_check)

    async def delete_from_endpoint(
        self,
        object_key: str,
        endpoint: StorageEndpoint,
    ) -> bool:
        """Delete file from a specific endpoint.
        
        Args:
            object_key: Object key to delete.
            endpoint: Target endpoint.
            
        Returns:
            True if successful.
        """
        try:
            if endpoint.provider == StorageProvider.LOCAL:
                base_path = self._resolve_local_path(endpoint)
                full_key = self._apply_path_prefix(object_key, endpoint.path_prefix)
                full_path = os.path.join(base_path, full_key)
                if os.path.exists(full_path):
                    os.remove(full_path)
                return True
            else:
                return await self._delete_s3(object_key, endpoint)
        except Exception as e:
            logger.error(f"Delete failed from {endpoint.name}: {e}")
            return False

    async def _delete_s3(
        self,
        object_key: str,
        endpoint: StorageEndpoint,
    ) -> bool:
        """Delete from S3-compatible storage."""
        full_key = self._apply_path_prefix(object_key, endpoint.path_prefix)
        
        def _do_delete():
            addressing_style = "path" if endpoint.path_style else "virtual"
            config = BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": addressing_style},
            )
            
            client = boto3.client(
                "s3",
                endpoint_url=endpoint.endpoint_url,
                aws_access_key_id=endpoint.access_key_id,
                aws_secret_access_key=endpoint.secret_access_key,
                region_name=endpoint.region or "auto",
                config=config,
            )
            
            client.delete_object(Bucket=endpoint.bucket_name, Key=full_key)
        
        await asyncio.to_thread(_do_delete)
        return True

    async def copy_between_endpoints(
        self,
        session,
        image_id: int,
        source_endpoint: StorageEndpoint,
        target_endpoint: StorageEndpoint,
        object_key: str,
    ) -> bool:
        """在端点之间复制文件并创建 location 记录。
        
        Args:
            session: Database session.
            image_id: 图片ID.
            source_endpoint: 源端点.
            target_endpoint: 目标端点.
            object_key: 对象键.
            
        Returns:
            True if successful.
        """
        try:
            # 下载源文件
            content = await self.download_from_endpoint(object_key, source_endpoint)
            if not content:
                logger.warning(f"无法从端点 {source_endpoint.name} 下载 {object_key}")
                return False
            
            # 上传到目标端点
            success = await self.upload_to_endpoint(content, object_key, target_endpoint)
            if not success:
                return False
            
            # 创建 location 记录
            from imgtag.models.image_location import ImageLocation
            from datetime import datetime, timezone
            
            location = ImageLocation(
                image_id=image_id,
                endpoint_id=target_endpoint.id,
                object_key=object_key,
                is_primary=False,  # 备份不是主存储
                sync_status="synced",
                synced_at=datetime.now(timezone.utc),
            )
            session.add(location)
            await session.flush()
            
            logger.info(f"图片 {image_id} 已复制到端点 {target_endpoint.name}")
            return True
        except Exception as e:
            logger.error(f"复制图片 {image_id} 到 {target_endpoint.name} 失败: {e}")
            return False

    @staticmethod
    def compute_file_hash(content: bytes) -> str:
        """Compute MD5 hash of file content.
        
        Args:
            content: File content bytes.
            
        Returns:
            Hex-encoded MD5 hash string.
        """
        return hashlib.md5(content).hexdigest()


# Singleton instance
storage_service = StorageService()
