"""Configuration helper for services.

Provides a cached async config reader for service layer usage.
Cache avoids repeated database queries for frequently accessed config values.
"""

import time
from typing import Any

from imgtag.core.logging_config import get_logger
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import config_repository

logger = get_logger(__name__)


class ConfigCache:
    """Cached configuration reader for services.
    
    Configuration values are cached for a configurable TTL to avoid
    repeated database queries. Cache is automatically refreshed when stale.
    """
    
    _cache: dict[str, str] = {}
    _cache_time: float = 0
    _ttl: float = 30.0  # Cache TTL in seconds
    _loading: bool = False  # 防止重复加载
    
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
        
        # Check cache
        if now - cls._cache_time < cls._ttl and key in cls._cache:
            return cls._cache.get(key, default)
        
        # Refresh cache
        try:
            async with async_session_maker() as session:
                value = await config_repository.get_value(session, key, default)
                cls._cache[key] = value
                cls._cache_time = now
                return value
        except Exception as e:
            logger.warning(f"配置读取失败 [{key}]: {e}")
            return cls._cache.get(key, default)
    
    @classmethod
    async def preload(cls) -> None:
        """Preload all configuration values into cache.
        
        Call this at application startup to ensure get_sync() works correctly.
        """
        try:
            async with async_session_maker() as session:
                # 必须 include_secrets=True 才能加载 API Key 等敏感配置
                all_configs = await config_repository.get_all_configs(session, include_secrets=True)
                for key, value in all_configs.items():
                    cls._cache[key] = value
                cls._cache_time = time.time()
                logger.info(f"配置缓存已预加载 ({len(all_configs)} 项)")
        except Exception as e:
            logger.warning(f"预加载配置缓存失败: {e}")
    
    @classmethod
    def get_sync(cls, key: str, default: str | None = None) -> str | None:
        """Get configuration value synchronously (cache-only, non-blocking).
        
        First tries cache. If cache is empty, logs a warning and returns default.
        Does NOT block to fetch from database - use preload() at startup instead.
        
        Args:
            key: Configuration key.
            default: Default value if not found.
            
        Returns:
            Configuration value or default.
        """
        # 从缓存读取
        if key in cls._cache:
            return cls._cache.get(key, default)
        
        # 缓存中没有，输出警告并返回默认值
        # 不阻塞！调用者应确保 preload() 已在启动时执行
        if not cls._loading:
            logger.warning(
                f"配置缓存未命中 [{key}]，返回默认值 '{default}'。"
                f"请确保应用启动时已调用 preload()。"
            )
        return default
    
    @classmethod
    def clear(cls) -> None:
        """Clear the configuration cache.
        
        Call this after updating configuration in database to ensure
        fresh values are loaded on next access.
        """
        cls._cache.clear()
        cls._cache_time = 0
        logger.debug("配置缓存已清除")
    
    @classmethod
    async def get_int(cls, key: str, default: int = 0) -> int:
        """Get configuration value as integer.
        
        Args:
            key: Configuration key.
            default: Default value if not found or invalid.
            
        Returns:
            Integer value.
        """
        value = await cls.get(key, str(default))
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    
    @classmethod
    async def get_float(cls, key: str, default: float = 0.0) -> float:
        """Get configuration value as float.
        
        Args:
            key: Configuration key.
            default: Default value if not found or invalid.
            
        Returns:
            Float value.
        """
        value = await cls.get(key, str(default))
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    @classmethod
    async def get_bool(cls, key: str, default: bool = False) -> bool:
        """Get configuration value as boolean.
        
        Args:
            key: Configuration key.
            default: Default value if not found or invalid.
            
        Returns:
            Boolean value.
        """
        value = await cls.get(key)
        if value is None:
            return default
        return value.lower() in ("true", "1", "yes", "on")
    
    @classmethod
    def clear(cls) -> None:
        """Clear the configuration cache."""
        cls._cache.clear()
        cls._cache_time = 0
        logger.info("配置缓存已清除")
    
    @classmethod
    async def refresh(cls) -> None:
        """Force refresh all cached values."""
        cls._cache_time = 0  # Mark cache as stale
        logger.info("配置缓存已标记为过期")


# Convenience alias
config_cache = ConfigCache
