# Per-Route Rate Limiter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent each configured route from querying its remote URL more often than a configurable minimum interval, with stale-cache fallback when the wait would be too long or the upstream fails.

**Architecture:** A `RateLimiter` class (one per route, created at app startup) uses an `asyncio.Lock` + timestamp to serialise fetches and enforce minimum interval. `make_handler` calls `limiter.acquire()` before every remote fetch; `False` means serve stale. Upstream errors (403/429/502) also fall back to stale cache via a new `UpstreamError` exception.

**Tech Stack:** Python 3.12, asyncio, FastAPI, httpx, redis-asyncio, pytest, pytest-asyncio

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `config.py` | Modify | Add `fetch_interval` + `fetch_max_wait` to `RouteConfig`; parse in `load()` |
| `rate_limiter.py` | Create | `RateLimiter` class — lock + timestamp, `acquire() -> bool` |
| `fetcher.py` | Modify | Replace `RateLimitedError` with `UpstreamError` covering 403/429/502 |
| `main.py` | Modify | Wire `RateLimiter` per route; update handler to use `acquire()` and stale fallback |
| `config.yaml` | Modify | Add `fetch_interval`/`fetch_max_wait` to example routes |
| `tests/test_rate_limiter.py` | Create | Unit tests for `RateLimiter` |
| `tests/test_fetcher.py` | Create | Unit tests for `UpstreamError` paths |
| `tests/test_main.py` | Create | Integration tests for handler rate-limit + stale fallback paths |

---

### Task 1: Add `fetch_interval` and `fetch_max_wait` to config

**Files:**
- Modify: `config.py`
- Modify: `config.yaml`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
import pytest
from pathlib import Path
from config import load

YAML = """
redis:
  host: localhost
  port: 6379
  password: ""
  db: 0
routes:
  - path: /test/{id}
    url: "http://example.com/{id}"
    cache_ttl: 60
    fetch_interval: 3.5
    fetch_max_wait: 7.0
  - path: /defaults/{id}
    url: "http://example.com/defaults/{id}"
    cache_ttl: 60
"""

def test_fetch_interval_parsed(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(YAML)
    cfg = load(f)
    assert cfg.routes[0].fetch_interval == 3.5
    assert cfg.routes[0].fetch_max_wait == 7.0

def test_fetch_interval_defaults(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(YAML)
    cfg = load(f)
    assert cfg.routes[1].fetch_interval == 2.0
    assert cfg.routes[1].fetch_max_wait == 4.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/i318088/prv/pfire/cachest
source .venv/bin/activate
pip install pytest pytest-asyncio --quiet
pytest tests/test_config.py -v
```

Expected: `FAILED` — `RouteConfig` has no `fetch_interval` attribute.

- [ ] **Step 3: Update `config.py`**

In `config.py`, change `RouteConfig`:

```python
@dataclass
class RouteConfig:
    path: str
    url: str
    cache_ttl: int
    extract: ExtractConfig = field(default_factory=ExtractConfig)
    fetch_interval: float = 2.0
    fetch_max_wait: float = 4.0
```

In `load()`, update the `routes.append(RouteConfig(...))` call:

```python
routes.append(RouteConfig(
    path=r["path"],
    url=r["url"],
    cache_ttl=int(r["cache_ttl"]),
    extract=extract,
    fetch_interval=float(r.get("fetch_interval", 2.0)),
    fetch_max_wait=float(r.get("fetch_max_wait", 4.0)),
))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Update `config.yaml` with example values**

Add `fetch_interval` and `fetch_max_wait` to both routes:

```yaml
redis:
  host: redis          # use "localhost" when running outside Docker
  port: 6379
  password: ""
  db: 0

routes:
  - path: /dy/{ticker}
    url: "https://dividendhistory.org/payout/{ticker}/"
    extract:
      selector: "dl.metrics-list .metric-row"
      label: "Yield"
      field: "dd"
    cache_ttl: 86400          # seconds (24h)
    fetch_interval: 2         # min seconds between remote fetches
    fetch_max_wait: 4         # max queue wait before falling back to stale

  - path: /price/{ticker}
    url: "https://someapi.com/price/{ticker}"
    # no extract block = endpoint returns plain text value
    cache_ttl: 300            # 5 minutes
    fetch_interval: 2
    fetch_max_wait: 4
```

- [ ] **Step 6: Commit**

```bash
git init  # if not already a git repo
git add config.py config.yaml tests/test_config.py
git commit -m "feat: add fetch_interval and fetch_max_wait to RouteConfig"
```

---

### Task 2: Implement `RateLimiter`

**Files:**
- Create: `rate_limiter.py`
- Create: `tests/test_rate_limiter.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_rate_limiter.py`:

```python
import asyncio
import pytest
from rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_first_acquire_returns_true():
    limiter = RateLimiter(interval=2.0, max_wait=4.0)
    result = await limiter.acquire()
    assert result is True


@pytest.mark.asyncio
async def test_immediate_second_acquire_waits_and_returns_true():
    """Second call within interval should sleep and return True if sleep <= max_wait."""
    limiter = RateLimiter(interval=0.1, max_wait=1.0)
    await limiter.acquire()
    start = asyncio.get_event_loop().time()
    result = await limiter.acquire()
    elapsed = asyncio.get_event_loop().time() - start
    assert result is True
    assert elapsed >= 0.05  # slept at least half the interval


@pytest.mark.asyncio
async def test_acquire_returns_false_when_wait_exceeds_max():
    """If required sleep > max_wait, acquire returns False immediately."""
    limiter = RateLimiter(interval=10.0, max_wait=0.5)
    await limiter.acquire()  # set last_fetch
    start = asyncio.get_event_loop().time()
    result = await limiter.acquire()
    elapsed = asyncio.get_event_loop().time() - start
    assert result is False
    assert elapsed < 1.0  # did not actually sleep the full interval


@pytest.mark.asyncio
async def test_acquire_true_after_interval_has_passed():
    """After enough time passes, acquire returns True without sleeping."""
    limiter = RateLimiter(interval=0.05, max_wait=1.0)
    await limiter.acquire()
    await asyncio.sleep(0.1)  # wait longer than interval
    result = await limiter.acquire()
    assert result is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_rate_limiter.py -v
```

Expected: `ERROR` — `rate_limiter` module not found.

- [ ] **Step 3: Create `rate_limiter.py`**

```python
import asyncio
import time


class RateLimiter:
    def __init__(self, interval: float, max_wait: float) -> None:
        self._interval = interval
        self._max_wait = max_wait
        self._lock = asyncio.Lock()
        self._last_fetch: float = 0.0

    async def acquire(self) -> bool:
        async with self._lock:
            sleep = self._interval - (time.monotonic() - self._last_fetch)
            if sleep <= 0:
                self._last_fetch = time.monotonic()
                return True
            if sleep > self._max_wait:
                return False
            await asyncio.sleep(sleep)
            self._last_fetch = time.monotonic()
            return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_rate_limiter.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add rate_limiter.py tests/test_rate_limiter.py
git commit -m "feat: add RateLimiter with asyncio lock and configurable interval/max_wait"
```

---

### Task 3: Replace `RateLimitedError` with `UpstreamError` in `fetcher.py`

**Files:**
- Modify: `fetcher.py`
- Create: `tests/test_fetcher.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_fetcher.py`:

```python
import pytest
import httpx
import respx
from fetcher import fetch, UpstreamError
from config import ExtractConfig


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_upstream_error_on_429():
    respx.get("http://example.com/test").mock(return_value=httpx.Response(429))
    with pytest.raises(UpstreamError) as exc_info:
        await fetch("http://example.com/test", ExtractConfig())
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_upstream_error_on_403():
    respx.get("http://example.com/test").mock(return_value=httpx.Response(403))
    with pytest.raises(UpstreamError) as exc_info:
        await fetch("http://example.com/test", ExtractConfig())
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_upstream_error_on_502():
    respx.get("http://example.com/test").mock(return_value=httpx.Response(502))
    with pytest.raises(UpstreamError) as exc_info:
        await fetch("http://example.com/test", ExtractConfig())
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_text_on_200():
    respx.get("http://example.com/test").mock(
        return_value=httpx.Response(200, text="42.5%")
    )
    result = await fetch("http://example.com/test", ExtractConfig())
    assert result == "42.5%"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pip install respx --quiet
pytest tests/test_fetcher.py -v
```

Expected: `FAILED` — `UpstreamError` not importable from `fetcher`.

- [ ] **Step 3: Update `fetcher.py`**

Replace the entire file:

```python
import httpx
from bs4 import BeautifulSoup
from config import ExtractConfig


class UpstreamError(Exception):
    def __init__(self, url: str, status_code: int):
        self.url = url
        self.status_code = status_code
        super().__init__(f"upstream {url!r} returned HTTP {status_code}")


# Keep as alias so any existing imports don't break during transition
RateLimitedError = UpstreamError


async def fetch(url: str, extract: ExtractConfig) -> str:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url)

    if resp.status_code in (403, 429, 502):
        raise UpstreamError(url, resp.status_code)
    resp.raise_for_status()

    if not extract.selector:
        return resp.text.strip()

    return _extract_from_html(resp.text, extract)


def _extract_from_html(html: str, ext: ExtractConfig) -> str:
    soup = BeautifulSoup(html, "lxml")
    for row in soup.select(ext.selector):
        dt = row.find("dt")
        if dt and dt.get_text(strip=True) == ext.label:
            target = row.find(ext.field)
            if target:
                return target.get_text(strip=True)
    raise ValueError(f"label {ext.label!r} not found via selector {ext.selector!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_fetcher.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add fetcher.py tests/test_fetcher.py
git commit -m "feat: replace RateLimitedError with UpstreamError covering 403/429/502"
```

---

### Task 4: Wire `RateLimiter` into `main.py` handler

**Files:**
- Modify: `main.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_main.py`:

```python
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
    mock_cache.get = AsyncMock(return_value="stale_value")
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_main.py -v
```

Expected: multiple failures — `RateLimiter` not imported in `main`, handler doesn't call `acquire()`.

- [ ] **Step 3: Update `main.py`**

Replace the entire file:

```python
import logging
from contextlib import asynccontextmanager
from typing import Any

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response

from cache import CacheMiss, RedisCache
from config import Config, RouteConfig, load
from fetcher import UpstreamError, fetch
from rate_limiter import RateLimiter

logger = logging.getLogger("cachest")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

CONFIG_PATH = "config.yaml"


def _cache_key(path_template: str, path_params: dict[str, str]) -> str:
    """/dy/{ticker} + {"ticker": "AAPL"} → "dy:AAPL" """
    first_seg = path_template.lstrip("/").split("/")[0]
    values = ":".join(path_params.values())
    return f"{first_seg}:{values}" if values else first_seg


def _build_url(template: str, path_params: dict[str, str]) -> str:
    url = template
    for k, v in path_params.items():
        url = url.replace(f"{{{k}}}", v)
    return url


def make_handler(route: RouteConfig, cache: RedisCache, limiter: RateLimiter):
    async def handler(request: Request) -> PlainTextResponse:
        path_params: dict[str, Any] = dict(request.path_params)
        key = _cache_key(route.path, path_params)
        force_refresh = request.query_params.get("forceRefresh") == "true"

        if not force_refresh:
            try:
                value = await cache.get(key)
                return PlainTextResponse(value, headers={"X-Cache": "HIT"})
            except CacheMiss:
                pass
            except Exception as e:
                logger.warning("cache GET %r failed: %s — proceeding without cache", key, e)

        allowed = await limiter.acquire()
        if not allowed:
            logger.warning("rate limiter max_wait exceeded for %r, serving stale", key)
            try:
                stale = await cache.get(key)
                return PlainTextResponse(stale, headers={"X-Cache": "STALE", "X-Cache-Stale-Reason": "rate-limited"})
            except CacheMiss:
                pass
            return PlainTextResponse("rate limit exceeded and no cached value available", status_code=503)

        url = _build_url(route.url, path_params)
        try:
            value = await fetch(url, route.extract)
        except UpstreamError as e:
            logger.warning("upstream %r returned HTTP %d, serving stale", e.url, e.status_code)
            try:
                stale = await cache.get(key)
                return PlainTextResponse(
                    stale,
                    headers={"X-Cache": "STALE", "X-Cache-Stale-Reason": f"upstream-{e.status_code}"},
                )
            except CacheMiss:
                pass
            return PlainTextResponse(
                f"upstream returned {e.status_code} and no cached value available",
                status_code=503,
            )
        except Exception as e:
            logger.error("fetch %r failed: %s", url, e)
            return PlainTextResponse("bad gateway: upstream fetch failed", status_code=502)

        try:
            await cache.set(key, value, route.cache_ttl)
        except Exception as e:
            logger.warning("cache SET %r failed: %s", key, e)

        return PlainTextResponse(value, headers={"X-Cache": "MISS"})

    return handler


def create_app(config: Config) -> FastAPI:
    cache = RedisCache(
        host=config.redis.host,
        port=config.redis.port,
        password=config.redis.password,
        db=config.redis.db,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("cachest starting — %d route(s) registered", len(config.routes))
        for r in config.routes:
            logger.info(
                "  %s -> %s (TTL: %ss, fetch_interval: %ss, fetch_max_wait: %ss)",
                r.path, r.url, r.cache_ttl, r.fetch_interval, r.fetch_max_wait,
            )
        yield
        await cache.close()

    app = FastAPI(lifespan=lifespan)

    _favicon = (Path(__file__).parent / "favicon.svg").read_bytes()

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(_favicon, media_type="image/svg+xml")

    for route in config.routes:
        limiter = RateLimiter(interval=route.fetch_interval, max_wait=route.fetch_max_wait)
        app.add_api_route(
            route.path,
            make_handler(route, cache, limiter),
            methods=["GET"],
            response_class=PlainTextResponse,
        )

    return app


cfg = load(CONFIG_PATH)
app = create_app(cfg)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add main.py rate_limiter.py tests/test_main.py
git commit -m "feat: wire RateLimiter per route into handler with stale fallback"
```

---

### Task 5: Build Docker image and test locally

**Files:** (no code changes — verification only)

- [ ] **Step 1: Build Docker image**

```bash
cd /Users/i318088/prv/pfire/cachest
docker build -t cachest:local .
```

Expected: `Successfully tagged cachest:local` (or equivalent buildkit output).

- [ ] **Step 2: Start the stack**

```bash
docker compose up -d
```

Expected: both `redis` and `cachest` containers running. Check with:

```bash
docker compose ps
```

- [ ] **Step 3: Verify app is up**

```bash
curl -s http://localhost:8080/docs | head -5
```

Expected: HTML response (FastAPI Swagger UI).

- [ ] **Step 4: Test cache miss then hit**

```bash
curl -v http://localhost:8080/dy/AAPL 2>&1 | grep -E "X-Cache|HTTP/"
```

First call: `X-Cache: MISS` (fetches remote, may take a moment).
Second call immediately after:

```bash
curl -v http://localhost:8080/dy/AAPL 2>&1 | grep -E "X-Cache|HTTP/"
```

Expected: `X-Cache: HIT` (served from Redis).

- [ ] **Step 5: Verify rate limiter fires on forceRefresh**

Call forceRefresh twice in quick succession — second should queue:

```bash
curl -v "http://localhost:8080/dy/AAPL?forceRefresh=true" 2>&1 | grep "X-Cache"
curl -v "http://localhost:8080/dy/AAPL?forceRefresh=true" 2>&1 | grep "X-Cache"
```

Check container logs for rate-limiter activity:

```bash
docker compose logs cachest | tail -20
```

Expected: log lines showing fetch timing or "rate limiter max_wait exceeded" if back-to-back calls within interval.

- [ ] **Step 6: Tear down**

```bash
docker compose down
```

- [ ] **Step 7: Commit final state**

```bash
git add -A
git status  # verify only expected files staged
git commit -m "chore: verify rate limiter works end-to-end via Docker"
```
