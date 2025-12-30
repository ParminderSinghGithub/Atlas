"""
Redis cache for features (optional).

Why Redis:
- Distributed cache (shared across service instances)
- Reduces memory pressure (can evict LRU)
- Optional (service works without it)

Critical: Redis failures must NOT break requests.
"""
from typing import Optional, Dict, Any
import json
import redis
from app.core.config import settings
from app.core.logging import get_logger, log_cache_error

logger = get_logger(__name__)


class RedisCache:
    """
    Optional Redis cache for features.
    
    Production considerations:
    - Redis is an optimization, not a requirement
    - All operations wrapped in try/except
    - Service continues if Redis unavailable
    - TTL prevents stale data
    """
    
    def __init__(self):
        self.client: Optional[redis.Redis] = None
        self.enabled = settings.redis_enabled
        
        if self.enabled:
            try:
                self.client = redis.from_url(
                    settings.redis_url,
                    decode_responses=True,  # Return strings not bytes
                    socket_connect_timeout=1,  # Fast fail
                    socket_timeout=1
                )
                # Test connection
                self.client.ping()
                logger.info(f"Redis cache enabled | url={settings.redis_url}")
            except Exception as e:
                logger.warning(f"Redis connection failed (continuing without cache): {e}")
                self.enabled = False
                self.client = None
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Get value from cache.
        
        Returns:
            Dict if found, None if miss or error
        
        Why swallow errors:
        - Cache miss is not an error
        - Redis timeout should not break request
        - Caller has fallback (load from Parquet)
        """
        if not self.enabled or self.client is None:
            return None
        
        try:
            value = self.client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            log_cache_error(logger, e)
            return None
    
    def set(self, key: str, value: Dict[str, Any], ttl: Optional[int] = None):
        """
        Set value in cache with TTL.
        
        Args:
            key: Cache key
            value: Dict to cache
            ttl: Time-to-live in seconds (default from config)
        
        Why TTL required:
        - Prevents stale features
        - Bounded memory usage
        - Aligns with feature refresh schedule
        """
        if not self.enabled or self.client is None:
            return
        
        try:
            serialized = json.dumps(value)
            ttl = ttl or settings.redis_ttl_seconds
            self.client.setex(key, ttl, serialized)
        except Exception as e:
            log_cache_error(logger, e)
    
    def mget(self, keys: list) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Get multiple values (batch operation).
        
        Why batch:
        - Reduce round-trips (1 request vs N)
        - Faster for bulk feature loading
        
        Returns:
            Dict of key → value (value is None if miss)
        """
        if not self.enabled or self.client is None:
            return {k: None for k in keys}
        
        try:
            values = self.client.mget(keys)
            return {
                key: json.loads(val) if val else None
                for key, val in zip(keys, values)
            }
        except Exception as e:
            log_cache_error(logger, e)
            return {k: None for k in keys}
    
    def mset(self, mapping: Dict[str, Dict[str, Any]], ttl: Optional[int] = None):
        """
        Set multiple values (batch operation).
        
        Why batch:
        - Reduce round-trips
        - Atomic operation (all or nothing)
        """
        if not self.enabled or self.client is None:
            return
        
        try:
            # Redis mset doesn't support TTL, so use pipeline
            ttl = ttl or settings.redis_ttl_seconds
            pipe = self.client.pipeline()
            for key, value in mapping.items():
                serialized = json.dumps(value)
                pipe.setex(key, ttl, serialized)
            pipe.execute()
        except Exception as e:
            log_cache_error(logger, e)
    
    def delete(self, key: str):
        """Delete key from cache."""
        if not self.enabled or self.client is None:
            return
        
        try:
            self.client.delete(key)
        except Exception as e:
            log_cache_error(logger, e)
    
    def flush_all(self):
        """
        Clear entire cache.
        
        Why dangerous:
        - Affects all services using same Redis instance
        - Only use in dev/staging
        - Production: use targeted deletes or TTL expiry
        """
        if not self.enabled or self.client is None:
            return
        
        try:
            self.client.flushdb()
            logger.warning("Redis cache flushed (all keys deleted)")
        except Exception as e:
            log_cache_error(logger, e)


# Global instance
_cache_instance: Optional[RedisCache] = None


def get_cache() -> RedisCache:
    """Get or create global Redis cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = RedisCache()
    return _cache_instance
