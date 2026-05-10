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
    )
    defaults.update(route_kwargs)
    route = RouteConfig(**defaults)
    return Config(redis=RedisConfig(), routes=[route])


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.get = AsyncMock(side_effect=CacheMiss("test:1"))
    cache.set = AsyncMock()
    cache.close = AsyncMock()
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

    async def get_side_effect(key):
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

    async def get_side_effect(key):
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
