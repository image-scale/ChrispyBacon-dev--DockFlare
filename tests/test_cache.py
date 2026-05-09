"""Tests for cache layer."""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock

from dockflare.cache import (
    CacheEntry,
    MemoryCache,
    RedisCache,
    CacheManager,
    NAMESPACE_ZONES,
    NAMESPACE_DNS,
    NAMESPACE_API,
    get_cache,
    cache_zone_id,
    get_cached_zone_id,
    cache_dns_record,
    get_cached_dns_record,
    invalidate_dns_record,
    cache_api_response,
    get_cached_api_response,
    clear_all_caches,
)


class TestCacheEntry:
    """Tests for CacheEntry class."""

    def test_not_expired_when_no_ttl(self):
        """Entry with no TTL should not expire."""
        entry = CacheEntry(value="test", expires_at=0)
        assert entry.is_expired is False

    def test_not_expired_before_time(self):
        """Entry should not be expired before its time."""
        future_time = time.time() + 3600
        entry = CacheEntry(value="test", expires_at=future_time)
        assert entry.is_expired is False

    def test_expired_after_time(self):
        """Entry should be expired after its time."""
        past_time = time.time() - 1
        entry = CacheEntry(value="test", expires_at=past_time)
        assert entry.is_expired is True


class TestMemoryCache:
    """Tests for MemoryCache class."""

    @pytest.fixture
    def cache(self):
        """Create a MemoryCache instance."""
        return MemoryCache(max_size=100)

    def test_set_and_get(self, cache):
        """Should set and retrieve values."""
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_nonexistent_returns_none(self, cache):
        """Should return None for missing keys."""
        assert cache.get("nonexistent") is None

    def test_delete_removes_key(self, cache):
        """Should delete keys."""
        cache.set("key1", "value1")
        assert cache.delete("key1") is True
        assert cache.get("key1") is None

    def test_delete_nonexistent_returns_false(self, cache):
        """Should return False when deleting missing key."""
        assert cache.delete("nonexistent") is False

    def test_exists_returns_true_for_existing(self, cache):
        """Should return True for existing keys."""
        cache.set("key1", "value1")
        assert cache.exists("key1") is True

    def test_exists_returns_false_for_missing(self, cache):
        """Should return False for missing keys."""
        assert cache.exists("nonexistent") is False

    def test_clear_removes_all(self, cache):
        """Should remove all entries."""
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_keys_returns_all_keys(self, cache):
        """Should return all keys."""
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        keys = cache.keys()
        assert "key1" in keys
        assert "key2" in keys

    def test_keys_with_pattern(self, cache):
        """Should filter keys by pattern."""
        cache.set("prefix:key1", "value1")
        cache.set("prefix:key2", "value2")
        cache.set("other:key3", "value3")
        keys = cache.keys("prefix:*")
        assert len(keys) == 2
        assert "other:key3" not in keys


class TestMemoryCacheTTL:
    """Tests for MemoryCache TTL behavior."""

    @pytest.fixture
    def cache(self):
        return MemoryCache()

    def test_ttl_expires_entry(self, cache):
        """Entry should expire after TTL."""
        cache.set("key1", "value1", ttl=1)
        time.sleep(1.1)
        assert cache.get("key1") is None

    def test_ttl_zero_never_expires(self, cache):
        """Entry with TTL=0 should not expire."""
        cache.set("key1", "value1", ttl=0)
        assert cache.get("key1") == "value1"

    def test_exists_returns_false_for_expired(self, cache):
        """exists should return False for expired keys."""
        cache.set("key1", "value1", ttl=1)
        time.sleep(1.1)
        assert cache.exists("key1") is False


class TestMemoryCacheEviction:
    """Tests for MemoryCache eviction behavior."""

    def test_evicts_oldest_when_full(self):
        """Should evict oldest entry when max size reached."""
        cache = MemoryCache(max_size=2)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        assert cache.size <= 2
        assert cache.get("key3") == "value3"

    def test_evicts_expired_first(self):
        """Should evict expired entries before oldest."""
        cache = MemoryCache(max_size=2)
        cache.set("expired", "value", ttl=1)
        cache.set("fresh", "value", ttl=3600)
        time.sleep(1.1)
        cache.set("new", "value")

        assert cache.get("fresh") == "value"
        assert cache.get("new") == "value"


class TestRedisCacheWithoutRedis:
    """Tests for RedisCache when Redis is unavailable."""

    @patch.dict("sys.modules", {"redis": None})
    def test_handles_missing_redis_package(self):
        """Should handle missing redis package gracefully."""
        cache = RedisCache()
        assert cache.is_connected is False
        assert cache.get("key") is None
        assert cache.set("key", "value") is False

    def test_handles_connection_failure(self):
        """Should handle Redis connection failure."""
        cache = RedisCache(host="nonexistent.host.invalid", port=9999)
        assert cache.is_connected is False


class TestRedisCacheWithMock:
    """Tests for RedisCache with mocked Redis client."""

    @pytest.fixture
    def mock_redis_client(self):
        """Create a mock Redis client."""
        client = MagicMock()
        client.ping.return_value = True
        return client

    @pytest.fixture
    def cache(self, mock_redis_client):
        """Create a RedisCache with mock client."""
        cache = RedisCache.__new__(RedisCache)
        cache._prefix = "test:"
        cache._client = mock_redis_client
        cache._connection_error = None
        return cache

    def test_get_returns_value(self, cache, mock_redis_client):
        """Should return cached value."""
        mock_redis_client.get.return_value = b'{"key": "value"}'
        result = cache.get("mykey")
        assert result == {"key": "value"}
        mock_redis_client.get.assert_called_with("test:mykey")

    def test_get_returns_none_for_missing(self, cache, mock_redis_client):
        """Should return None for missing keys."""
        mock_redis_client.get.return_value = None
        assert cache.get("missing") is None

    def test_set_without_ttl(self, cache, mock_redis_client):
        """Should set value without TTL."""
        cache.set("key", {"value": 123})
        mock_redis_client.set.assert_called()

    def test_set_with_ttl(self, cache, mock_redis_client):
        """Should set value with TTL."""
        cache.set("key", {"value": 123}, ttl=60)
        mock_redis_client.setex.assert_called_with("test:key", 60, '{"value": 123}')

    def test_delete_returns_true(self, cache, mock_redis_client):
        """Should return True on successful delete."""
        mock_redis_client.delete.return_value = 1
        assert cache.delete("key") is True

    def test_delete_returns_false(self, cache, mock_redis_client):
        """Should return False when key not deleted."""
        mock_redis_client.delete.return_value = 0
        assert cache.delete("missing") is False

    def test_exists_returns_true(self, cache, mock_redis_client):
        """Should return True when key exists."""
        mock_redis_client.exists.return_value = 1
        assert cache.exists("key") is True

    def test_exists_returns_false(self, cache, mock_redis_client):
        """Should return False when key missing."""
        mock_redis_client.exists.return_value = 0
        assert cache.exists("missing") is False


class TestCacheManager:
    """Tests for CacheManager class."""

    @pytest.fixture
    def manager(self):
        """Create a CacheManager without Redis."""
        return CacheManager(redis_host=None, default_ttl=60)

    def test_uses_memory_when_no_redis(self, manager):
        """Should use memory cache when Redis unavailable."""
        assert manager.using_redis is False
        assert manager.primary_backend is manager._memory

    def test_set_and_get(self, manager):
        """Should set and get values."""
        manager.set("key", "value")
        assert manager.get("key") == "value"

    def test_set_with_namespace(self, manager):
        """Should support namespaced keys."""
        manager.set("key", "value1", namespace="ns1")
        manager.set("key", "value2", namespace="ns2")
        assert manager.get("key", namespace="ns1") == "value1"
        assert manager.get("key", namespace="ns2") == "value2"

    def test_delete(self, manager):
        """Should delete keys."""
        manager.set("key", "value")
        manager.delete("key")
        assert manager.get("key") is None

    def test_exists(self, manager):
        """Should check key existence."""
        manager.set("key", "value")
        assert manager.exists("key") is True
        assert manager.exists("missing") is False

    def test_clear_namespace(self, manager):
        """Should clear all keys in a namespace."""
        manager.set("key1", "value1", namespace="ns")
        manager.set("key2", "value2", namespace="ns")
        manager.set("key3", "value3", namespace="other")

        manager.clear_namespace("ns")

        assert manager.get("key1", namespace="ns") is None
        assert manager.get("key2", namespace="ns") is None
        assert manager.get("key3", namespace="other") == "value3"

    def test_clear_all(self, manager):
        """Should clear all cache entries."""
        manager.set("key1", "value1")
        manager.set("key2", "value2")
        manager.clear_all()
        assert manager.get("key1") is None
        assert manager.get("key2") is None

    def test_get_or_set_returns_cached(self, manager):
        """Should return cached value without calling factory."""
        manager.set("key", "cached")
        factory = Mock(return_value="fresh")

        result = manager.get_or_set("key", factory)

        assert result == "cached"
        factory.assert_not_called()

    def test_get_or_set_computes_and_caches(self, manager):
        """Should compute and cache when not cached."""
        factory = Mock(return_value="computed")

        result = manager.get_or_set("key", factory)

        assert result == "computed"
        factory.assert_called_once()
        assert manager.get("key") == "computed"


class TestCacheManagerWithRedis:
    """Tests for CacheManager with mocked Redis."""

    @pytest.fixture
    def mock_redis_cache(self):
        """Create a mock RedisCache."""
        cache = Mock()
        cache.is_connected = True
        return cache

    def test_uses_redis_when_connected(self, mock_redis_cache):
        """Should use Redis when connected."""
        manager = CacheManager(redis_host=None)
        manager._redis = mock_redis_cache

        assert manager.using_redis is True
        assert manager.primary_backend is mock_redis_cache


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Reset the global cache manager."""
        import dockflare.cache as cache_module
        cache_module._cache_manager = None
        yield
        cache_module._cache_manager = None

    def test_get_cache_creates_singleton(self):
        """get_cache should create a singleton."""
        cache1 = get_cache()
        cache2 = get_cache()
        assert cache1 is cache2

    def test_cache_zone_id(self):
        """Should cache and retrieve zone IDs."""
        cache_zone_id("example.com", "zone-123")
        assert get_cached_zone_id("example.com") == "zone-123"

    def test_get_cached_zone_id_missing(self):
        """Should return None for uncached zones."""
        assert get_cached_zone_id("uncached.com") is None

    def test_cache_dns_record(self):
        """Should cache and retrieve DNS records."""
        record = {"id": "rec-123", "type": "CNAME"}
        cache_dns_record("app.example.com", record)
        assert get_cached_dns_record("app.example.com") == record

    def test_invalidate_dns_record(self):
        """Should invalidate cached DNS records."""
        cache_dns_record("app.example.com", {"id": "rec-123"})
        invalidate_dns_record("app.example.com")
        assert get_cached_dns_record("app.example.com") is None

    def test_cache_api_response(self):
        """Should cache and retrieve API responses."""
        response = {"success": True, "result": []}
        cache_api_response("/zones", response)
        assert get_cached_api_response("/zones") == response

    def test_clear_all_caches(self):
        """Should clear all cache entries."""
        cache_zone_id("example.com", "zone-123")
        cache_dns_record("app.example.com", {"id": "rec-123"})

        clear_all_caches()

        assert get_cached_zone_id("example.com") is None
        assert get_cached_dns_record("app.example.com") is None


class TestCacheNamespaces:
    """Tests for namespace constants."""

    def test_namespace_values(self):
        """Namespace constants should be defined."""
        assert NAMESPACE_ZONES == "zones"
        assert NAMESPACE_DNS == "dns"
        assert NAMESPACE_API == "api"
