import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

import stats


@pytest.fixture(autouse=True)
def clean_registry():
    """stats keeps module-level state, so every test starts from a known baseline."""
    stats._registry.clear()
    stats._cache = None
    stats._tasks.clear()
    yield
    stats._registry.clear()
    stats._cache = None


# --- in-process counters ---------------------------------------------------


@pytest.mark.parametrize("x_cache,field", [
    ("HIT", "hits"),
    ("MISS", "misses"),
    ("STALE", "stale"),
    ("ERROR", "errors"),
])
def test_record_increments_the_right_counter(x_cache, field):
    stats.record("/dy/{ticker}", x_cache)
    s = stats.get("/dy/{ticker}")
    assert s.total == 1
    assert getattr(s, field) == 1
    others = {"hits", "misses", "stale", "errors"} - {field}
    assert all(getattr(s, o) == 0 for o in others)


def test_record_is_case_insensitive():
    stats.record("/a", "hit")
    assert stats.get("/a").hits == 1


def test_record_accumulates():
    for tag in ("HIT", "HIT", "MISS", "STALE", "ERROR"):
        stats.record("/dy/{ticker}", tag)
    s = stats.get("/dy/{ticker}")
    assert (s.total, s.hits, s.misses, s.stale, s.errors) == (5, 2, 1, 1, 1)


def test_unknown_x_cache_increments_total_only():
    stats.record("/a", "WEIRD")
    s = stats.get("/a")
    assert s.total == 1
    assert (s.hits, s.misses, s.stale, s.errors) == (0, 0, 0, 0)


def test_routes_are_counted_separately():
    stats.record("/dy/{ticker}", "HIT")
    stats.record("/fi/{isin}", "MISS")
    assert stats.get("/dy/{ticker}").hits == 1
    assert stats.get("/fi/{isin}").misses == 1
    assert stats.get("/dy/{ticker}").misses == 0


def test_all_routes_returns_a_snapshot():
    stats.record("/a", "HIT")
    snapshot = stats.all_routes()
    stats.record("/a", "HIT")
    assert snapshot["/a"].hits == 1


# --- redis mirroring -------------------------------------------------------


def test_record_without_a_cache_does_not_raise():
    stats.record("/a", "HIT")  # must not raise


async def test_record_mirrors_to_redis_in_one_round_trip():
    cache = MagicMock()
    cache.hincrby_fields = AsyncMock()
    stats.init(cache)

    stats.record("/a", "HIT")
    await stats.drain()

    cache.hincrby_fields.assert_awaited_once_with("stats:/a", {"total": 1, "hits": 1})


async def test_persist_failure_does_not_break_the_request_path():
    """A stats write failing must never surface to the caller."""
    cache = MagicMock()
    cache.hincrby_fields = AsyncMock(side_effect=ConnectionError("redis down"))
    stats.init(cache)

    stats.record("/a", "HIT")
    await stats.drain()

    assert stats.get("/a").hits == 1


def test_record_outside_an_event_loop_is_safe():
    """Synchronous callers (tests, startup) must not blow up on create_task."""
    cache = MagicMock()
    cache.hincrby_fields = AsyncMock()
    stats.init(cache)
    stats.record("/a", "HIT")  # must not raise
    assert stats.get("/a").hits == 1


def test_drain_with_nothing_pending():
    assert asyncio.run(stats.drain()) is None


# --- loading and reset -----------------------------------------------------


async def test_load_from_redis_pre_populates_the_registry():
    cache = MagicMock()
    cache.scan_keys = AsyncMock(return_value=["stats:/dy/{ticker}"])
    cache.hgetall = AsyncMock(return_value={
        "total": "42", "hits": "30", "misses": "10", "stale": "1", "errors": "1",
    })

    await stats.load_from_redis(cache)

    s = stats.get("/dy/{ticker}")
    assert (s.total, s.hits, s.misses, s.stale, s.errors) == (42, 30, 10, 1, 1)


async def test_load_from_redis_skips_empty_hashes():
    cache = MagicMock()
    cache.scan_keys = AsyncMock(return_value=["stats:/a"])
    cache.hgetall = AsyncMock(return_value={})
    await stats.load_from_redis(cache)
    assert stats.get("/a").total == 0


async def test_load_from_redis_failure_starts_from_zero(caplog):
    """Redis being down must not stop the app; the dashboard just forgets history —
    but that has to be visible in the log rather than silent."""
    cache = MagicMock()
    cache.scan_keys = AsyncMock(side_effect=ConnectionError("redis down"))

    with caplog.at_level("WARNING", logger="cachest.stats"):
        await stats.load_from_redis(cache)

    assert any("could not load stats" in r.message for r in caplog.records)


async def test_reset_all_clears_counters_and_redis_keys():
    stats.record("/a", "HIT")
    cache = MagicMock()
    cache.delete_pattern = AsyncMock()

    stats.reset_all(cache)
    await stats.drain()

    assert stats.all_routes() == {}
    cache.delete_pattern.assert_awaited_once_with("stats:*")


async def test_reset_all_survives_a_redis_failure():
    stats.record("/a", "HIT")
    cache = MagicMock()
    cache.delete_pattern = AsyncMock(side_effect=ConnectionError("redis down"))

    stats.reset_all(cache)
    await stats.drain()  # must not raise

    assert stats.all_routes() == {}
