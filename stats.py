import copy
from dataclasses import dataclass, field


@dataclass
class RouteStats:
    total: int = 0
    hits: int = 0
    misses: int = 0
    stale: int = 0
    errors: int = 0


_registry: dict[str, RouteStats] = {}


def get(path: str) -> RouteStats:
    if path not in _registry:
        _registry[path] = RouteStats()
    return _registry[path]


def record(path: str, x_cache: str) -> None:
    s = get(path)
    s.total += 1
    tag = x_cache.upper()
    if tag == "HIT":
        s.hits += 1
    elif tag == "MISS":
        s.misses += 1
    elif tag == "STALE":
        s.stale += 1
    elif tag == "ERROR":
        s.errors += 1


def all_routes() -> dict[str, RouteStats]:
    return {k: copy.copy(v) for k, v in _registry.items()}
