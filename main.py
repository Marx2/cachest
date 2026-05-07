import logging
from contextlib import asynccontextmanager
from typing import Any

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response

from cache import CacheMiss, RedisCache
from config import Config, RouteConfig, load
from fetcher import RateLimitedError, fetch

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


def make_handler(route: RouteConfig, cache: RedisCache):
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

        url = _build_url(route.url, path_params)
        try:
            value = await fetch(url, route.extract)
        except RateLimitedError:
            logger.warning("rate limited fetching %r", url)
            try:
                stale = await cache.get(key)
                return PlainTextResponse(
                    stale,
                    headers={"X-Cache": "STALE", "X-Cache-Stale-Reason": "rate-limited"},
                )
            except CacheMiss:
                pass
            return PlainTextResponse(
                "upstream rate limited and no cached value available",
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
            logger.info("  %s -> %s (TTL: %ss)", r.path, r.url, r.cache_ttl)
        yield
        await cache.close()

    app = FastAPI(lifespan=lifespan)

    _favicon = (Path(__file__).parent / "favicon.svg").read_bytes()

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(_favicon, media_type="image/svg+xml")

    for route in config.routes:
        app.add_api_route(
            route.path,
            make_handler(route, cache),
            methods=["GET"],
            response_class=PlainTextResponse,
        )

    return app


cfg = load(CONFIG_PATH)
app = create_app(cfg)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
