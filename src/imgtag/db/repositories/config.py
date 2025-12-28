"""Config repository for configuration management.

Provides async access to application configuration stored in database.

NOTE: For cached config access, prefer using ConfigService directly.
This repository is mainly for API endpoints that need session-based operations.
"""

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.config_defaults import DEFAULT_CONFIG
from imgtag.core.logging_config import get_logger
from imgtag.db.repositories.base import BaseRepository
from imgtag.models.config import Config

logger = get_logger(__name__)


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
