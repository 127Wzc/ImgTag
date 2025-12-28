"""Configuration cache with TTL-based caching.

This is a CORE infrastructure module that directly uses SQLAlchemy queries.
It does NOT depend on any repositories or services to avoid circular imports.

Dependency hierarchy:
    config_defaults ← config_cache ← config_service ← API endpoints
                    ↑
                (repositories can also use config_cache)
"""

import time
from typing import Any

from sqlalchemy import select

from imgtag.core.config_defaults import DEFAULT_CONFIG
from imgtag.core.logging_config import get_logger
from imgtag.db.database import async_session_maker
from imgtag.models.config import Config

logger = get_logger(__name__)


class ConfigCache:
    """Cached configuration reader.
    
    Configuration values are cached for a configurable TTL to avoid
    repeated database queries. Cache is automatically refreshed when stale.
    
    This class directly queries the Config model instead of using
    ConfigRepository to avoid circular imports.
    """
    
    _cache: dict[str, str] = {}
    _cache_time: float = 0
    _ttl: float = 30.0  # Cache TTL in seconds
    
    # ==================== Async Read Operations ====================
    
    @classmethod
    async def get(cls, key: str, default: str | None = None) -> str | None:
        """Get configuration value with caching.
        
        Args:
            key: Configuration key.
            default: Default value if not found.
            
        Returns:
            Configuration value or default.
        """
        now = time.time()
        
        # Check cache first
        if now - cls._cache_time < cls._ttl and key in cls._cache:
            return cls._cache.get(key, default)
        
        # Query database directly (no repository dependency)
        try:
            async with async_session_maker() as session:
                stmt = select(Config.value).where(Config.key == key)
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                
                # Use default from DEFAULT_CONFIG if not in database
                if row is None:
                    value = default if default is not None else DEFAULT_CONFIG.get(key)
                else:
                    value = row
                    
                cls._cache[key] = value
                cls._cache_time = now
                return value
        except Exception as e:
            logger.warning(f"配置读取失败 [{key}]: {e}")
            return cls._cache.get(key, default)
    
    @classmethod
    async def get_int(cls, key: str, default: int = 0) -> int:
        """Get configuration value as integer."""
        value = await cls.get(key, str(default))
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    
    @classmethod
    async def get_float(cls, key: str, default: float = 0.0) -> float:
        """Get configuration value as float."""
        value = await cls.get(key, str(default))
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    @classmethod
    async def get_bool(cls, key: str, default: bool = False) -> bool:
        """Get configuration value as boolean."""
        value = await cls.get(key)
        if value is None:
            return default
        return value.lower() in ("true", "1", "yes", "on")
    
    # ==================== Sync Read Operations ====================
    
    @classmethod
    def get_sync(cls, key: str, default: str | None = None) -> str | None:
        """Get configuration value synchronously (cache-only).
        
        Does NOT block to query database. Use preload() at startup.
        """
        if key in cls._cache:
            return cls._cache.get(key, default)
        
        logger.warning(
            f"配置缓存未命中 [{key}]，返回默认值 '{default}'。"
            f"请确保应用启动时已调用 preload()。"
        )
        return default
    
    # ==================== Cache Management ====================
    
    @classmethod
    async def preload(cls) -> None:
        """Preload all configuration values into cache.
        
        Call this at application startup to ensure get_sync() works.
        """
        try:
            async with async_session_maker() as session:
                stmt = select(Config.key, Config.value)
                result = await session.execute(stmt)
                rows = result.fetchall()
                for key, value in rows:
                    cls._cache[key] = value
                cls._cache_time = time.time()
                logger.info(f"配置缓存已预加载 ({len(rows)} 项)")
        except Exception as e:
            logger.warning(f"预加载配置缓存失败: {e}")
    
    @classmethod
    def clear(cls) -> None:
        """Clear the configuration cache."""
        cls._cache.clear()
        cls._cache_time = 0
        logger.info("配置缓存已清除")
    
    @classmethod
    async def refresh(cls) -> None:
        """Force refresh - mark cache as stale."""
        cls._cache_time = 0
        logger.info("配置缓存已标记为过期")


# Convenience alias
config_cache = ConfigCache
