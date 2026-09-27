import httpx
import pytest
import respx
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from cache import CacheMiss, CacheStale
from config import Config, RedisConfig, RouteConfig, load
from fetcher import ExtractionError, UpstreamError
from keys import cache_key, key_pattern, path_params_of
from main import create_app

REAL_CONFIG = "config.yaml"


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
    return Config(redis=RedisConfig(), routes=[RouteConfig(**defaults)])


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.get = AsyncMock(side_effect=CacheMiss("test:1"))
    cache.get_fresh_or_stale = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.close = AsyncMock()
    cache.incr_with_ttl = AsyncMock(return_value=1)
    cache.delete_pattern = AsyncMock(return_value=0)
    cache.delete_keys = AsyncMock(return_value=0)
    cache.scan_keys = AsyncMock(return_value=[])
    cache.hgetall = AsyncMock(return_value={})
    cache.hincrby_fields = AsyncMock()

    # The stats page reads value heads for counts/histogram, previews for shown rows.
    cache._test_keys = []
    cache._test_heads = {}
    cache._test_previews = {}

    async def _scan_keys(pattern="*"):
        return list(cache._test_keys)

    async def _heads(keys):
        return {k: cache._test_heads[k] for k in keys if k in cache._test_heads}

    async def _previews(keys, length=80):
        return {k: cache._test_previews.get(k, "") for k in keys}

    cache.scan_keys = _scan_keys
    cache.read_heads = _heads
    cache.read_previews = _previews
    return cache


@pytest.fixture
def fetch():
    with patch("main.fetch", new_callable=AsyncMock) as m:
        m.return_value = "result_value"
        yield m


@pytest.fixture
def limiter():
    """RateLimiter patched for the whole test. Set `limiter.allowed = False` to make
    acquire() refuse, which is the rate-limited path."""
    instance = MagicMock()

    async def acquire():
        return limiter.allowed

    instance.acquire = acquire
    limiter.allowed = True
    with patch("main.RateLimiter", return_value=instance):
        yield limiter


@pytest.fixture
def client(mock_cache, limiter):
    """TestClient factory with RedisCache patched for the whole test."""
    with patch("main.RedisCache", return_value=mock_cache):
        def _client(cfg=None):
            return TestClient(create_app(cfg or _make_config()))
        yield _client


# --- cache outcomes --------------------------------------------------------


def test_cache_hit_skips_fetch(mock_cache, fetch, client):
    mock_cache.get = AsyncMock(return_value="cached_value")
    resp = client().get("/test/1")
    assert (resp.status_code, resp.text, resp.headers["x-cache"]) == (200, "cached_value", "HIT")
    fetch.assert_not_called()


def test_cache_miss_fetches_and_stores(mock_cache, fetch, client):
    resp = client().get("/test/1")
    assert (resp.status_code, resp.text, resp.headers["x-cache"]) == (200, "result_value", "MISS")
    mock_cache.set.assert_called_once()


def test_stale_entry_triggers_refetch(mock_cache, fetch, client):
    """CacheStale on the normal path means MISS, not HIT — the value is re-fetched."""
    mock_cache.get = AsyncMock(side_effect=CacheStale("test:1", "old_value"))
    resp = client().get("/test/1")
    assert (resp.status_code, resp.headers["x-cache"]) == (200, "MISS")
    fetch.assert_called_once()


def test_cache_error_still_serves_a_fetch(mock_cache, fetch, client):
    """Redis being down must not take the endpoint down."""
    mock_cache.get = AsyncMock(side_effect=ConnectionError("redis down"))
    mock_cache.set = AsyncMock(side_effect=ConnectionError("redis down"))
    resp = client().get("/test/1")
    assert (resp.status_code, resp.text) == (200, "result_value")


def test_different_query_values_cached_separately(mock_cache, fetch, client):
    cfg = _make_config(
        path="/ohlcv/{ticker}",
        url="http://example.com/ohlcv/{ticker}?start={start}&end={end}",
        query_params=["start", "end"],
    )
    c = client(cfg)
    c.get("/ohlcv/AAPL?start=2025-01-01&end=2026-01-02")
    c.get("/ohlcv/AAPL?start=2025-01-01&end=2026-01-03")
    keys = {c.args[0] for c in mock_cache.set.call_args_list}
    assert keys == {
        "ohlcv:AAPL:2025-01-01:2026-01-02",
        "ohlcv:AAPL:2025-01-01:2026-01-03",
    }


# --- query params ----------------------------------------------------------


def _query_config() -> Config:
    return _make_config(
        path="/ohlcv/{ticker}",
        url="http://example.com/ohlcv/{ticker}?start={start}&end={end}",
        query_params=["start", "end"],
    )


def test_missing_query_param_returns_422(mock_cache, fetch, client):
    resp = client(_query_config()).get("/ohlcv/AAPL?start=2025-01-01")
    assert resp.status_code == 422
    assert "end" in resp.text
    fetch.assert_not_called()
    mock_cache.get.assert_not_called()


def test_query_params_forwarded_to_upstream(fetch, client):
    resp = client(_query_config()).get("/ohlcv/AAPL?start=2025-01-01&end=2026-01-01")
    assert resp.status_code == 200
    assert fetch.call_args.args[0] == \
        "http://example.com/ohlcv/AAPL?start=2025-01-01&end=2026-01-01"


def test_path_param_is_encoded_into_the_upstream_url(fetch, client):
    """A ticker containing a query separator must not extend the upstream URL."""
    client().get("/test/AAPL%3Fx%3D1")
    assert fetch.call_args.args[0] == "http://example.com/AAPL%3Fx%3D1"


# --- rate limiting ---------------------------------------------------------


def test_rate_limited_serves_stale(mock_cache, fetch, limiter, client):
    limiter.allowed = False
    mock_cache.get_fresh_or_stale = AsyncMock(return_value="stale_value")
    resp = client().get("/test/1")
    assert (resp.text, resp.headers["x-cache"]) == ("stale_value", "STALE")
    assert resp.headers["x-cache-stale-reason"] == "rate-limited"
    fetch.assert_not_called()


def test_rate_limited_without_stale_returns_503(mock_cache, fetch, limiter, client):
    limiter.allowed = False
    mock_cache.get_fresh_or_stale = AsyncMock(return_value=None)
    assert client().get("/test/1").status_code == 503
    fetch.assert_not_called()


def test_force_refresh_is_still_rate_limited(mock_cache, fetch, limiter, client):
    limiter.allowed = False
    mock_cache.get_fresh_or_stale = AsyncMock(return_value="stale_value")
    resp = client().get("/test/1?forceRefresh=true")
    assert resp.headers["x-cache"] == "STALE"
    fetch.assert_not_called()


def test_force_refresh_bypasses_the_cache_and_refetches(mock_cache, fetch, client):
    resp = client().get("/test/1?forceRefresh=true")
    assert resp.status_code == 200
    mock_cache.get.assert_not_called()
    fetch.assert_called_once()
    mock_cache.set.assert_called_once()


# --- daily quota (previously untested) -------------------------------------


def _quota_config() -> Config:
    return _make_config(name="FMP", daily_limit=2)


def test_quota_under_limit_allows_the_fetch(mock_cache, fetch, client):
    mock_cache.incr_with_ttl = AsyncMock(return_value=1)
    assert client(_quota_config()).get("/test/1").status_code == 200
    fetch.assert_called_once()


def test_quota_counter_key_is_route_name_and_utc_day(mock_cache, fetch, client):
    from datetime import datetime, timezone
    client(_quota_config()).get("/test/1")
    key, ttl = mock_cache.incr_with_ttl.call_args.args
    assert key == f"limit:FMP:{datetime.now(timezone.utc):%Y-%m-%d}"
    assert ttl > 86400  # must outlive the day it counts


def test_quota_exceeded_serves_stale(mock_cache, fetch, client):
    mock_cache.incr_with_ttl = AsyncMock(return_value=3)
    mock_cache.get_fresh_or_stale = AsyncMock(return_value="stale_value")
    resp = client(_quota_config()).get("/test/1")
    assert (resp.status_code, resp.text) == (200, "stale_value")
    assert resp.headers["x-cache-stale-reason"] == "quota-exceeded"
    fetch.assert_not_called()


def test_quota_exceeded_without_stale_returns_503(mock_cache, fetch, client):
    mock_cache.incr_with_ttl = AsyncMock(return_value=99)
    mock_cache.get_fresh_or_stale = AsyncMock(return_value=None)
    assert client(_quota_config()).get("/test/1").status_code == 503
    fetch.assert_not_called()


def test_cache_hit_does_not_consume_quota(mock_cache, fetch, client):
    mock_cache.get = AsyncMock(return_value="cached_value")
    assert client(_quota_config()).get("/test/1").status_code == 200
    mock_cache.incr_with_ttl.assert_not_called()


def test_route_without_daily_limit_never_counts(mock_cache, fetch, client):
    client().get("/test/1")
    mock_cache.incr_with_ttl.assert_not_called()


# --- upstream failures -----------------------------------------------------


def test_upstream_error_serves_stale(mock_cache, fetch, client):
    fetch.side_effect = UpstreamError("http://example.com/1", 429)
    mock_cache.get_fresh_or_stale = AsyncMock(return_value="stale_value")
    resp = client().get("/test/1")
    assert (resp.text, resp.headers["x-cache"]) == ("stale_value", "STALE")
    assert resp.headers["x-cache-stale-reason"] == "upstream-429"


def test_upstream_error_without_stale_returns_503(mock_cache, fetch, client):
    fetch.side_effect = UpstreamError("http://example.com/1", 500)
    mock_cache.get_fresh_or_stale = AsyncMock(return_value=None)
    assert client().get("/test/1").status_code == 503


def test_upstream_404_passes_through(mock_cache, fetch, client):
    """A 404 means "no data for this key" — not a transient outage, so it is neither
    retried against stale nor reported as a gateway failure."""
    fetch.side_effect = UpstreamError("http://example.com/1", 404)
    assert client().get("/test/1").status_code == 404
    mock_cache.get_fresh_or_stale.assert_not_called()


def test_transport_failure_serves_stale(mock_cache, fetch, client):
    """A timeout is transient, so the cached value beats a 502."""
    fetch.side_effect = UpstreamError("http://example.com/1", 504)
    mock_cache.get_fresh_or_stale = AsyncMock(return_value="stale_value")
    resp = client().get("/test/1")
    assert (resp.status_code, resp.text) == (200, "stale_value")
    assert resp.headers["x-cache-stale-reason"] == "upstream-504"


def test_extraction_error_is_502_and_never_serves_stale(mock_cache, fetch, client):
    """A broken selector or renamed json_field would be indistinguishable from correct
    stale data, so it must fail loudly instead."""
    fetch.side_effect = ExtractionError("label 'Yield' not found")
    mock_cache.get_fresh_or_stale = AsyncMock(return_value="stale_value")
    resp = client().get("/test/1")
    assert resp.status_code == 502
    mock_cache.get_fresh_or_stale.assert_not_called()
    mock_cache.set.assert_not_called()


# --- cache browser / admin endpoints ---------------------------------------


def test_stats_page_renders(client):
    resp = client().get("/stats")
    assert resp.status_code == 200
    assert "Cache Browser" in resp.text
    assert 'id="cache-filter"' in resp.text
    assert 'id="invalidate-btn"' in resp.text


def test_stats_page_lists_entries(mock_cache, client):
    mock_cache._test_keys = ["test:AAPL"]
    mock_cache._test_heads = {"test:AAPL": "1700000000|"}
    mock_cache._test_previews = {"test:AAPL": "0.05"}
    resp = client().get("/stats")
    assert "AAPL" in resp.text
    assert "0.05" in resp.text


def test_stats_page_embeds_json_not_javascript(mock_cache, client):
    """Values are embedded as JSON in a data block, so "</script>" inside a cached
    upstream body cannot break out into executable script."""
    mock_cache._test_keys = ["test:AAPL"]
    mock_cache._test_heads = {"test:AAPL": "1700000000|"}
    mock_cache._test_previews = {"test:AAPL": "</script><script>alert(1)</script>"}
    resp = client().get("/stats")
    assert "<script>alert(1)</script>" not in resp.text
    assert "alert(1)" in resp.text  # present, but escaped


def test_invalidate_keys_deletes_exactly_those_keys(mock_cache, client):
    keys = ["ohlcv:AAPL:2025-01-01:2026-01-01", "fundamentals:AAPL:mda"]
    resp = client().post("/stats/invalidate-keys", json={"keys": keys})
    assert resp.status_code == 200
    mock_cache.delete_keys.assert_awaited_once_with(keys)


def test_invalidate_keys_surfaces_a_rejected_key(mock_cache, client):
    """A caller must not be able to turn a key into a pattern and flush a prefix."""
    mock_cache.delete_keys = AsyncMock(side_effect=ValueError("unsafe cache key: 'ohlcv:*'"))
    resp = client().post("/stats/invalidate-keys", json={"keys": ["ohlcv:*"]})
    assert resp.status_code == 422
    assert "unsafe" in resp.json()["error"]


@pytest.mark.parametrize("body", [{}, {"keys": "nope"}, {"keys": [1, 2]}, []])
def test_invalidate_keys_validates_the_body(mock_cache, client, body):
    assert client().post("/stats/invalidate-keys", json=body).status_code == 422
    mock_cache.delete_keys.assert_not_called()


def test_reset_cache_deletes_a_prefix(mock_cache, client):
    resp = client().post("/stats/reset-cache/ohlcv")
    assert resp.json() == {"ok": True, "deleted": 0}
    mock_cache.delete_pattern.assert_awaited_once_with("ohlcv:*")


@pytest.mark.parametrize("prefix", ["*", "ohlcv:*", "a b", "a[b]c"])
def test_reset_cache_rejects_a_prefix_that_is_a_pattern(mock_cache, client, prefix):
    """The prefix becomes part of a SCAN pattern — `prefix=*` would flush everything."""
    resp = client().post(f"/stats/reset-cache/{prefix}")
    assert resp.status_code == 422
    assert "unsafe" in resp.json()["error"]
    mock_cache.delete_pattern.assert_not_called()


@pytest.mark.parametrize("path", ["/stats/reset-cache/a/b", "/stats/reset-cache/a%2Fb"])
def test_reset_cache_prefix_cannot_span_key_segments(mock_cache, client, path):
    """A slash in the prefix is stopped by routing, so it cannot widen the SCAN."""
    assert client().post(path).status_code == 404
    mock_cache.delete_pattern.assert_not_called()


def test_reset_stats_clears_counters(client):
    assert client().post("/stats/reset").json() == {"ok": True}


# --- per-route key attribution (the dashboard double-count bug) ------------


def _sibling_config() -> Config:
    """Two routes sharing the "ohlcv" prefix — grouping by prefix merged their cards."""
    return Config(redis=RedisConfig(), routes=[
        RouteConfig(
            path="/ohlcv/{ticker}",
            url="http://up/ohlcv/{ticker}?start={start}&end={end}",
            cache_ttl=60,
            query_params=["start", "end"],
        ),
        RouteConfig(
            path="/ohlcv/fund/{ticker}",
            url="http://up/fund/{ticker}?start={start}&end={end}",
            cache_ttl=60,
            query_params=["start", "end"],
        ),
    ])


def test_sibling_routes_count_only_their_own_keys(mock_cache, client):
    mock_cache._test_keys = [
        "ohlcv:AAPL:2025-01-01:2026-01-01",
        "ohlcv:fund:VWCE:2025-01-01:2026-01-01",
    ]
    mock_cache._test_heads = {k: "1700000000|" for k in mock_cache._test_keys}
    mock_cache._test_previews = {
        "ohlcv:AAPL:2025-01-01:2026-01-01": "a",
        "ohlcv:fund:VWCE:2025-01-01:2026-01-01": "b",
    }
    resp = client(_sibling_config()).get("/stats")
    # Each card counts 1, not 2 — the old prefix grouping reported 2 on both.
    assert resp.text.count("Redis keys: 1") == 2
    assert "Redis keys: 2" not in resp.text


def test_entry_label_is_the_path_param_not_a_literal_segment(mock_cache, client):
    """"/ohlcv/fund/{ticker}" labels VWCE, not "fund"."""
    mock_cache._test_keys = ["ohlcv:fund:VWCE:2025-01-01:2026-01-01"]
    mock_cache._test_heads = {"ohlcv:fund:VWCE:2025-01-01:2026-01-01": "1700000000|"}
    mock_cache._test_previews = {"ohlcv:fund:VWCE:2025-01-01:2026-01-01": "x"}
    resp = client(_sibling_config()).get("/stats")
    assert "VWCE" in resp.text


def test_unowned_keys_are_logged_not_attributed(mock_cache, client, caplog):
    """A key matching no route must be visible, not silently folded into a card."""
    mock_cache._test_keys = ["orphan:key:1"]
    mock_cache._test_heads = {"orphan:key:1": "1700000000|"}
    with caplog.at_level("INFO", logger="cachest"):
        client().get("/stats")
    assert any("matched no route" in r.message for r in caplog.records)


def test_stats_page_ignores_cachests_own_bookkeeping_keys(mock_cache, client):
    """Regression: cachest stores its counters and quota in the SAME Redis database
    ("stats:/ohlcv/{ticker}" is a hash, "limit:FMP:<date>" a counter). Walking the whole
    keyspace and reading every value made GET /stats fail with WRONGTYPE and 500.

    Bookkeeping keys match no route pattern, so they are never even read.
    """
    mock_cache._test_keys = ["test:AAPL", "stats:/test/{id}", "limit:FMP:2026-05-13"]
    mock_cache._test_heads = {"test:AAPL": "1700000000|"}
    mock_cache._test_previews = {"test:AAPL": "0.05"}

    read = []
    real_read_heads = mock_cache.read_heads

    async def _tracking_read_heads(keys):
        read.extend(keys)
        return await real_read_heads(keys)

    mock_cache.read_heads = _tracking_read_heads

    resp = client().get("/stats")
    assert resp.status_code == 200
    assert "0.05" in resp.text
    # Only the real cache key was read; the hashes/counters were never touched.
    assert read == ["test:AAPL"]


def test_stats_page_reads_only_value_heads(mock_cache, client):
    """Regression: /stats OOM-killed the prod pod (128Mi limit) when it read whole
    cached values. The real keyspace is ~50MB over ~1100 keys with a 1.1MB maximum, so
    the dashboard must read only the "<ts>|" head, and previews only for shown rows.

    The fake values are generated inside the traced window so the allocation models
    Redis handing the body over — a pre-built list would never show up in the peak.
    """
    import tracemalloc

    keys = [f"ohlcv:SYM{i}:2026-01-01:2026-02-01" for i in range(60)]
    mock_cache._test_keys = keys
    mock_cache._test_heads = {k: "1700000000|" for k in keys}

    async def _previews(ks, length=80):
        # 1.1 MB is the largest value measured in prod; built here, inside the traced
        # window, so materialising all of them at once would show up in the peak.
        return {k: ("x" * 1_100_000)[:length] for k in ks}

    mock_cache.read_previews = _previews

    tracemalloc.start()
    resp = client().get("/stats")
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert resp.status_code == 200
    assert resp.text.count('class="route-path"') >= 1
    # 60 x 1.1MB = 66MB if the bodies were ever resident together.
    assert peak < 20_000_000, f"peak {peak // 1_000_000}MB — whole values are being read"


def test_stats_page_previews_are_truncated(mock_cache, client):
    """A cached value is an upstream body and can be arbitrarily large; only a short
    preview belongs in the page."""
    mock_cache._test_keys = ["test:AAPL"]
    mock_cache._test_heads = {"test:AAPL": "1700000000|"}

    async def _previews(ks, length=80):
        return {k: ("y" * 50_000)[:length] for k in ks}

    mock_cache.read_previews = _previews

    resp = client().get("/stats")
    assert "y" * 50_000 not in resp.text
    assert "y" * 80 in resp.text


def test_stats_page_caps_the_number_of_entries(mock_cache, client):
    from main import MAX_ENTRIES
    n = MAX_ENTRIES + 50
    keys = [f"test:SYM{i}" for i in range(n)]
    mock_cache._test_keys = keys
    mock_cache._test_heads = {k: f"{1700000000 + i}|" for i, k in enumerate(keys)}
    mock_cache._test_previews = {k: "v" for k in keys}

    resp = client().get("/stats")
    assert resp.text.count('"ticker"') <= MAX_ENTRIES
    # Previews are fetched only for displayed rows, never for the whole keyspace.
    assert resp.text.count('"ticker"') < n


# --- operational endpoints -------------------------------------------------


def test_health(client):
    assert client().get("/health").json() == {"status": "ok"}


def test_meta_reports_service_and_version(monkeypatch, client):
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert client().get("/__meta").json() == {
        "service": "cachest", "impl": "real", "version": "0.0.0-dev",
    }


def test_stats_page_references_assets_relatively(mock_cache, client):
    """Regression: behind the TLS ingress, url_for() emitted absolute http:// URLs
    because uvicorn does not trust X-Forwarded-Proto. The browser then blocked the CSS
    and JS as mixed content — the page rendered unstyled and the cache browser never
    ran. TestClient hides this because its base URL is already http://testserver, so
    the reference must be asserted rather than assumed.
    """
    body = client().get("/stats").text
    assert 'href="/static/stats.css"' in body
    assert 'src="/static/stats.js"' in body
    # No absolute URL may appear in an attribute — that is what the browser blocks.
    # (A bare "http://" in prose is fine, hence the attribute-scoped check.)
    assert '="http://' not in body
    assert "='http://" not in body
    assert '="https://testserver/static' not in body


@pytest.mark.parametrize("path", ["/static/stats.css", "/static/stats.js"])
def test_static_assets_are_served(client, path):
    """The stats page's CSS/JS must resolve, or the page renders unstyled."""
    assert client().get(path).status_code == 200


def test_metrics_returns_prometheus_text(client):
    c = client()
    c.get("/health")
    resp = c.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "http_server_request_duration_seconds" in resp.text


def test_client_metrics_are_bucketed_per_upstream_host(client):
    cfg = _make_config(url="http://openst/{id}")
    c = client(cfg)
    with respx.mock:
        respx.get("http://openst/1").mock(return_value=httpx.Response(200, text="ok"))
        assert c.get("/test/1").headers["x-cache"] == "MISS"
    metrics = c.get("/metrics")
    assert "http_client_request_duration_seconds" in metrics.text
    assert 'server_address="openst"' in metrics.text


# --- the shipped config ----------------------------------------------------


def test_every_configured_route_registers_a_fastapi_route():
    """A path that fails to register silently disappears from the API. Loading
    config.yaml proves the config is valid; this proves it is actually wired up."""
    cfg = load(REAL_CONFIG)
    with patch("main.RedisCache", return_value=MagicMock()):
        app = create_app(cfg)
    registered = {r.path for r in app.routes if hasattr(r, "path")}
    missing = [r.path for r in cfg.routes if r.path not in registered]
    assert not missing, f"routes not registered: {missing}"


def test_configured_query_param_routes_reject_a_missing_param(client):
    cfg = load(REAL_CONFIG)
    route = next(r for r in cfg.routes if r.query_params)
    path = "/" + "/".join(
        "x" if seg.startswith("{") else seg for seg in route.path.strip("/").split("/")
    )
    with TestClient(create_app(cfg)) as c:
        assert c.get(path).status_code == 422


def test_every_route_key_matches_its_own_attribution_pattern():
    """The key a route writes must be one the stats page attributes back to it."""
    for route in load(REAL_CONFIG).routes:
        key = cache_key(
            route.path,
            {p: "X" for p in path_params_of(route.path)},
            {p: "X" for p in route.query_params},
        )
        assert key_pattern(route.path, route.query_params).match(key), route.path
