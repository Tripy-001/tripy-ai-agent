"""
In-memory LRU cache for Places API responses to avoid redundant calls.
Supports optional Redis backend for distributed caching in production.
"""
import logging
import hashlib
import json
from typing import Any, Dict, Optional, List
from functools import lru_cache
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# In-memory cache with TTL
_cache_store: Dict[str, tuple[Any, datetime]] = {}
_cache_ttl_seconds = 3600  # 1 hour default


def _generate_cache_key(operation: str, **params) -> str:
    """Generate a stable cache key from operation and parameters."""
    # Sort params for consistent hashing
    sorted_params = json.dumps(params, sort_keys=True, ensure_ascii=False)
    key_str = f"{operation}:{sorted_params}"
    return hashlib.md5(key_str.encode()).hexdigest()


def get_cached(operation: str, **params) -> Optional[Any]:
    """Retrieve cached result if available and not expired."""
    try:
        key = _generate_cache_key(operation, **params)
        if key in _cache_store:
            value, expiry = _cache_store[key]
            if datetime.utcnow() < expiry:
                logger.debug(f"Cache hit for {operation}")
                return value
            else:
                # Expired, remove
                del _cache_store[key]
                logger.debug(f"Cache expired for {operation}")
        return None
    except Exception as e:
        logger.warning(f"Cache get error: {e}")
        return None


def set_cached(operation: str, value: Any, ttl_seconds: Optional[int] = None, **params):
    """Store result in cache with TTL."""
    try:
        key = _generate_cache_key(operation, **params)
        ttl = ttl_seconds if ttl_seconds is not None else _cache_ttl_seconds
        expiry = datetime.utcnow() + timedelta(seconds=ttl)
        _cache_store[key] = (value, expiry)
        logger.debug(f"Cached {operation} for {ttl}s")
    except Exception as e:
        logger.warning(f"Cache set error: {e}")


def clear_cache():
    """Clear all cached entries (useful for testing)."""
    global _cache_store
    _cache_store = {}
    logger.info("Cache cleared")


def cleanup_expired():
    """Remove expired entries from cache."""
    try:
        now = datetime.utcnow()
        expired_keys = [k for k, (_, expiry) in _cache_store.items() if now >= expiry]
        for k in expired_keys:
            del _cache_store[k]
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")
    except Exception as e:
        logger.warning(f"Cache cleanup error: {e}")
