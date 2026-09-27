import asyncio
import copy
import logging
from dataclasses import dataclass

logger = logging.getLogger("cachest.stats")

FIELDS = ("total", "hits", "misses", "stale", "errors")


@dataclass
class RouteStats:
    total: int = 0
    hits: int = 0
    misses: int = 0
    stale: int = 0
    errors: int = 0


# Counters live in-process for the dashboard and are mirrored to Redis so they survive
# a restart. Both are best-effort: a Redis outage degrades the dashboard's durability,
# never the request path.
_registry: dict[str, RouteStats] = {}
_cache = None
_tasks: set[asyncio.Task] = set()


def init(cache) -> None:
    global _cache
    _cache = cache


def get(path: str) -> RouteStats:
    if path not in _registry:
        _registry[path] = RouteStats()
    return _registry[path]


def _field_for(x_cache: str) -> str | None:
    return {
        "HIT": "hits",
        "MISS": "misses",
        "STALE": "stale",
        "ERROR": "errors",
    }.get(x_cache.upper())


def record(path: str, x_cache: str) -> None:
    s = get(path)
    s.total += 1
    field = _field_for(x_cache)
    if field is not None:
        setattr(s, field, getattr(s, field) + 1)

    if _cache is not None:
        _schedule(_persist(path, field))


def _schedule(coro) -> None:
    """Run a write in the background without losing the task.

    The task is held in a module-level set until it finishes, so a reference cycle
    from the event loop cannot garbage-collect it mid-flight, and shutdown can drain
    what is outstanding.
    """
    try:
        task = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        # No event loop (startup, or a plain synchronous call from a test).
        coro.close()
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def drain() -> None:
    """Wait for outstanding counter writes. Called from lifespan shutdown."""
    if _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


def all_routes() -> dict[str, RouteStats]:
    return {k: copy.copy(v) for k, v in _registry.items()}


def reset_all(cache) -> None:
    _registry.clear()
    if cache is not None:
        _schedule(_delete_all_stats(cache))


async def _delete_all_stats(cache) -> None:
    try:
        await cache.delete_pattern("stats:*")
    except Exception as e:
        logger.warning("could not clear persisted stats: %s", e)


async def load_from_redis(cache) -> None:
    try:
        keys = await cache.scan_keys("stats:*")
    except Exception as e:
        # Counters start at zero for this process; the dashboard stays correct, it just
        # forgets history. Worth a log line so the reset is not silent.
        logger.warning("could not load stats from redis (starting from zero): %s", e)
        return

    for key in keys:
        data = await cache.hgetall(key)
        if not data:
            continue
        s = get(key[len("stats:"):])
        for name in FIELDS:
            setattr(s, name, int(data.get(name, 0) or 0))


async def _persist(path: str, field: str | None) -> None:
    increments = {"total": 1}
    if field is not None:
        increments[field] = 1
    try:
        await _cache.hincrby_fields(f"stats:{path}", increments)
    except Exception as e:
        logger.debug("stats persist for %s failed: %s", path, e)
