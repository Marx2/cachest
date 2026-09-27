import time

import pytest
from unittest.mock import AsyncMock, MagicMock

from cache import SCAN_BATCH, TIMESTAMP_CHARS, CacheMiss, CacheStale, RedisCache


@pytest.fixture
def redis_mock():
    r = MagicMock()
    r.get = AsyncMock()
    r.setex = AsyncMock()
    r.mget = AsyncMock()
    r.scan_iter = MagicMock()
    r.delete = AsyncMock()
    r.incr = AsyncMock()
    r.expire = AsyncMock()
    r.hgetall = AsyncMock()
    r.aclose = AsyncMock()
    r.pipeline = MagicMock()
    return r


@pytest.fixture
def cache(redis_mock):
    c = RedisCache.__new__(RedisCache)
    c._client = redis_mock
    return c


def _scan_yielding(*keys):
    async def _scan(pattern):
        for k in keys:
            yield k

    return _scan


# --- get / set -------------------------------------------------------------


async def test_get_miss(cache, redis_mock):
    redis_mock.get.return_value = None
    with pytest.raises(CacheMiss):
        await cache.get("k", 60)


async def test_get_fresh(cache, redis_mock):
    redis_mock.get.return_value = f"{int(time.time()) - 30}|hello"
    assert await cache.get("k", 60) == "hello"


async def test_get_stale(cache, redis_mock):
    redis_mock.get.return_value = f"{int(time.time()) - 120}|old"
    with pytest.raises(CacheStale) as exc_info:
        await cache.get("k", 60)
    assert exc_info.value.value == "old"


async def test_get_value_with_pipe(cache, redis_mock):
    redis_mock.get.return_value = f"{int(time.time()) - 5}|val|ue|pipes"
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


# --- get_fresh_or_stale: the fallback primitive ---------------------------


async def test_get_fresh_or_stale_returns_fresh_value(cache, redis_mock):
    redis_mock.get.return_value = f"{int(time.time()) - 5}|fresh"
    assert await cache.get_fresh_or_stale("k", 60) == "fresh"


async def test_get_fresh_or_stale_returns_expired_value(cache, redis_mock):
    redis_mock.get.return_value = f"{int(time.time()) - 9999}|ancient"
    assert await cache.get_fresh_or_stale("k", 60) == "ancient"


async def test_get_fresh_or_stale_returns_none_on_miss(cache, redis_mock):
    redis_mock.get.return_value = None
    assert await cache.get_fresh_or_stale("k", 60) is None


# --- quota counter ---------------------------------------------------------


async def test_incr_with_ttl_sets_expiry_only_on_creation(cache, redis_mock):
    redis_mock.incr.return_value = 1
    assert await cache.incr_with_ttl("limit:FMP:2026-05-13", 90000) == 1
    redis_mock.expire.assert_called_once_with("limit:FMP:2026-05-13", 90000)


async def test_incr_with_ttl_does_not_extend_expiry_of_existing_key(cache, redis_mock):
    """Extending the TTL on every call would keep a dead day's counter alive forever."""
    redis_mock.incr.return_value = 7
    assert await cache.incr_with_ttl("limit:FMP:2026-05-13", 90000) == 7
    redis_mock.expire.assert_not_called()


# --- scanning --------------------------------------------------------------


async def test_scan_all_with_values_uses_a_single_scan(cache, redis_mock):
    redis_mock.scan_iter = MagicMock(side_effect=lambda pattern: _scan_yielding("a:1", "b:2")(pattern))
    redis_mock.mget = AsyncMock(return_value=["1|x", "2|y"])
    assert await cache.scan_all_with_values() == [("a:1", "1|x"), ("b:2", "2|y")]
    redis_mock.scan_iter.assert_called_once_with("*")


async def test_scan_all_with_values_filters_keys_deleted_mid_scan(cache, redis_mock):
    """A key removed between SCAN and MGET comes back as None and must be dropped,
    or the stats page would attribute a value to a key that no longer exists."""
    redis_mock.scan_iter = _scan_yielding("a:1", "b:2")
    redis_mock.mget = AsyncMock(return_value=["1|x", None])
    assert await cache.scan_all_with_values() == [("a:1", "1|x")]


async def test_scan_all_with_values_batches_large_keyspaces(cache, redis_mock):
    """One huge MGET would block the Redis event loop, so reads are chunked."""
    keys = [f"a:{i}" for i in range(SCAN_BATCH * 2 + 5)]
    redis_mock.scan_iter = _scan_yielding(*keys)
    redis_mock.mget = AsyncMock(side_effect=lambda *ks: [f"1|{k}" for k in ks])
    result = await cache.scan_all_with_values()
    assert len(result) == len(keys)
    assert redis_mock.mget.call_count == 3


async def test_read_heads_pipelines_getrange(cache, redis_mock):
    pipe = MagicMock()
    pipe.getrange = MagicMock()
    pipe.execute = AsyncMock(return_value=["1700000000|", "1700000001|"])
    redis_mock.pipeline = MagicMock(return_value=pipe)

    assert await cache.read_heads(["a:1", "b:2"]) == {
        "a:1": "1700000000|", "b:2": "1700000001|",
    }
    pipe.execute.assert_awaited_once_with(raise_on_error=False)
    assert [c.args for c in pipe.getrange.call_args_list] == [
        ("a:1", 0, TIMESTAMP_CHARS - 1), ("b:2", 0, TIMESTAMP_CHARS - 1),
    ]


async def test_read_heads_skips_wrong_type_keys(cache, redis_mock):
    """Regression: cachest's "stats:" counters are hashes in this same database, and
    GETRANGE on a hash raises WRONGTYPE. A dashboard must not 500 on its own keys."""
    from redis.exceptions import ResponseError
    pipe = MagicMock()
    pipe.getrange = MagicMock()
    pipe.execute = AsyncMock(return_value=[
        "1700000000|",
        ResponseError("WRONGTYPE Operation against a key holding the wrong kind of value"),
        "",  # key deleted between SCAN and read
    ])
    redis_mock.pipeline = MagicMock(return_value=pipe)

    result = await cache.read_heads(["a:1", "stats:/x", "gone:1"])
    assert result == {"a:1": "1700000000|"}


async def test_read_previews_strips_the_timestamp_prefix(cache, redis_mock):
    pipe = MagicMock()
    pipe.getrange = MagicMock()
    pipe.execute = AsyncMock(return_value=["1700000000|0.0525"])
    redis_mock.pipeline = MagicMock(return_value=pipe)

    assert await cache.read_previews(["dy:AAPL"]) == {"dy:AAPL": "0.0525"}


async def test_read_previews_truncates(cache, redis_mock):
    pipe = MagicMock()
    pipe.getrange = MagicMock()
    pipe.execute = AsyncMock(return_value=["1700000000|" + "z" * 500])
    redis_mock.pipeline = MagicMock(return_value=pipe)

    assert (await cache.read_previews(["k"], length=80))["k"] == "z" * 80


async def test_reads_batch_large_key_lists(cache, redis_mock):
    pipe = MagicMock()
    pipe.getrange = MagicMock()
    pipe.execute = AsyncMock(side_effect=lambda *a, **k: [])
    redis_mock.pipeline = MagicMock(return_value=pipe)
    await cache.read_heads([f"k:{i}" for i in range(SCAN_BATCH + 1)])
    assert pipe.execute.call_count == 2


# --- deletion --------------------------------------------------------------


async def test_delete_pattern_uses_a_glob(cache, redis_mock):
    redis_mock.scan_iter = _scan_yielding("ohlcv:AAPL", "ohlcv:TSLA")
    assert await cache.delete_pattern("ohlcv:*") == 2
    redis_mock.delete.assert_called_once_with("ohlcv:AAPL", "ohlcv:TSLA")


async def test_delete_pattern_no_keys_skips_delete(cache, redis_mock):
    redis_mock.scan_iter = _scan_yielding()
    assert await cache.delete_pattern("ohlcv:*") == 0
    redis_mock.delete.assert_not_called()


async def test_delete_keys_deletes_exactly_those_keys(cache, redis_mock):
    """Regression: invalidation used to SCAN "prefix:ticker" with no wildcard, which
    cannot match a key carrying query segments (ohlcv:AAPL:start:end)."""
    await cache.delete_keys(["ohlcv:AAPL:2025-01-01:2026-01-01"])
    redis_mock.delete.assert_called_once_with("ohlcv:AAPL:2025-01-01:2026-01-01")
    redis_mock.scan_iter.assert_not_called()


async def test_delete_keys_rejects_a_wildcard(cache, redis_mock):
    """A caller must not be able to smuggle a pattern in and flush a whole prefix."""
    with pytest.raises(ValueError):
        await cache.delete_keys(["ohlcv:*"])
    redis_mock.delete.assert_not_called()


async def test_delete_keys_empty_is_a_noop(cache, redis_mock):
    assert await cache.delete_keys([]) == 0
    redis_mock.delete.assert_not_called()


async def test_delete_keys_batches(cache, redis_mock):
    keys = [f"a:{i}" for i in range(SCAN_BATCH + 1)]
    await cache.delete_keys(keys)
    assert redis_mock.delete.call_count == 2


# --- hashes ----------------------------------------------------------------


async def test_hincrby_fields_pipelines_in_one_round_trip(cache, redis_mock):
    pipe = MagicMock()
    pipe.hincrby = MagicMock()
    pipe.execute = AsyncMock()
    redis_mock.pipeline = MagicMock(return_value=pipe)

    await cache.hincrby_fields("stats:/a", {"total": 1, "hits": 1})

    redis_mock.pipeline.assert_called_once_with(transaction=False)
    assert [c.args for c in pipe.hincrby.call_args_list] == [
        ("stats:/a", "total", 1),
        ("stats:/a", "hits", 1),
    ]
    pipe.execute.assert_awaited_once()


async def test_hincrby_fields_empty_does_nothing(cache, redis_mock):
    await cache.hincrby_fields("stats:/a", {})
    redis_mock.pipeline.assert_not_called()
