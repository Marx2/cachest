"""Config loading and validation.

These tests exercise behaviour that can actually fail at runtime: a config that loads
but misbehaves (colliding keys, an unresolvable URL placeholder, an unreachable stale
window) is the failure mode worth guarding. The shipped config.yaml is additionally
covered by test_main.py::test_every_configured_route_registers_a_fastapi_route.
"""

import pytest
from pathlib import Path

from config import DEFAULT_STALE_TTL, QUOTA_TTL_SECONDS, Config, ConfigError, load
from keys import key_pattern

REAL_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"

MINIMAL = """
redis:
  host: localhost
routes:
  - name: TEST
    path: /test/{id}
    url: "http://example.com/{id}"
    cache_ttl: 60
"""


def _write(tmp_path, yaml_text, name="config.yaml"):
    f = tmp_path / name
    f.write_text(yaml_text)
    return f


# --- parsing ---------------------------------------------------------------


def test_loads_defaults(tmp_path):
    cfg = load(_write(tmp_path, MINIMAL))
    route = cfg.routes[0]
    assert route.cache_ttl == 60
    assert route.fetch_interval == 2.0
    assert route.fetch_max_wait == 4.0
    assert route.fetch_timeout == 15.0
    assert route.stale_ttl == DEFAULT_STALE_TTL
    assert route.daily_limit == 0
    assert route.query_params == []


def test_parses_overrides(tmp_path):
    yaml_text = """
routes:
  - name: TEST
    path: /t/{id}
    url: "http://example.com/{id}"
    cache_ttl: 60
    stale_ttl: 3600
    daily_limit: 25
    json_field: DividendYield
    fetch_interval: 3.5
    fetch_max_wait: 7.0
    fetch_timeout: 120.0
    query_params: [start, end]
"""
    route = load(_write(tmp_path, yaml_text)).routes[0]
    assert route.stale_ttl == 3600
    assert route.daily_limit == 25
    assert route.json_field == "DividendYield"
    assert route.fetch_interval == 3.5
    assert route.fetch_max_wait == 7.0
    assert route.fetch_timeout == 120.0
    assert route.query_params == ["start", "end"]


def test_redis_host_prefers_env(tmp_path, monkeypatch):
    monkeypatch.setenv("REDIS_HOST", "from-env")
    assert load(_write(tmp_path, MINIMAL)).redis.host == "from-env"


def test_redis_host_falls_back_to_file(tmp_path, monkeypatch):
    monkeypatch.delenv("REDIS_HOST", raising=False)
    assert load(_write(tmp_path, MINIMAL)).redis.host == "localhost"


def test_redis_password_reads_env(tmp_path, monkeypatch):
    """REDIS_HOST had an env override but REDIS_PASSWORD did not — they now agree."""
    monkeypatch.setenv("REDIS_PASSWORD", "s3cret")
    assert load(_write(tmp_path, MINIMAL)).redis.password == "s3cret"


def test_api_key_resolved_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("API_TEST", "key-123")
    assert load(_write(tmp_path, MINIMAL)).routes[0].api_key == "key-123"


# --- validation ------------------------------------------------------------


def test_missing_required_key_names_the_route(tmp_path):
    yaml_text = """
routes:
  - name: BROKEN
    path: /t/{id}
    url: "http://example.com"
"""
    with pytest.raises(ConfigError, match="BROKEN.*cache_ttl"):
        load(_write(tmp_path, yaml_text))


def test_duplicate_path_rejected(tmp_path):
    """Two routes with one path would share cache keys and serve each other's data."""
    yaml_text = """
routes:
  - name: A
    path: /t/{id}
    url: "http://example.com/{id}"
    cache_ttl: 60
  - name: B
    path: /t/{id}
    url: "http://other.com/{id}"
    cache_ttl: 60
"""
    with pytest.raises(ConfigError, match="duplicate path"):
        load(_write(tmp_path, yaml_text))


def test_url_placeholder_not_backed_by_any_param_rejected(tmp_path):
    """An unresolvable placeholder used to be sent to the upstream literally."""
    yaml_text = """
routes:
  - name: T
    path: /t/{id}
    url: "http://example.com/{id}?start={start}"
    cache_ttl: 60
    query_params: [end]
"""
    with pytest.raises(ConfigError, match=r"\{start\}"):
        load(_write(tmp_path, yaml_text))


def test_api_key_placeholder_always_allowed(tmp_path):
    yaml_text = """
routes:
  - name: T
    path: /t/{id}
    url: "http://example.com/{id}?apikey={api_key}"
    cache_ttl: 60
"""
    assert load(_write(tmp_path, yaml_text)).routes[0].api_key == ""


def test_query_param_placeholder_is_accepted(tmp_path):
    yaml_text = """
routes:
  - name: T
    path: /t/{id}
    url: "http://example.com/{id}?start={start}"
    cache_ttl: 60
    query_params: [start]
"""
    assert load(_write(tmp_path, yaml_text)).routes[0].query_params == ["start"]


def test_stale_ttl_shorter_than_cache_ttl_rejected(tmp_path):
    """Otherwise every value is stale the instant it is written and the fallback is dead."""
    yaml_text = """
routes:
  - name: T
    path: /t/{id}
    url: "http://example.com/{id}"
    cache_ttl: 86400
    stale_ttl: 60
"""
    with pytest.raises(ConfigError, match="stale_ttl"):
        load(_write(tmp_path, yaml_text))


def test_daily_limit_without_name_rejected(tmp_path):
    """Quota keys are "limit:{name}:{date}" — no name means the limit is ignored."""
    yaml_text = """
routes:
  - path: /t/{id}
    url: "http://example.com/{id}"
    cache_ttl: 60
    daily_limit: 25
"""
    with pytest.raises(ConfigError, match="no name"):
        load(_write(tmp_path, yaml_text))


@pytest.mark.parametrize("field,value", [
    ("cache_ttl", 0),
    ("fetch_interval", -1),
    ("fetch_max_wait", -1),
    ("fetch_timeout", 0),
    ("daily_limit", -5),
])
def test_negative_and_zero_values_rejected(tmp_path, field, value):
    yaml_text = f"""
routes:
  - name: T
    path: /t/{{id}}
    url: "http://example.com/{{id}}"
    cache_ttl: 60
    {field}: {value}
"""
    with pytest.raises(ConfigError, match=field):
        load(_write(tmp_path, yaml_text))


def test_json_field_and_extract_selector_are_mutually_exclusive(tmp_path):
    yaml_text = """
routes:
  - name: T
    path: /t/{id}
    url: "http://example.com/{id}"
    cache_ttl: 60
    json_field: DividendYield
    extract:
      selector: "dl .row"
      label: Yield
      field: dd
"""
    with pytest.raises(ConfigError, match="only one"):
        load(_write(tmp_path, yaml_text))


def test_extract_selector_needs_label_and_field(tmp_path):
    yaml_text = """
routes:
  - name: T
    path: /t/{id}
    url: "http://example.com/{id}"
    cache_ttl: 60
    extract:
      selector: "dl .row"
"""
    with pytest.raises(ConfigError, match="extract.label"):
        load(_write(tmp_path, yaml_text))


# --- the shipped config ----------------------------------------------------


def test_real_config_loads():
    """The validation above runs against the real file on every test session."""
    cfg = load(REAL_CONFIG)
    assert len(cfg.routes) > 0


def test_real_config_has_no_two_routes_sharing_a_key_space():
    cfg = load(REAL_CONFIG)
    patterns = [key_pattern(r.path, r.query_params).pattern for r in cfg.routes]
    assert len(patterns) == len(set(patterns)), (
        "two routes would claim the same cache keys and serve each other's data"
    )


def test_real_config_quota_ttl_outlives_a_utc_day():
    """The counter for "today" must not expire before the day it counts is over."""
    assert QUOTA_TTL_SECONDS > 86400


def test_redis_port_and_db_are_file_only(tmp_path, monkeypatch):
    """Documents the asymmetry on purpose: REDIS_PORT/REDIS_DB were declared as env vars
    in the cluster HelmRelease but never read, so they were a second source of truth
    that silently did nothing. Only host and password have an env override.
    """
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_DB", "7")
    redis = load(_write(tmp_path, MINIMAL)).redis
    assert redis.port == 6379
    assert redis.db == 0
