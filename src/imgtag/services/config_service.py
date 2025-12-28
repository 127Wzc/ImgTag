"""Configuration Service - Business Logic Layer.

Provides write operations and initialization for application configuration.
Depends on config_cache for read operations.

Architecture:
    config_cache ← read operations (cached)
    config_service ← write operations, initialization
    config_repository ← API endpoint data access (with session)
"""

from typing import Any

from sqlalchemy import select

from imgtag.core.config_cache import config_cache
from imgtag.core.config_defaults import DEFAULT_CONFIG
from imgtag.core.logging_config import get_logger
from imgtag.db.database import async_session_maker
from imgtag.models.config import Config

logger = get_logger(__name__)


class ConfigService:
    """Configuration service for write operations and initialization.
    
    For read operations, use config_cache directly.
    """
    
    # ==================== Write Operations ====================
    
    @classmethod
    async def set(
        cls,
        key: str,
        value: str,
        is_secret: bool | None = None,
    ) -> bool:
        """Set configuration value.
        
        Args:
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
            
            async with async_session_maker() as session:
                stmt = select(Config).where(Config.key == key)
                result = await session.execute(stmt)
                config = result.scalar_one_or_none()
                
                if config:
                    config.value = value
                    if is_secret is not None:
                        config.is_secret = is_secret
                else:
                    config = Config(key=key, value=value, is_secret=is_secret)
                    session.add(config)
                
                await session.commit()
            
            # Clear cache to ensure fresh reads
            config_cache.clear()
            logger.info(f"配置已更新: {key}")
            return True
        except Exception as e:
            logger.error(f"设置配置失败 [{key}]: {e}")
            return False
    
    @classmethod
    async def set_multiple(cls, configs: dict[str, str]) -> bool:
        """Batch update multiple configurations."""
        try:
            for key, value in configs.items():
                await cls.set(key, value)
            logger.info(f"批量更新配置成功: {list(configs.keys())}")
            return True
        except Exception as e:
            logger.error(f"批量更新配置失败: {e}")
            return False
    
    # ==================== Read Operations (delegated to cache) ====================
    
    @classmethod
    async def get(cls, key: str, default: str | None = None) -> str | None:
        """Get configuration value (delegates to config_cache)."""
        return await config_cache.get(key, default)
    
    @classmethod
    async def get_all(cls, include_secrets: bool = False) -> dict[str, Any]:
        """Get all configuration as dictionary."""
        try:
            async with async_session_maker() as session:
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
        except Exception as e:
            logger.error(f"获取所有配置失败: {e}")
            return {}
    
    # ==================== Initialization ====================
    
    @classmethod
    async def ensure_defaults(cls) -> None:
        """Ensure all default configurations exist in database."""
        try:
            async with async_session_maker() as session:
                for key, value in DEFAULT_CONFIG.items():
                    stmt = select(Config).where(Config.key == key)
                    result = await session.execute(stmt)
                    existing = result.scalar_one_or_none()
                    
                    if not existing:
                        is_secret = "key" in key.lower() or "secret" in key.lower()
                        config = Config(key=key, value=value, is_secret=is_secret)
                        session.add(config)
                
                await session.commit()
                logger.info("默认配置已确保存在")
        except Exception as e:
            logger.error(f"确保默认配置失败: {e}")


# Global service instance
config_service = ConfigService
