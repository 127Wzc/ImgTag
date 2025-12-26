"""Config repository for configuration management.

Provides async access to application configuration stored in database.
"""

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.logging_config import get_logger
from imgtag.db.repositories.base import BaseRepository
from imgtag.models.config import Config

logger = get_logger(__name__)


# 默认配置值
DEFAULT_CONFIG: dict[str, str] = {
    # 视觉模型配置
    "vision_api_base_url": "https://api.openai.com/v1",
    "vision_api_key": "",
    "vision_model": "gpt-4o-mini",
    "vision_max_image_size": "2048",  # 最大图片大小 KB
    "vision_allowed_extensions": "jpg,jpeg,png,webp,bmp",
    "vision_convert_gif": "true",
    "vision_prompt": """请分析这张图片，并按以下格式返回JSON响应:
{
    "tags": ["标签1", "标签2", "标签3", ...],
    "description": "详细的图片描述文本"
}

要求：
1. tags: 提取5-10个关键标签，使用中文
2. description: 用中文详细描述图片内容

请只返回JSON格式，不要添加任何其他文字。""",
    # 嵌入模型配置
    "embedding_mode": "local",
    "embedding_local_model": "BAAI/bge-small-zh-v1.5",
    "hf_endpoint": "https://hf-mirror.com",
    "embedding_api_base_url": "https://api.openai.com/v1",
    "embedding_api_key": "",
    "embedding_model": "text-embedding-3-small",
    "embedding_dimensions": "512",
    # 队列配置
    "queue_max_workers": "2",
    "queue_batch_interval": "1",
    # 上传配置
    "max_upload_size": "10",
    # S3 存储配置
    "s3_enabled": "false",
    "s3_endpoint_url": "",
    "s3_access_key_id": "",
    "s3_secret_access_key": "",
    "s3_bucket_name": "",
    "s3_region": "us-east-1",
    "s3_public_url_prefix": "",
    "s3_path_prefix": "imgtag/",
    "image_url_priority": "auto",
    # 系统配置
    "base_url": "",
    "allow_register": "true",
}


class ConfigRepository(BaseRepository[Config]):
    """Repository for application configuration.

    Provides methods right at SQLAlchemy 2.0 async style.
    """

    model = Config

    async def get_value(
        self,
        session: AsyncSession,
        key: str,
        default: str | None = None,
    ) -> str | None:
        """Get configuration value by key.

        Args:
            session: Database session.
            key: Configuration key.
            default: Default value if not found.

        Returns:
            Configuration value or default.
        """
        config = await self.get_by_id(session, key)
        if config:
            return config.value
        return default if default is not None else DEFAULT_CONFIG.get(key)

    async def get_int(
        self,
        session: AsyncSession,
        key: str,
        default: int = 0,
    ) -> int:
        """Get configuration value as integer.

        Args:
            session: Database session.
            key: Configuration key.
            default: Default value if not found or not a valid integer.

        Returns:
            Integer value.
        """
        value = await self.get_value(session, key)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            return default

    async def set_value(
        self,
        session: AsyncSession,
        key: str,
        value: str,
        is_secret: bool | None = None,
    ) -> bool:
        """Set configuration value.

        Args:
            session: Database session.
            key: Configuration key.
            value: Configuration value.
            is_secret: Whether this is a secret (auto-detected if None).

        Returns:
            True if successful.
        """
        try:
            # Auto-detect secret based on key name
            if is_secret is None:
                is_secret = "key" in key.lower() or "secret" in key.lower()

            config = await self.get_by_id(session, key)
            if config:
                config.value = value
                if is_secret is not None:
                    config.is_secret = is_secret
            else:
                config = Config(key=key, value=value, is_secret=is_secret)
                session.add(config)

            await session.flush()
            logger.info(f"配置已更新: {key}")
            return True
        except Exception as e:
            logger.error(f"设置配置失败 [{key}]: {e}")
            return False

    async def get_all_configs(
        self,
        session: AsyncSession,
        include_secrets: bool = False,
    ) -> dict[str, Any]:
        """Get all configuration as dictionary.

        Args:
            session: Database session.
            include_secrets: Whether to include secret values.

        Returns:
            Dictionary of all configurations.
        """
        stmt = select(Config).order_by(Config.key)
        result = await session.execute(stmt)
        configs = result.scalars().all()

        output: dict[str, Any] = {}
        for config in configs:
            if config.is_secret and not include_secrets:
                output[config.key] = "******" if config.value else ""
            else:
                output[config.key] = config.value

        return output

    async def update_multiple(
        self,
        session: AsyncSession,
        configs: dict[str, str],
    ) -> bool:
        """Batch update multiple configurations.

        Args:
            session: Database session.
            configs: Dictionary of key-value pairs to update.

        Returns:
            True if all updates successful.
        """
        try:
            for key, value in configs.items():
                await self.set_value(session, key, value)
            logger.info(f"批量更新配置成功: {list(configs.keys())}")
            return True
        except Exception as e:
            logger.error(f"批量更新配置失败: {e}")
            return False

    async def ensure_defaults(self, session: AsyncSession) -> None:
        """Ensure all default configurations exist.

        Args:
            session: Database session.
        """
        for key, value in DEFAULT_CONFIG.items():
            existing = await self.get_by_id(session, key)
            if not existing:
                is_secret = "key" in key.lower() or "secret" in key.lower()
                config = Config(key=key, value=value, is_secret=is_secret)
                session.add(config)
        await session.flush()
        logger.info("默认配置已确保存在")


# Global repository instance
config_repository = ConfigRepository()
