"""Category code cache for efficient lookup.

Provides caching for level=0 category codes to avoid repeated
database queries during uploads.
"""

from typing import Optional

from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)

# In-memory cache: {category_id: code}
_CATEGORY_CODE_CACHE: dict[int, Optional[str]] = {}


async def get_category_code_cached(
    session,
    category_id: int,
) -> Optional[str]:
    """Get category code with caching.
    
    Args:
        session: Database session.
        category_id: Tag ID (must be level=0 category).
        
    Returns:
        Category code string or None if not a category.
    """
    if category_id in _CATEGORY_CODE_CACHE:
        return _CATEGORY_CODE_CACHE[category_id]
    
    # Import here to avoid circular dependency
    from imgtag.db.repositories import tag_repository
    
    category = await tag_repository.get_by_id(session, category_id)
    if category and category.level == 0:
        _CATEGORY_CODE_CACHE[category_id] = category.code
        logger.debug(f"Cached category code: {category_id} -> {category.code}")
        return category.code
    
    return None


def invalidate_category_cache(category_id: int) -> None:
    """Invalidate cache for a specific category.
    
    Call this when a category's code is updated.
    
    Args:
        category_id: Tag ID to invalidate.
    """
    if category_id in _CATEGORY_CODE_CACHE:
        old_value = _CATEGORY_CODE_CACHE.pop(category_id)
        logger.debug(f"Invalidated category cache: {category_id} (was: {old_value})")


def clear_category_cache() -> None:
    """Clear all cached category codes.
    
    Useful for testing or full cache refresh.
    """
    _CATEGORY_CODE_CACHE.clear()
    logger.debug("Cleared all category code cache")


def get_cache_stats() -> dict:
    """Get cache statistics for monitoring.
    
    Returns:
        Dict with cache size and entries.
    """
    return {
        "size": len(_CATEGORY_CODE_CACHE),
        "entries": dict(_CATEGORY_CODE_CACHE),
    }
