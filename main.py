import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

import stats
from cache import CacheMiss, CacheStale, RedisCache
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


def _respond(route_path: str, value: str, x_cache: str, **extra_headers) -> PlainTextResponse:
    stats.record(route_path, x_cache)
    return PlainTextResponse(value, headers={"X-Cache": x_cache, **extra_headers})


def make_handler(route: RouteConfig, cache: RedisCache, limiter: RateLimiter):
    async def handler(request: Request) -> PlainTextResponse:
        path_params: dict[str, Any] = dict(request.path_params)
        key = _cache_key(route.path, path_params)
        force_refresh = request.query_params.get("forceRefresh") == "true"

        if not force_refresh:
            try:
                value = await cache.get(key, route.cache_ttl)
                return _respond(route.path, value, "HIT")
            except CacheMiss:
                pass
            except CacheStale:
                pass  # expired but present; fall through to re-fetch
            except Exception as e:
                logger.warning("cache GET %r failed: %s — proceeding without cache", key, e)

        allowed = await limiter.acquire()
        if not allowed:
            logger.warning("[rate-limit] max_wait exceeded for %r (forceRefresh=%s) — no upstream call made", key, force_refresh)
            try:
                stale = await cache.get(key, route.cache_ttl)
                return _respond(route.path, stale, "STALE", **{"X-Cache-Stale-Reason": "rate-limited"})
            except CacheStale as e:
                return _respond(route.path, e.value, "STALE", **{"X-Cache-Stale-Reason": "rate-limited"})
            except CacheMiss:
                pass
            return PlainTextResponse("rate limit exceeded and no cached value available", status_code=503)

        url = _build_url(route.url, path_params)
        try:
            value = await fetch(url, route.extract)
        except UpstreamError as e:
            logger.warning("[upstream-error] %r returned HTTP %d — serving stale", e.url, e.status_code)
            try:
                stale = await cache.get(key, route.cache_ttl)
                return _respond(route.path, stale, "STALE", **{"X-Cache-Stale-Reason": f"upstream-{e.status_code}"})
            except CacheStale as exc:
                return _respond(route.path, exc.value, "STALE", **{"X-Cache-Stale-Reason": f"upstream-{e.status_code}"})
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
            await cache.set(key, value, route.stale_ttl)
        except Exception as e:
            logger.warning("cache SET %r failed: %s", key, e)

        return _respond(route.path, value, "MISS")

    return handler


async def _render_stats(config: Config, cache: RedisCache) -> str:
    now = int(time.time())
    route_map = {r.path: r for r in config.routes}
    all_stats = stats.all_routes()

    cards_html = []
    for route in config.routes:
        path = route.path
        s = all_stats.get(path, stats.RouteStats())

        prefix = path.lstrip("/").split("/")[0]
        raw_values = await cache.scan_prefix(prefix)

        buckets = [0] * 30
        for raw in raw_values:
            try:
                ts_str, _ = raw.split("|", 1)
                age_days = (now - int(ts_str)) // 86400
                if 0 <= age_days < 30:
                    buckets[age_days] += 1
            except (ValueError, IndexError):
                pass

        total_keys = sum(buckets)
        max_bucket = max(buckets) if any(buckets) else 1

        bars_html = []
        for i, count in enumerate(buckets):
            height_pct = int(count / max_bucket * 100) if max_bucket else 0
            label = "today" if i == 0 else (f"{i}d" if i % 5 == 0 else "")
            bars_html.append(f"""
              <div class="bar-wrap">
                <div class="bar" style="height:{height_pct}%" title="{i}d ago: {count} keys"></div>
                <div class="bar-label">{label}</div>
              </div>""")

        upstream_short = route.url[:60] + ("…" if len(route.url) > 60 else "")
        card = f"""
    <div class="card">
      <div class="card-header">
        <span class="route-path">{path}</span>
        <span class="upstream">{upstream_short}</span>
      </div>
      <div class="pills">
        <span class="pill pill-total">Total {s.total}</span>
        <span class="pill pill-hit">HIT {s.hits}</span>
        <span class="pill pill-miss">MISS {s.misses}</span>
        <span class="pill pill-stale">STALE {s.stale}</span>
      </div>
      <div class="redis-keys">Redis keys: {total_keys}</div>
      <div class="chart">{''.join(bars_html)}
      </div>
    </div>"""
        cards_html.append(card)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>cachest / stats</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0f172a; color: #e2e8f0; font-family: system-ui, sans-serif; padding: 2rem; }}
    h1 {{ font-size: 1.25rem; font-weight: 600; color: #94a3b8; margin-bottom: 1.5rem; letter-spacing: 0.05em; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 1.25rem; }}
    .card {{ background: #1e293b; border-radius: 0.75rem; padding: 1.25rem; }}
    .card-header {{ margin-bottom: 0.75rem; }}
    .route-path {{ font-size: 1rem; font-weight: 600; color: #f1f5f9; display: block; }}
    .upstream {{ font-size: 0.75rem; color: #64748b; display: block; margin-top: 0.2rem; word-break: break-all; }}
    .pills {{ display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.75rem; }}
    .pill {{ padding: 0.2rem 0.6rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }}
    .pill-total {{ background: #334155; color: #f1f5f9; }}
    .pill-hit {{ background: #14532d; color: #22c55e; }}
    .pill-miss {{ background: #1e3a5f; color: #3b82f6; }}
    .pill-stale {{ background: #451a03; color: #f59e0b; }}
    .redis-keys {{ font-size: 0.75rem; color: #94a3b8; margin-bottom: 0.75rem; }}
    .chart {{ display: flex; align-items: flex-end; gap: 2px; height: 60px; padding-bottom: 18px; position: relative; }}
    .bar-wrap {{ display: flex; flex-direction: column; align-items: center; flex: 1; height: 100%; justify-content: flex-end; }}
    .bar {{ width: 100%; background: #3b82f6; border-radius: 2px 2px 0 0; min-height: 1px; transition: height 0.2s; }}
    .bar-label {{ font-size: 0.55rem; color: #64748b; margin-top: 2px; white-space: nowrap; }}
  </style>
</head>
<body>
  <h1>cachest / stats</h1>
  <div class="grid">
    {''.join(cards_html)}
  </div>
</body>
</html>"""


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
                "  %s -> %s (cache_ttl: %ss, stale_ttl: %ss, fetch_interval: %ss, fetch_max_wait: %ss)",
                r.path, r.url, r.cache_ttl, r.stale_ttl, r.fetch_interval, r.fetch_max_wait,
            )
        yield
        await cache.close()

    app = FastAPI(lifespan=lifespan)

    _favicon = (Path(__file__).parent / "favicon.svg").read_bytes()

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(_favicon, media_type="image/svg+xml")

    @app.get("/stats", response_class=HTMLResponse, include_in_schema=False)
    async def stats_page():
        html = await _render_stats(config, cache)
        return HTMLResponse(html)

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
