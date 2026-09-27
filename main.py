import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from httpx import AsyncClient
from pythonjsonlogger.json import JsonFormatter

load_dotenv()

from cache import CacheMiss, CacheStale, RedisCache
from config import QUOTA_TTL_SECONDS, Config, RouteConfig, load
from fetcher import ExtractionError, UpstreamError, build_url, fetch
from keys import cache_key, key_label, key_pattern, key_prefix, safe_key
from otel import setup_otel
from rate_limiter import RateLimiter
import stats

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yaml"
BUCKETS = 30  # days shown in the stats histogram
MAX_ENTRIES = 2000  # rows handed to the cache browser

logger = logging.getLogger("cachest")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "service"},
        )
    )
    logger.addHandler(_handler)


def _respond(route_path: str, value: str, x_cache: str, **extra_headers) -> PlainTextResponse:
    stats.record(route_path, x_cache)
    return PlainTextResponse(value, headers={"X-Cache": x_cache, **extra_headers})


def _error(route: RouteConfig, message: str, status_code: int) -> PlainTextResponse:
    stats.record(route.path, "ERROR")
    return PlainTextResponse(message, status_code=status_code)


def make_handler(route: RouteConfig, cache: RedisCache, limiter: RateLimiter, client: AsyncClient):
    async def handler(request: Request) -> PlainTextResponse:
        path_params: dict[str, Any] = dict(request.path_params)
        query_values = {p: request.query_params.get(p) for p in route.query_params}
        missing = [p for p, v in query_values.items() if v is None]
        if missing:
            return _error(
                route,
                f"missing required query parameter(s): {', '.join(missing)}",
                422,
            )

        supplied = {k: v or "" for k, v in query_values.items()}
        key = cache_key(route.path, path_params, supplied)
        force_refresh = request.query_params.get("forceRefresh") == "true"

        if not force_refresh:
            try:
                value = await cache.get(key, route.cache_ttl)
                return _respond(route.path, value, "HIT")
            except (CacheMiss, CacheStale):
                # Expected outcomes, not failures: absent, or expired but still
                # available for the stale fallbacks below.
                pass
            except Exception as e:
                # Redis being unreachable must not take the endpoint down: the fetch
                # below can still answer, just uncached.
                logger.warning("cache GET %r failed: %s — proceeding without cache", key, e)

        if not await limiter.acquire():
            logger.warning(
                "[rate-limit] max_wait exceeded for %r (forceRefresh=%s) — no upstream call made",
                key, force_refresh,
            )
            stale = await cache.get_fresh_or_stale(key, route.cache_ttl)
            if stale is not None:
                return _respond(
                    route.path, stale, "STALE", **{"X-Cache-Stale-Reason": "rate-limited"}
                )
            return _error(route, "rate limit exceeded and no cached value available", 503)

        if route.daily_limit > 0:
            count = await cache.incr_with_ttl(
                f"limit:{route.name}:{datetime.now(timezone.utc):%Y-%m-%d}", QUOTA_TTL_SECONDS
            )
            if count > route.daily_limit:
                logger.warning(
                    "[quota] daily limit %d exceeded for %r (count=%d)",
                    route.daily_limit, route.name, count,
                )
                stale = await cache.get_fresh_or_stale(key, route.cache_ttl)
                if stale is not None:
                    return _respond(
                        route.path, stale, "STALE", **{"X-Cache-Stale-Reason": "quota-exceeded"}
                    )
                return _error(route, "daily upstream limit reached", 503)

        url = build_url(route.url, path_params, route.api_key, supplied)
        try:
            value = await fetch(url, route.extract, route.json_field, timeout=route.fetch_timeout, client=client)
        except ExtractionError as e:
            # The response arrived but we could not read it — a broken selector or a
            # renamed json_field. Stale would be a silent lie here, so fail loudly.
            logger.error("[extract-error] %r %s", route.name or route.path, e)
            return _error(route, "upstream response could not be parsed", 502)
        except UpstreamError as e:
            # A 404 means "no data for this key" (e.g. empty calendar window, unknown
            # symbol) — not a transient outage. Pass it through so consumers can
            # degrade gracefully; stale caching would be wrong.
            if e.status_code == 404:
                logger.info("[not-found] %r returned HTTP 404", e.url)
                return _error(route, "upstream returned 404 and no cached value available", 404)
            logger.warning("[upstream-error] %r returned HTTP %d — serving stale", e.url, e.status_code)
            stale = await cache.get_fresh_or_stale(key, route.cache_ttl)
            if stale is not None:
                return _respond(
                    route.path, stale, "STALE", **{"X-Cache-Stale-Reason": f"upstream-{e.status_code}"}
                )
            return _error(route, f"upstream returned {e.status_code} and no cached value available", 503)

        try:
            await cache.set(key, value, route.stale_ttl)
        except Exception as e:
            logger.warning("cache SET %r failed: %s", key, e)

        return _respond(route.path, value, "MISS")

    return handler


def _age_buckets(pairs: list[tuple[str, str]]) -> list[int]:
    """Count entries per day-age, oldest bucket = 29+ days."""
    now = int(time.time())
    buckets = [0] * BUCKETS
    for _key, raw in pairs:
        try:
            ts_str, _ = raw.split("|", 1)
            age_days = (now - int(ts_str)) // 86400
        except (ValueError, IndexError):
            continue
        if 0 <= age_days < BUCKETS:
            buckets[age_days] += 1
        elif age_days >= BUCKETS:
            buckets[-1] += 1
    return buckets


def _histogram_html(buckets: list[int]) -> list[dict[str, Any]]:
    """Bar heights + labels for the age histogram."""
    peak = max(buckets) or 1
    out = []
    for i, count in enumerate(buckets):
        out.append({
            "pct": int(count / peak * 100),
            "count": count,
            "label": f"{i}d ago" if i else "today",
            "short": "today" if i == 0 else (f"{i}d" if i % 5 == 0 else ""),
        })
    return out


async def _render_stats(config: Config, cache: RedisCache) -> dict[str, Any]:
    """Everything the stats page needs, in one keyspace pass.

    A single SCAN feeds every card. Keys are attributed to a route by matching each
    route's own compiled pattern, so sibling routes that share a leading path segment
    ("/ohlcv/{ticker}" vs "/ohlcv/fund/{ticker}") each count only their own keys.
    """
    all_pairs = await cache.scan_all_with_values()

    patterns = [(r, key_pattern(r.path, r.query_params)) for r in config.routes]
    by_route: dict[int, list[tuple[str, str]]] = {i: [] for i in range(len(config.routes))}
    unowned = 0
    for key, raw in all_pairs:
        for i, (_route, pattern) in enumerate(patterns):
            if pattern.match(key):
                by_route[i].append((key, raw))
                break
        else:
            unowned += 1

    all_stats = stats.all_routes()
    family_sizes: dict[str, int] = {}
    for r in config.routes:
        prefix = key_prefix(r.path)
        family_sizes[prefix] = family_sizes.get(prefix, 0) + 1

    cards = []
    for i, route in enumerate(config.routes):
        pairs = by_route[i]
        s = all_stats.get(route.path) or stats.RouteStats()
        cards.append({
            "path": route.path,
            "upstream": route.url[:60] + ("…" if len(route.url) > 60 else ""),
            "prefix": key_prefix(route.path),
            "family_size": family_sizes[key_prefix(route.path)],
            "total": s.total,
            "hits": s.hits,
            "misses": s.misses,
            "stale": s.stale,
            "errors": s.errors,
            "total_keys": len(pairs),
            "buckets": _histogram_html(_age_buckets(pairs)),
        })

    # Newest first, one row per cache key, truncated so a large keyspace cannot
    # produce an unbounded HTML payload.
    rows: list[tuple[int, str, str, str, str]] = []
    for i, route in enumerate(config.routes):
        for key, raw in by_route[i]:
            try:
                ts_str, value = raw.split("|", 1)
                ts = int(ts_str)
            except (ValueError, IndexError):
                continue
            rows.append((ts, route.path, key_label(route.path, key), value[:80], key))
    rows.sort(key=lambda r: r[0], reverse=True)

    if len(rows) > MAX_ENTRIES:
        logger.info("stats: cache browser truncated from %d to %d entries", len(rows), MAX_ENTRIES)
        rows = rows[:MAX_ENTRIES]

    if unowned:
        logger.info("stats: %d key(s) matched no route pattern", unowned)

    entries = [
        {"key": key, "ticker": label, "route": route_path, "ts": ts, "value": value}
        for ts, route_path, label, value, key in rows
    ]
    return {"cards": cards, "entries": entries}


def create_app(config: Config) -> FastAPI:
    cache = RedisCache(
        host=config.redis.host,
        port=config.redis.port,
        password=config.redis.password,
        db=config.redis.db,
    )
    templates = Jinja2Templates(directory=BASE_DIR / "templates")
    # One pooled client for every upstream, created up front and shared by all routes:
    # connections are reused instead of rebuilt per fetch. Per-request timeouts still
    # come from each route's fetch_timeout.
    http = AsyncClient(follow_redirects=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("cachest starting — %d route(s) registered", len(config.routes))
        for r in config.routes:
            logger.info(
                "  %s -> %s (cache_ttl: %ss, stale_ttl: %ss, fetch_interval: %ss, fetch_max_wait: %ss, fetch_timeout: %ss)",
                r.path, r.url, r.cache_ttl, r.stale_ttl, r.fetch_interval, r.fetch_max_wait, r.fetch_timeout,
            )
        await stats.load_from_redis(cache)
        stats.init(cache)
        try:
            yield
        finally:
            await http.aclose()
            await cache.close()

    app = FastAPI(lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
    setup_otel(app, "cachest")

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "http_request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(elapsed, 1),
            },
        )
        return response

    @app.get("/health", include_in_schema=False)
    async def health():
        return JSONResponse({"status": "ok"})

    _favicon = (BASE_DIR / "favicon.svg").read_bytes()

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(_favicon, media_type="image/svg+xml")

    @app.get("/__meta", include_in_schema=False)
    async def meta():
        return JSONResponse(
            {
                "service": "cachest",
                "impl": "real",
                "version": os.environ.get("APP_VERSION") or "0.0.0-dev",
            }
        )

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/stats")

    @app.get("/stats", response_class=HTMLResponse, include_in_schema=False)
    async def stats_page(request: Request):
        return templates.TemplateResponse(
            request, "stats.html", await _render_stats(config, cache)
        )

    @app.post("/stats/reset", include_in_schema=False)
    async def stats_reset():
        stats.reset_all(cache)
        return JSONResponse({"ok": True})

    @app.post("/stats/reset-cache/{prefix}", include_in_schema=False)
    async def stats_reset_cache(prefix: str):
        """Flush every key under a path prefix.

        The prefix becomes part of a SCAN pattern, so it is validated first: without
        that, `prefix=*` would match the whole keyspace.
        """
        try:
            safe_key(prefix)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=422)
        deleted = await cache.delete_pattern(f"{prefix}:*")
        return JSONResponse({"ok": True, "deleted": deleted})

    @app.post("/stats/invalidate-keys", include_in_schema=False)
    async def invalidate_keys(request: Request):
        """Delete exactly the listed cache keys.

        Keys are validated against the charset cachest itself generates, so a caller
        cannot turn a key into a wildcard and flush a whole prefix by accident.
        """
        body = await request.json()
        keys = body.get("keys") if isinstance(body, dict) else None
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            return JSONResponse({"ok": False, "error": "expected {\"keys\": [str]} "}, status_code=422)
        try:
            deleted = await cache.delete_keys(keys)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=422)
        return JSONResponse({"ok": True, "deleted": deleted})

    for route in config.routes:
        limiter = RateLimiter(interval=route.fetch_interval, max_wait=route.fetch_max_wait)
        app.add_api_route(
            route.path,
            make_handler(route, cache, limiter, http),
            methods=["GET"],
            response_class=PlainTextResponse,
        )

    return app


cfg = load(CONFIG_PATH)
app = create_app(cfg)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
