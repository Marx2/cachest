import asyncio
import copy
from dataclasses import dataclass, field

from redis.asyncio import Redis


@dataclass
class RouteStats:
    total: int = 0
    hits: int = 0
    misses: int = 0
    stale: int = 0
    errors: int = 0


_registry: dict[str, RouteStats] = {}
_redis: Redis | None = None


def init(client: Redis) -> None:
    global _redis
    _redis = client


def get(path: str) -> RouteStats:
    if path not in _registry:
        _registry[path] = RouteStats()
    return _registry[path]


def record(path: str, x_cache: str) -> None:
    s = get(path)
    s.total += 1
    tag = x_cache.upper()
    field: str | None = None
    if tag == "HIT":
        s.hits += 1
        field = "hits"
    elif tag == "MISS":
        s.misses += 1
        field = "misses"
    elif tag == "STALE":
        s.stale += 1
        field = "stale"
    elif tag == "ERROR":
        s.errors += 1
        field = "errors"

    if _redis is not None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_persist(path, field))
        except RuntimeError:
            pass


def all_routes() -> dict[str, RouteStats]:
    return {k: copy.copy(v) for k, v in _registry.items()}


async def load_from_redis(client: Redis) -> None:
    try:
        async for key in client.scan_iter("stats:*"):
            path = key.decode() if isinstance(key, bytes) else key
            path = path[len("stats:"):]
            data = await client.hgetall(f"stats:{path}")
            if not data:
                continue
            s = get(path)
            s.total = int(data.get(b"total", data.get("total", 0)))
            s.hits = int(data.get(b"hits", data.get("hits", 0)))
            s.misses = int(data.get(b"misses", data.get("misses", 0)))
            s.stale = int(data.get(b"stale", data.get("stale", 0)))
            s.errors = int(data.get(b"errors", data.get("errors", 0)))
    except Exception:
        pass


async def _persist(path: str, field: str | None) -> None:
    try:
        key = f"stats:{path}"
        pipe = _redis.pipeline(transaction=False)
        pipe.hincrby(key, "total", 1)
        if field is not None:
            pipe.hincrby(key, field, 1)
        await pipe.execute()
    except Exception:
        pass
