import os
from dataclasses import dataclass, field
from pathlib import Path
import yaml


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
    stale_ttl: int = 2592000
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


def load(path: str | Path) -> Config:
    data = Path(path).read_text()
    raw = yaml.safe_load(data)

    redis_raw = raw.get("redis", {})
    redis_cfg = RedisConfig(
        host=os.environ.get("REDIS_HOST") or redis_raw.get("host", "localhost"),
        port=redis_raw.get("port", 6379),
        password=redis_raw.get("password", "") or "",
        db=redis_raw.get("db", 0),
    )

    routes = []
    for r in raw.get("routes", []):
        ext_raw = r.get("extract") or {}
        extract = ExtractConfig(
            selector=ext_raw.get("selector", ""),
            label=ext_raw.get("label", ""),
            field=ext_raw.get("field", ""),
        )
        name = r.get("name", "")
        api_key = os.environ.get(f"API_{name}", "") if name else ""
        routes.append(RouteConfig(
            path=r["path"],
            url=r["url"],
            cache_ttl=int(r["cache_ttl"]),
            name=name,
            api_key=api_key,
            daily_limit=int(r.get("daily_limit", 0)),
            json_field=r.get("json_field", ""),
            extract=extract,
            fetch_interval=float(r.get("fetch_interval", 2.0)),
            fetch_max_wait=float(r.get("fetch_max_wait", 4.0)),
            stale_ttl=int(r.get("stale_ttl", 2592000)),
            query_params=list(r.get("query_params", [])),
        ))

    return Config(redis=redis_cfg, routes=routes)
