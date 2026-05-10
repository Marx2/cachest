import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest

import stats


def setup_function():
    stats._registry.clear()
    stats._redis = None


def test_record_hit():
    stats.record("/dy/{ticker}", "HIT")
    s = stats.get("/dy/{ticker}")
    assert s.total == 1
    assert s.hits == 1
    assert s.misses == 0
    assert s.stale == 0


def test_record_miss():
    stats.record("/dy/{ticker}", "MISS")
    s = stats.get("/dy/{ticker}")
    assert s.total == 1
    assert s.hits == 0
    assert s.misses == 1
    assert s.stale == 0


def test_record_stale():
    stats.record("/dy/{ticker}", "STALE")
    s = stats.get("/dy/{ticker}")
    assert s.total == 1
    assert s.hits == 0
    assert s.misses == 0
    assert s.stale == 1


def test_record_error():
    stats.record("/dy/{ticker}", "ERROR")
    s = stats.get("/dy/{ticker}")
    assert s.total == 1
    assert s.errors == 1
    assert s.hits == 0


def test_record_accumulates():
    stats.record("/dy/{ticker}", "HIT")
    stats.record("/dy/{ticker}", "HIT")
    stats.record("/dy/{ticker}", "MISS")
    stats.record("/dy/{ticker}", "STALE")
    stats.record("/dy/{ticker}", "ERROR")
    s = stats.get("/dy/{ticker}")
    assert s.total == 5
    assert s.hits == 2
    assert s.misses == 1
    assert s.stale == 1
    assert s.errors == 1


def test_record_multiple_routes():
    stats.record("/dy/{ticker}", "HIT")
    stats.record("/fi/{isin}", "MISS")
    assert stats.get("/dy/{ticker}").hits == 1
    assert stats.get("/fi/{isin}").misses == 1
    assert stats.get("/dy/{ticker}").misses == 0


def test_all_routes_snapshot():
    stats.record("/a", "HIT")
    stats.record("/b", "MISS")
    snapshot = stats.all_routes()
    assert set(snapshot.keys()) == {"/a", "/b"}
    assert snapshot["/a"].hits == 1
    assert snapshot["/b"].misses == 1


def test_all_routes_is_copy():
    stats.record("/a", "HIT")
    snapshot = stats.all_routes()
    stats.record("/a", "HIT")
    assert snapshot["/a"].hits == 1  # snapshot not mutated


def test_unknown_x_cache_increments_total_only():
    stats.record("/dy/{ticker}", "UNKNOWN")
    s = stats.get("/dy/{ticker}")
    assert s.total == 1
    assert s.hits == 0
    assert s.misses == 0
    assert s.stale == 0


def test_get_creates_empty():
    s = stats.get("/new/path")
    assert s.total == 0
    assert s.hits == 0


def test_record_no_redis_write_when_client_not_set():
    stats._redis = None
    stats.record("/a", "HIT")  # must not raise


@pytest.mark.asyncio
async def test_record_schedules_redis_write_when_client_set():
    pipe = MagicMock()
    pipe.hincrby = MagicMock()
    pipe.execute = AsyncMock()

    client = MagicMock()
    client.pipeline = MagicMock(return_value=pipe)

    stats.init(client)
    stats.record("/a", "HIT")

    await asyncio.sleep(0)  # let fire-and-forget task run

    pipe.hincrby.assert_any_call("stats:/a", "total", 1)
    pipe.hincrby.assert_any_call("stats:/a", "hits", 1)
    await pipe.execute()


@pytest.mark.asyncio
async def test_load_from_redis_pre_populates_registry():
    async def _scan(*args, **kwargs):
        yield "stats:/dy/{ticker}"

    client = MagicMock()
    client.scan_iter = MagicMock(return_value=_scan())
    client.hgetall = AsyncMock(return_value={
        b"total": b"42",
        b"hits": b"30",
        b"misses": b"10",
        b"stale": b"1",
        b"errors": b"1",
    })

    await stats.load_from_redis(client)

    s = stats.get("/dy/{ticker}")
    assert s.total == 42
    assert s.hits == 30
    assert s.misses == 10
    assert s.stale == 1
    assert s.errors == 1


@pytest.mark.asyncio
async def test_persist_failure_is_silent():
    pipe = MagicMock()
    pipe.hincrby = MagicMock()
    pipe.execute = AsyncMock(side_effect=ConnectionError("redis down"))

    client = MagicMock()
    client.pipeline = MagicMock(return_value=pipe)

    stats._redis = client
    await stats._persist("/a", "hits")  # must not raise

