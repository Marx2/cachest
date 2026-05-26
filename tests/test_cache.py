import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from cache import CacheMiss, CacheStale, RedisCache


@pytest.fixture
def redis_mock():
    r = MagicMock()
    r.get = AsyncMock()
    r.setex = AsyncMock()
    r.aclose = AsyncMock()
    return r


@pytest.fixture
def cache(redis_mock):
    c = RedisCache.__new__(RedisCache)
    c._client = redis_mock
    return c


async def test_get_miss(cache, redis_mock):
    redis_mock.get.return_value = None
    with pytest.raises(CacheMiss):
        await cache.get("k", 60)


async def test_get_fresh(cache, redis_mock):
    ts = int(time.time()) - 30
    redis_mock.get.return_value = f"{ts}|hello"
    assert await cache.get("k", 60) == "hello"


async def test_get_stale(cache, redis_mock):
    ts = int(time.time()) - 120
    redis_mock.get.return_value = f"{ts}|old"
    with pytest.raises(CacheStale) as exc_info:
        await cache.get("k", 60)
    assert exc_info.value.value == "old"


async def test_get_value_with_pipe(cache, redis_mock):
    ts = int(time.time()) - 5
    redis_mock.get.return_value = f"{ts}|val|ue|pipes"
    assert await cache.get("k", 60) == "val|ue|pipes"


async def test_get_legacy_entry_treated_as_miss(cache, redis_mock):
    redis_mock.get.return_value = "raw_value_no_timestamp"
    with pytest.raises(CacheMiss):
        await cache.get("k", 60)


async def test_set_stores_stamped_value(cache, redis_mock):
    before = int(time.time())
    await cache.set("k", "myvalue", 2592000)
    after = int(time.time())
    key, ttl, stored = redis_mock.setex.call_args[0]
    assert key == "k"
    assert ttl == 2592000
    ts_str, value = stored.split("|", 1)
    assert value == "myvalue"
    assert before <= int(ts_str) <= after


async def test_scan_prefix_with_keys_returns_pairs(cache, redis_mock):
    async def _scan(pattern):
        for k in ["dy:AAPL", "dy:TSLA"]:
            yield k

    redis_mock.scan_iter = _scan
    redis_mock.mget = AsyncMock(return_value=["123|0.05", "456|0.03"])
    result = await cache.scan_prefix_with_keys("dy")
    assert result == [("dy:AAPL", "123|0.05"), ("dy:TSLA", "456|0.03")]


async def test_scan_prefix_with_keys_empty(cache, redis_mock):
    async def _scan(pattern):
        return
        yield

    redis_mock.scan_iter = _scan
    result = await cache.scan_prefix_with_keys("dy")
    assert result == []


async def test_scan_prefix_with_keys_filters_none(cache, redis_mock):
    async def _scan(pattern):
        for k in ["dy:AAPL", "dy:TSLA"]:
            yield k

    redis_mock.scan_iter = _scan
    redis_mock.mget = AsyncMock(return_value=["123|0.05", None])
    result = await cache.scan_prefix_with_keys("dy")
    assert result == [("dy:AAPL", "123|0.05")]
