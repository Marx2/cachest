import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from cache import CacheMiss
from config import Config, RedisConfig, RouteConfig, ExtractConfig
from main import create_app


def _make_config(**route_kwargs) -> Config:
    defaults = dict(
        path="/test/{id}",
        url="http://example.com/{id}",
        cache_ttl=60,
        fetch_interval=2.0,
        fetch_max_wait=4.0,
        stale_ttl=2592000,
    )
    defaults.update(route_kwargs)
    route = RouteConfig(**defaults)
    return Config(redis=RedisConfig(), routes=[route])


@pytest.fixture
def mock_cache():
    async def _empty():
        return
        yield

    cache = MagicMock()
    cache.get = AsyncMock(side_effect=CacheMiss("test:1"))
    cache.set = AsyncMock()
    cache.close = AsyncMock()
    cache.scan_prefix = AsyncMock(return_value=[])
    cache.scan_prefix_with_keys = AsyncMock(return_value=[])
    cache._client = MagicMock()
    cache._client.scan_iter = MagicMock(return_value=_empty())
    return cache


@pytest.fixture
def mock_fetch():
    with patch("main.fetch", new_callable=AsyncMock) as m:
        m.return_value = "result_value"
        yield m


def test_cache_hit_skips_fetch(mock_cache, mock_fetch):
    cfg = _make_config()
    with patch("main.RedisCache", return_value=mock_cache):
        app = create_app(cfg)
    mock_cache.get = AsyncMock(return_value="cached_value")
    client = TestClient(app)
    resp = client.get("/test/1")
    assert resp.status_code == 200
    assert resp.text == "cached_value"
    assert resp.headers["x-cache"] == "HIT"
    mock_fetch.assert_not_called()


def test_cache_miss_fetches_and_stores(mock_cache, mock_fetch):
    cfg = _make_config()
    with patch("main.RedisCache", return_value=mock_cache):
        app = create_app(cfg)
    client = TestClient(app)
    resp = client.get("/test/1")
    assert resp.status_code == 200
    assert resp.text == "result_value"
    assert resp.headers["x-cache"] == "MISS"
    mock_cache.set.assert_called_once()


def test_rate_limiter_false_returns_stale(mock_cache, mock_fetch):
    """When acquire() returns False, serve stale from cache."""
    cfg = _make_config()
    with patch("main.RedisCache", return_value=mock_cache), \
         patch("main.RateLimiter") as MockLimiter:
        limiter_instance = MagicMock()
        limiter_instance.acquire = AsyncMock(return_value=False)
        MockLimiter.return_value = limiter_instance
        app = create_app(cfg)
    stale_calls = 0

    async def get_side_effect(key, cache_ttl=None):
        nonlocal stale_calls
        stale_calls += 1
        if stale_calls == 1:
            raise CacheMiss(key)  # first call = miss (triggers rate limiter check)
        return "stale_value"     # second call = stale fallback

    mock_cache.get = AsyncMock(side_effect=get_side_effect)
    client = TestClient(app)
    resp = client.get("/test/1")
    assert resp.status_code == 200
    assert resp.text == "stale_value"
    assert resp.headers["x-cache"] == "STALE"
    mock_fetch.assert_not_called()


def test_rate_limiter_false_no_stale_returns_503(mock_cache, mock_fetch):
    """When acquire() returns False and no stale exists, return 503."""
    cfg = _make_config()
    with patch("main.RedisCache", return_value=mock_cache), \
         patch("main.RateLimiter") as MockLimiter:
        limiter_instance = MagicMock()
        limiter_instance.acquire = AsyncMock(return_value=False)
        MockLimiter.return_value = limiter_instance
        app = create_app(cfg)
    mock_cache.get = AsyncMock(side_effect=CacheMiss("test:1"))
    client = TestClient(app)
    resp = client.get("/test/1")
    assert resp.status_code == 503
    mock_fetch.assert_not_called()


def test_upstream_error_returns_stale(mock_cache, mock_fetch):
    """On UpstreamError, serve stale from cache."""
    from fetcher import UpstreamError
    cfg = _make_config()
    with patch("main.RedisCache", return_value=mock_cache):
        app = create_app(cfg)
    mock_fetch.side_effect = UpstreamError("http://example.com/1", 429)
    stale_calls = 0

    async def get_side_effect(key, cache_ttl=None):
        nonlocal stale_calls
        stale_calls += 1
        if stale_calls == 1:
            raise CacheMiss(key)  # first call = miss (triggers fetch)
        return "stale_value"     # second call = stale fallback

    mock_cache.get = AsyncMock(side_effect=get_side_effect)
    client = TestClient(app)
    resp = client.get("/test/1")
    assert resp.status_code == 200
    assert resp.text == "stale_value"
    assert resp.headers["x-cache"] == "STALE"


def test_upstream_error_no_stale_returns_503(mock_cache, mock_fetch):
    """On UpstreamError with no stale, return 503."""
    from fetcher import UpstreamError
    cfg = _make_config()
    with patch("main.RedisCache", return_value=mock_cache):
        app = create_app(cfg)
    mock_fetch.side_effect = UpstreamError("http://example.com/1", 403)
    mock_cache.get = AsyncMock(side_effect=CacheMiss("test:1"))
    client = TestClient(app)
    resp = client.get("/test/1")
    assert resp.status_code == 503


def test_force_refresh_rate_limited_returns_stale(mock_cache, mock_fetch):
    """forceRefresh=true is still subject to rate limiting; stale is served if acquire() is False."""
    cfg = _make_config()
    with patch("main.RedisCache", return_value=mock_cache), \
         patch("main.RateLimiter") as MockLimiter:
        limiter_instance = MagicMock()
        limiter_instance.acquire = AsyncMock(return_value=False)
        MockLimiter.return_value = limiter_instance
        app = create_app(cfg)
    mock_cache.get = AsyncMock(return_value="stale_value")
    client = TestClient(app)
    resp = client.get("/test/1?forceRefresh=true")
    assert resp.status_code == 200
    assert resp.text == "stale_value"
    assert resp.headers["x-cache"] == "STALE"
    mock_fetch.assert_not_called()


def test_stale_entry_triggers_refetch(mock_cache, mock_fetch):
    """CacheStale on normal path → MISS, not HIT."""
    from cache import CacheStale
    cfg = _make_config()
    with patch("main.RedisCache", return_value=mock_cache):
        app = create_app(cfg)
    mock_cache.get = AsyncMock(side_effect=CacheStale("test:1", "old_value"))
    client = TestClient(app)
    resp = client.get("/test/1")
    assert resp.status_code == 200
    assert resp.text == "result_value"
    assert resp.headers["x-cache"] == "MISS"
    mock_fetch.assert_called_once()


def test_stale_entry_served_when_rate_limited(mock_cache, mock_fetch):
    """Rate-limited + CacheStale → serve stale value."""
    from cache import CacheStale
    cfg = _make_config()
    with patch("main.RedisCache", return_value=mock_cache), \
         patch("main.RateLimiter") as MockLimiter:
        limiter_instance = MagicMock()
        limiter_instance.acquire = AsyncMock(return_value=False)
        MockLimiter.return_value = limiter_instance
        app = create_app(cfg)
    calls = 0

    async def get_side_effect(key, cache_ttl=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CacheMiss(key)
        raise CacheStale(key, "old_value")

    mock_cache.get = AsyncMock(side_effect=get_side_effect)
    client = TestClient(app)
    resp = client.get("/test/1")
    assert resp.status_code == 200
    assert resp.text == "old_value"
    assert resp.headers["x-cache"] == "STALE"
    mock_fetch.assert_not_called()


def test_stale_entry_served_on_upstream_error(mock_cache, mock_fetch):
    """Upstream error + CacheStale → serve stale value."""
    from cache import CacheStale
    from fetcher import UpstreamError
    cfg = _make_config()
    with patch("main.RedisCache", return_value=mock_cache):
        app = create_app(cfg)
    mock_fetch.side_effect = UpstreamError("http://example.com/1", 429)
    calls = 0

    async def get_side_effect(key, cache_ttl=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CacheMiss(key)
        raise CacheStale(key, "old_value")

    mock_cache.get = AsyncMock(side_effect=get_side_effect)
    client = TestClient(app)
    resp = client.get("/test/1")
    assert resp.status_code == 200
    assert resp.text == "old_value"
    assert resp.headers["x-cache"] == "STALE"


def test_invalidate_ticker_deletes_keys(mock_cache, mock_fetch):
    cfg = _make_config()

    async def _scan(pattern):
        yield "test:AAPL"

    mock_cache._client.scan_iter = _scan
    mock_cache._client.delete = AsyncMock()

    with patch("main.RedisCache", return_value=mock_cache):
        app = create_app(cfg)

    client = TestClient(app)
    resp = client.post("/stats/invalidate-ticker/test/AAPL")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted": 1}
    mock_cache._client.delete.assert_called_once_with("test:AAPL")


def test_invalidate_ticker_no_keys(mock_cache, mock_fetch):
    cfg = _make_config()

    async def _scan(pattern):
        return
        yield

    mock_cache._client.scan_iter = _scan
    mock_cache._client.delete = AsyncMock()

    with patch("main.RedisCache", return_value=mock_cache):
        app = create_app(cfg)

    client = TestClient(app)
    resp = client.post("/stats/invalidate-ticker/test/AAPL")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted": 0}
    mock_cache._client.delete.assert_not_called()


def test_stats_page_includes_cache_browser(mock_cache, mock_fetch):
    cfg = _make_config()
    mock_cache.scan_prefix_with_keys = AsyncMock(
        return_value=[("test:AAPL", "1700000000|0.05")]
    )
    with patch("main.RedisCache", return_value=mock_cache):
        app = create_app(cfg)

    client = TestClient(app)
    resp = client.get("/stats")
    assert resp.status_code == 200
    assert "Cache Browser" in resp.text
    assert "cache-filter" in resp.text
    assert "invalidate-btn" in resp.text
    assert "AAPL" in resp.text


def test_stats_page_empty_cache_browser(mock_cache, mock_fetch):
    cfg = _make_config()
    mock_cache.scan_prefix_with_keys = AsyncMock(return_value=[])
    with patch("main.RedisCache", return_value=mock_cache):
        app = create_app(cfg)

    client = TestClient(app)
    resp = client.get("/stats")
    assert resp.status_code == 200
    assert "Cache Browser" in resp.text
    assert "0 entries" in resp.text


# ---------------------------------------------------------------------------
# query-param routes (openst instruments surface)
# ---------------------------------------------------------------------------


from main import _build_url, _cache_key


def test_cache_key_substitutes_path_and_query_params():
    assert _cache_key("/ohlcv/{ticker}", {"ticker": "AAPL"}, {"start": "2025-01-01", "end": "2026-01-01"}) == \
        "ohlcv:AAPL:2025-01-01:2026-01-01"


def test_cache_key_no_path_params_routes_dont_collide():
    assert _cache_key("/calendar/earnings", {}) == "calendar:earnings"
    assert _cache_key("/calendar/dividend", {}) == "calendar:dividend"
    assert _cache_key("/dy/{ticker}", {"ticker": "AAPL"}) == "dy:AAPL"


def test_build_url_substitutes_query_values():
    url = _build_url(
        "http://up/{ticker}?statement={statement}&period={period}",
        {"ticker": "AAPL"},
        "",
        {"statement": "cash", "period": "quarter"},
    )
    assert url == "http://up/AAPL?statement=cash&period=quarter"


def _query_config() -> Config:
    return _make_config(
        path="/ohlcv/{ticker}",
        url="http://example.com/ohlcv/{ticker}?start={start}&end={end}",
        query_params=["start", "end"],
    )


def test_missing_query_param_returns_422(mock_cache, mock_fetch):
    cfg = _query_config()
    with patch("main.RedisCache", return_value=mock_cache):
        app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/ohlcv/AAPL?start=2025-01-01")
    assert resp.status_code == 422
    assert "end" in resp.text
    mock_fetch.assert_not_called()
    mock_cache.get.assert_not_called()


def test_query_params_forwarded_to_upstream(mock_cache, mock_fetch):
    cfg = _query_config()
    with patch("main.RedisCache", return_value=mock_cache):
        app = create_app(cfg)
    client = TestClient(app)

    resp = client.get("/ohlcv/AAPL?start=2025-01-01&end=2026-01-01")
    assert resp.status_code == 200
    assert resp.headers["x-cache"] == "MISS"
    assert mock_fetch.call_args.args[0] == \
        "http://example.com/ohlcv/AAPL?start=2025-01-01&end=2026-01-01"


def test_different_query_values_cached_separately(mock_cache, mock_fetch):
    cfg = _query_config()
    with patch("main.RedisCache", return_value=mock_cache):
        app = create_app(cfg)
    mock_cache.get = AsyncMock(side_effect=CacheMiss("k"))
    client = TestClient(app)

    client.get("/ohlcv/AAPL?start=2025-01-01&end=2026-01-02")
    client.get("/ohlcv/AAPL?start=2025-01-01&end=2026-01-03")

    keys = {call.args[0] for call in mock_cache.set.call_args_list}
    assert keys == {
        "ohlcv:AAPL:2025-01-01:2026-01-02",
        "ohlcv:AAPL:2025-01-01:2026-01-03",
    }
