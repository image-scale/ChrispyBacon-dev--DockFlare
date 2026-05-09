"""
Cache layer with Redis and in-memory fallback.

Provides caching for DNS records, zone data, and API responses
with support for TTL-based expiration and namespacing.
"""

import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from . import settings


@dataclass
class CacheEntry:
    """Entry in the cache with value and expiration."""

    value: Any
    expires_at: float = 0

    @property
    def is_expired(self) -> bool:
        """Check if the entry has expired."""
        if self.expires_at == 0:
            return False
        return time.time() > self.expires_at


class CacheBackend(ABC):
    """Abstract base class for cache backends."""

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Get a value from the cache."""
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl: int = 0) -> bool:
        """Set a value in the cache with optional TTL in seconds."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a key from the cache."""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        pass

    @abstractmethod
    def clear(self) -> bool:
        """Clear all entries from the cache."""
        pass

    @abstractmethod
    def keys(self, pattern: str = "*") -> List[str]:
        """Get keys matching a pattern."""
        pass


class MemoryCache(CacheBackend):
    """In-memory cache implementation with TTL support."""

    def __init__(self, max_size: int = 10000):
        """
        Initialize the memory cache.

        Args:
            max_size: Maximum number of entries to store
        """
        self._data: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._lock = threading.RLock()

    def get(self, key: str) -> Optional[Any]:
        """Get a value from the cache."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None

            if entry.is_expired:
                del self._data[key]
                return None

            return entry.value

    def set(self, key: str, value: Any, ttl: int = 0) -> bool:
        """Set a value in the cache."""
        with self._lock:
            if len(self._data) >= self._max_size and key not in self._data:
                self._evict_expired()

                if len(self._data) >= self._max_size:
                    oldest_key = next(iter(self._data))
                    del self._data[oldest_key]

            expires_at = time.time() + ttl if ttl > 0 else 0
            self._data[key] = CacheEntry(value=value, expires_at=expires_at)
            return True

    def delete(self, key: str) -> bool:
        """Delete a key from the cache."""
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    def exists(self, key: str) -> bool:
        """Check if a key exists and is not expired."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return False

            if entry.is_expired:
                del self._data[key]
                return False

            return True

    def clear(self) -> bool:
        """Clear all entries."""
        with self._lock:
            self._data.clear()
            return True

    def keys(self, pattern: str = "*") -> List[str]:
        """Get keys matching a pattern (supports * wildcard)."""
        import fnmatch

        with self._lock:
            self._evict_expired()

            if pattern == "*":
                return list(self._data.keys())

            return [k for k in self._data.keys() if fnmatch.fnmatch(k, pattern)]

    def _evict_expired(self):
        """Remove expired entries."""
        expired_keys = [
            k for k, v in self._data.items() if v.is_expired
        ]
        for key in expired_keys:
            del self._data[key]

    @property
    def size(self) -> int:
        """Get the current number of entries."""
        with self._lock:
            return len(self._data)


class RedisCache(CacheBackend):
    """Redis-backed cache implementation."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str = None,
        prefix: str = "dockflare:",
        socket_timeout: float = 5.0,
        connection_pool=None,
    ):
        """
        Initialize the Redis cache.

        Args:
            host: Redis host
            port: Redis port
            db: Redis database index
            password: Redis password
            prefix: Key prefix for namespacing
            socket_timeout: Socket timeout in seconds
            connection_pool: Optional existing connection pool
        """
        self._prefix = prefix
        self._client = None
        self._connection_error = None

        try:
            import redis

            if connection_pool:
                self._client = redis.Redis(connection_pool=connection_pool)
            else:
                self._client = redis.Redis(
                    host=host,
                    port=port,
                    db=db,
                    password=password,
                    socket_timeout=socket_timeout,
                    decode_responses=False,
                )
            self._client.ping()
            logging.info(f"Connected to Redis at {host}:{port}")
        except ImportError:
            logging.warning("Redis package not installed, Redis cache unavailable")
            self._connection_error = "Redis package not installed"
        except Exception as e:
            logging.warning(f"Failed to connect to Redis: {e}")
            self._connection_error = str(e)

    @property
    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        if self._client is None:
            return False
        try:
            self._client.ping()
            return True
        except Exception:
            return False

    def _make_key(self, key: str) -> str:
        """Create a namespaced key."""
        return f"{self._prefix}{key}"

    def get(self, key: str) -> Optional[Any]:
        """Get a value from Redis."""
        if not self._client:
            return None

        try:
            full_key = self._make_key(key)
            data = self._client.get(full_key)
            if data is None:
                return None

            return json.loads(data)
        except Exception as e:
            logging.debug(f"Redis get error for {key}: {e}")
            return None

    def set(self, key: str, value: Any, ttl: int = 0) -> bool:
        """Set a value in Redis."""
        if not self._client:
            return False

        try:
            full_key = self._make_key(key)
            data = json.dumps(value)

            if ttl > 0:
                self._client.setex(full_key, ttl, data)
            else:
                self._client.set(full_key, data)

            return True
        except Exception as e:
            logging.debug(f"Redis set error for {key}: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete a key from Redis."""
        if not self._client:
            return False

        try:
            full_key = self._make_key(key)
            result = self._client.delete(full_key)
            return result > 0
        except Exception as e:
            logging.debug(f"Redis delete error for {key}: {e}")
            return False

    def exists(self, key: str) -> bool:
        """Check if a key exists in Redis."""
        if not self._client:
            return False

        try:
            full_key = self._make_key(key)
            return self._client.exists(full_key) > 0
        except Exception as e:
            logging.debug(f"Redis exists error for {key}: {e}")
            return False

    def clear(self) -> bool:
        """Clear all keys with our prefix."""
        if not self._client:
            return False

        try:
            pattern = f"{self._prefix}*"
            cursor = 0
            while True:
                cursor, keys = self._client.scan(cursor, match=pattern, count=100)
                if keys:
                    self._client.delete(*keys)
                if cursor == 0:
                    break
            return True
        except Exception as e:
            logging.debug(f"Redis clear error: {e}")
            return False

    def keys(self, pattern: str = "*") -> List[str]:
        """Get keys matching a pattern."""
        if not self._client:
            return []

        try:
            full_pattern = self._make_key(pattern)
            all_keys = []
            cursor = 0
            while True:
                cursor, keys = self._client.scan(cursor, match=full_pattern, count=100)
                all_keys.extend(
                    k.decode("utf-8")[len(self._prefix) :] if isinstance(k, bytes) else k[len(self._prefix) :]
                    for k in keys
                )
                if cursor == 0:
                    break
            return all_keys
        except Exception as e:
            logging.debug(f"Redis keys error: {e}")
            return []


class CacheManager:
    """
    Cache manager with fallback support.

    Uses Redis as primary cache if available, falls back to memory cache.
    Supports namespacing for different data types.
    """

    def __init__(
        self,
        redis_host: str = None,
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: str = None,
        default_ttl: int = 300,
        memory_max_size: int = 10000,
    ):
        """
        Initialize the cache manager.

        Args:
            redis_host: Redis host (None to skip Redis)
            redis_port: Redis port
            redis_db: Redis database index
            redis_password: Redis password
            default_ttl: Default TTL in seconds
            memory_max_size: Max entries for memory cache
        """
        self._default_ttl = default_ttl
        self._memory = MemoryCache(max_size=memory_max_size)
        self._redis: Optional[RedisCache] = None

        if redis_host:
            self._redis = RedisCache(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password,
            )

    @property
    def primary_backend(self) -> CacheBackend:
        """Get the primary cache backend."""
        if self._redis and self._redis.is_connected:
            return self._redis
        return self._memory

    @property
    def using_redis(self) -> bool:
        """Check if Redis is being used as primary."""
        return self._redis is not None and self._redis.is_connected

    def get(self, key: str, namespace: str = None) -> Optional[Any]:
        """
        Get a value from the cache.

        Args:
            key: Cache key
            namespace: Optional namespace prefix

        Returns:
            Cached value or None
        """
        full_key = f"{namespace}:{key}" if namespace else key
        return self.primary_backend.get(full_key)

    def set(
        self,
        key: str,
        value: Any,
        ttl: int = None,
        namespace: str = None,
    ) -> bool:
        """
        Set a value in the cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: TTL in seconds (uses default if not specified)
            namespace: Optional namespace prefix

        Returns:
            True if set successfully
        """
        full_key = f"{namespace}:{key}" if namespace else key
        effective_ttl = ttl if ttl is not None else self._default_ttl
        return self.primary_backend.set(full_key, value, effective_ttl)

    def delete(self, key: str, namespace: str = None) -> bool:
        """Delete a key from the cache."""
        full_key = f"{namespace}:{key}" if namespace else key
        return self.primary_backend.delete(full_key)

    def exists(self, key: str, namespace: str = None) -> bool:
        """Check if a key exists in the cache."""
        full_key = f"{namespace}:{key}" if namespace else key
        return self.primary_backend.exists(full_key)

    def clear_namespace(self, namespace: str) -> bool:
        """Clear all keys in a namespace."""
        pattern = f"{namespace}:*"
        keys = self.primary_backend.keys(pattern)
        for key in keys:
            self.primary_backend.delete(key)
        return True

    def clear_all(self) -> bool:
        """Clear all cache entries."""
        return self.primary_backend.clear()

    def get_or_set(
        self,
        key: str,
        factory,
        ttl: int = None,
        namespace: str = None,
    ) -> Any:
        """
        Get a value from cache or compute and store it.

        Args:
            key: Cache key
            factory: Callable to generate the value if not cached
            ttl: TTL in seconds
            namespace: Optional namespace prefix

        Returns:
            Cached or computed value
        """
        value = self.get(key, namespace=namespace)
        if value is not None:
            return value

        value = factory()
        if value is not None:
            self.set(key, value, ttl=ttl, namespace=namespace)

        return value


NAMESPACE_ZONES = "zones"
NAMESPACE_DNS = "dns"
NAMESPACE_TUNNELS = "tunnels"
NAMESPACE_API = "api"


_cache_manager: Optional[CacheManager] = None


def get_cache() -> CacheManager:
    """Get or create the default cache manager."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager(
            redis_host=settings.REDIS_HOST if hasattr(settings, "REDIS_HOST") else None,
            redis_port=getattr(settings, "REDIS_PORT", 6379),
            redis_db=getattr(settings, "REDIS_DB_INDEX", 0),
            redis_password=getattr(settings, "REDIS_PASSWORD", None),
            default_ttl=getattr(settings, "CACHE_TTL_SECONDS", 300),
        )
    return _cache_manager


def cache_zone_id(zone_name: str, zone_id: str, ttl: int = 3600) -> bool:
    """Cache a zone ID lookup."""
    return get_cache().set(zone_name, zone_id, ttl=ttl, namespace=NAMESPACE_ZONES)


def get_cached_zone_id(zone_name: str) -> Optional[str]:
    """Get a cached zone ID."""
    return get_cache().get(zone_name, namespace=NAMESPACE_ZONES)


def cache_dns_record(hostname: str, record_data: Dict[str, Any], ttl: int = 300) -> bool:
    """Cache DNS record data."""
    return get_cache().set(hostname, record_data, ttl=ttl, namespace=NAMESPACE_DNS)


def get_cached_dns_record(hostname: str) -> Optional[Dict[str, Any]]:
    """Get cached DNS record data."""
    return get_cache().get(hostname, namespace=NAMESPACE_DNS)


def invalidate_dns_record(hostname: str) -> bool:
    """Invalidate cached DNS record."""
    return get_cache().delete(hostname, namespace=NAMESPACE_DNS)


def cache_api_response(endpoint: str, response: Any, ttl: int = 60) -> bool:
    """Cache an API response."""
    cache_key = endpoint.replace("/", "_")
    return get_cache().set(cache_key, response, ttl=ttl, namespace=NAMESPACE_API)


def get_cached_api_response(endpoint: str) -> Optional[Any]:
    """Get a cached API response."""
    cache_key = endpoint.replace("/", "_")
    return get_cache().get(cache_key, namespace=NAMESPACE_API)


def clear_all_caches() -> bool:
    """Clear all cache entries."""
    return get_cache().clear_all()
