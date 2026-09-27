import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from keys import path_params_of

# Placeholders in a URL template, including the reserved {api_key}.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Longer than the longest realistic UTC day plus slack, so the counter for "today"
# cannot expire before the day it counts is over.
QUOTA_TTL_SECONDS = 90_000

DEFAULT_STALE_TTL = 2592000  # 30 days


class ConfigError(Exception):
    """Raised for a config.yaml that would misbehave at runtime."""


@dataclass
class ExtractConfig:
    selector: str = ""
    label: str = ""
    field: str = ""


@dataclass
class RouteConfig:
    path: str
    url: str
    cache_ttl: int
    name: str = ""
    api_key: str = ""
    daily_limit: int = 0
    json_field: str = ""
    extract: ExtractConfig = field(default_factory=ExtractConfig)
    fetch_interval: float = 2.0
    fetch_max_wait: float = 4.0
    fetch_timeout: float = 15.0
    stale_ttl: int = DEFAULT_STALE_TTL
    query_params: list[str] = field(default_factory=list)


@dataclass
class RedisConfig:
    host: str = "localhost"
    port: int = 6379
    password: str = ""
    db: int = 0


@dataclass
class Config:
    redis: RedisConfig
    routes: list[RouteConfig]


def _validate(route: RouteConfig, seen_paths: set[str]) -> None:
    where = f"route {route.name or route.path!r} ({route.path})"

    if route.path in seen_paths:
        raise ConfigError(f"{where}: duplicate path — cache keys would collide")
    seen_paths.add(route.path)

    if route.cache_ttl <= 0:
        raise ConfigError(f"{where}: cache_ttl must be > 0, got {route.cache_ttl}")
    if route.stale_ttl < route.cache_ttl:
        raise ConfigError(
            f"{where}: stale_ttl ({route.stale_ttl}) is shorter than cache_ttl "
            f"({route.cache_ttl}) — stale fallback would never be reachable"
        )
    if route.fetch_interval < 0:
        raise ConfigError(f"{where}: fetch_interval must be >= 0")
    if route.fetch_max_wait < 0:
        raise ConfigError(f"{where}: fetch_max_wait must be >= 0")
    if route.fetch_timeout <= 0:
        raise ConfigError(f"{where}: fetch_timeout must be > 0")
    if route.daily_limit < 0:
        raise ConfigError(f"{where}: daily_limit must be >= 0, got {route.daily_limit}")
    if route.daily_limit > 0 and not route.name:
        # Quota counters are keyed "limit:{name}:{date}" — without a name there is
        # nothing to key on and the limit would be silently ignored.
        raise ConfigError(f"{where}: daily_limit is set but the route has no name")

    available = set(path_params_of(route.path)) | set(route.query_params) | {"api_key"}
    missing = sorted(set(_PLACEHOLDER.findall(route.url)) - available)
    if missing:
        raise ConfigError(
            f"{where}: url placeholder(s) {', '.join('{' + m + '}' for m in missing)} "
            f"are neither a path param, a declared query_param, nor {{api_key}} — "
            f"they would be sent to the upstream literally"
        )

    # fetcher() picks one extraction strategy: json_field, else HTML selector, else
    # passthrough. Two of them set at once silently means the first one wins.
    if route.json_field and route.extract.selector:
        raise ConfigError(
            f"{where}: json_field and extract.selector are set; fetcher uses only one"
        )
    if route.extract.selector and not (route.extract.label and route.extract.field):
        raise ConfigError(
            f"{where}: extract.selector needs both extract.label and extract.field"
        )


def load(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text()) or {}

    redis_raw = raw.get("redis") or {}
    # host and password can be overridden from the environment; port and db are
    # file-only. The cluster sets all four in the mounted configmap and used to also
    # declare REDIS_PORT/REDIS_DB as env vars, which were silently ignored — hence the
    # explicit asymmetry rather than an env var that looks supported but is not.
    redis_cfg = RedisConfig(
        host=os.environ.get("REDIS_HOST") or redis_raw.get("host", "localhost"),
        port=int(redis_raw.get("port", 6379)),
        # {api_key}/password never reach a log line, the stats page, or a cache key.
        password=os.environ.get("REDIS_PASSWORD") or redis_raw.get("password", "") or "",
        db=int(redis_raw.get("db", 0)),
    )

    routes: list[RouteConfig] = []
    seen_paths: set[str] = set()
    for r in raw.get("routes") or []:
        ext_raw = r.get("extract") or {}
        extract = ExtractConfig(
            selector=ext_raw.get("selector", ""),
            label=ext_raw.get("label", ""),
            field=ext_raw.get("field", ""),
        )
        name = r.get("name", "")
        missing_required = [k for k in ("path", "url", "cache_ttl") if k not in r]
        if missing_required:
            raise ConfigError(
                f"route {name or r.get('path', '<unnamed>')!r} is missing required "
                f"key(s): {', '.join(missing_required)}"
            )
        route = RouteConfig(
            path=r["path"],
            url=r["url"],
            cache_ttl=int(r["cache_ttl"]),
            name=name,
            # {api_key} is resolved from the environment at load time, so the key
            # itself never reaches a log line, the stats page, or a cache key.
            api_key=os.environ.get(f"API_{name}", "") if name else "",
            daily_limit=int(r.get("daily_limit", 0)),
            json_field=r.get("json_field", ""),
            extract=extract,
            fetch_interval=float(r.get("fetch_interval", 2.0)),
            fetch_max_wait=float(r.get("fetch_max_wait", 4.0)),
            fetch_timeout=float(r.get("fetch_timeout", 15.0)),
            stale_ttl=int(r.get("stale_ttl", DEFAULT_STALE_TTL)),
            query_params=list(r.get("query_params") or []),
        )
        _validate(route, seen_paths)
        routes.append(route)

    return Config(redis=redis_cfg, routes=routes)
