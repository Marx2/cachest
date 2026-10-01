"""Config loading and validation.

These tests exercise behaviour that can actually fail at runtime: a config that loads
but misbehaves (colliding keys, an unresolvable URL placeholder, an unreachable stale
window) is the failure mode worth guarding. The shipped config.yaml is additionally
covered by test_main.py::test_every_configured_route_registers_a_fastapi_route.
"""

import pytest
from pathlib import Path

from config import (
    DEFAULT_STALE_TTL,
    QUOTA_TTL_SECONDS,
    UNBOUNDED_QUEUE,
    Config,
    ConfigError,
    RouteConfig,
    load,
)
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


# --- queue depth (plan §63.9) ---------------------------------------------
#
# fetch_max_wait is a TOTAL queueing budget, so fetch_interval/fetch_max_wait
# silently set a concurrency cap. The historical 2/4 is depth 3, which starved
# every symbol past the third in a portfolio sweep behind an instant 503 that
# never reached the provider. These tests pin the arithmetic and the shipped
# per-route depths so that cannot regress unnoticed.


def test_queue_depth_is_floor_max_wait_over_interval_plus_one():
    assert RouteConfig("/a/{t}", "http://x/{t}", 60, fetch_interval=2.0, fetch_max_wait=4.0).queue_depth == 3
    assert RouteConfig("/a/{t}", "http://x/{t}", 60, fetch_interval=0.2, fetch_max_wait=120.0).queue_depth == 600
    assert RouteConfig("/a/{t}", "http://x/{t}", 60, fetch_interval=1.0, fetch_max_wait=120.0).queue_depth == 121
    # a remainder below one interval still buys exactly one more slot
    assert RouteConfig("/a/{t}", "http://x/{t}", 60, fetch_interval=3.0, fetch_max_wait=7.0).queue_depth == 3


def test_queue_depth_is_unbounded_without_pacing():
    assert RouteConfig("/a/{t}", "http://x/{t}", 60, fetch_interval=0.0).queue_depth == UNBOUNDED_QUEUE


#: Two depth bars, because the callers come in two sizes.
#:
#: `portfoliost-wallets`' snapshots-sync sweep asks for every held symbol of every
#: portfolio at once — 175+ distinct symbols in PROD — but only on the price-bar
#: routes. A page of the SPA fans out over one portfolio's positions plus the
#: portfolio cards, so ~80 is the worst realistic case there.
#:
#: The two routes below are deliberately serialized and exempt from both: one has
#: no path param at all (a singleton scraped once a day by the corpbondsync job)
#: and the other is per-company news on a 5-minute cadence, where a second
#: concurrent caller for the same key is a cache miss by definition.
SWEEP_ROUTES = frozenset({
    "/ohlcv/{ticker}",
    "/ohlcv/fund/{ticker}",
    "/fixedincome/ohlcv/{symbol}",
    "/crypto/ohlcv/{pair}",
})
MIN_SWEEP_DEPTH = 128
MIN_UI_DEPTH = 32
NARROW_FANOUT = frozenset({"/corp-bond/catalogue", "/news/company/{ticker}"})


def _too_shallow(cfg, only=None, exempt=frozenset(), floor=0):
    return [
        (r.name, r.path, r.queue_depth)
        for r in cfg.routes
        if (only is None or r.path in only)
        and r.path not in exempt
        and 0 <= r.queue_depth < floor
    ]


def test_real_config_queue_depth_absorbs_a_portfolio_sweep():
    """The price-bar routes carry the 175+ symbol snapshots-sync burst."""
    too_shallow = _too_shallow(load(REAL_CONFIG), only=SWEEP_ROUTES, floor=MIN_SWEEP_DEPTH)
    assert not too_shallow, _depth_msg(too_shallow, MIN_SWEEP_DEPTH)


def test_real_config_queue_depth_absorbs_a_ui_page():
    """Every other symbol-keyed route carries one page of the SPA (~80 rows)."""
    too_shallow = _too_shallow(load(REAL_CONFIG), exempt=NARROW_FANOUT, floor=MIN_UI_DEPTH)
    assert not too_shallow, _depth_msg(too_shallow, MIN_UI_DEPTH)


def _depth_msg(too_shallow, floor):
    return (
        "queue_depth = floor(fetch_max_wait / fetch_interval) + 1 is a concurrency cap; "
        f"these routes admit fewer than {floor} concurrent upstream fetches and 503 "
        "(with no upstream call at all) for every caller past that depth: "
        f"{too_shallow}"
    )


def test_real_config_deliberately_serialized_routes_are_named():
    """The NARROW_FANOUT exemption is a decision, not an oversight — pin both halves."""
    cfg = load(REAL_CONFIG)
    by_path = {r.path: r for r in cfg.routes}
    for path in NARROW_FANOUT:
        assert path in by_path, f"{path} no longer exists; re-check the fan-out exemption"
        assert by_path[path].queue_depth < MIN_UI_DEPTH, (
            f"{path} is exempted as a deliberate singleton but now has a sweep-sized depth "
            "— drop it from NARROW_FANOUT so it is held to the UI bar"
        )
    for path in SWEEP_ROUTES:
        assert path in by_path, f"{path} no longer exists; re-check SWEEP_ROUTES"


def test_real_config_paces_external_scrapes_rather_than_flooding():
    """openst legs that scrape an external site keep real spacing (plan §63.9.1)."""
    cfg = load(REAL_CONFIG)
    by_name = {r.name: r for r in cfg.routes}
    for name in ("OPENST_OHLCV_FUNDS", "OPENST_BOND_PROFILE", "OPENST_CORP_BOND_PROFILE"):
        assert by_name[name].fetch_interval >= 0.5, f"{name} proxies a scraper upstream"


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


# --- fund *category* NAV (plan §72.39 step 2, stage 4) ---------------------
#
# Distinct from OPENST_OHLCV_FUNDS: that one carries the fund's default category
# keyed on a .TFI symbol, this one carries the category the broker actually
# executes against, keyed on the provider's own code (ING01W). They must not
# share a key space, or one would serve the other's data — and the difference
# between the two is the whole ~12.7% class gap this work exists to close.

FUND_CATEGORY_PATH = "/fund/history/{code}"


def test_real_config_has_fund_category_history_route():
    cfg = load(REAL_CONFIG)
    by_name = {r.name: r for r in cfg.routes}
    route = by_name.get("OPENST_FUND_CATEGORY_HISTORY")
    assert route is not None, "the fund-category route is gone"
    assert route.path == FUND_CATEGORY_PATH
    assert route.url == (
        "http://openst:8080/fund/history/{code}?start={start}&end={end}"
    )
    assert route.query_params == ["start", "end"]


def test_fund_category_route_does_not_collide_with_the_default_category_route():
    """/ohlcv/fund/{ticker} serves category A; this serves the traded category.

    Same underlying data shape, different key space. A collision would let a
    request for ING01W return ING01's bars — silently, and with the right shape.
    """
    cfg = load(REAL_CONFIG)
    by_path = {r.path: r for r in cfg.routes}
    a = key_pattern(by_path["/ohlcv/fund/{ticker}"].path,
                    by_path["/ohlcv/fund/{ticker}"].query_params).pattern
    w = key_pattern(by_path[FUND_CATEGORY_PATH].path,
                    by_path[FUND_CATEGORY_PATH].query_params).pattern
    assert a != w


def test_fund_category_route_caches_for_a_business_day():
    """NAV moves once per valuation day, so 24h — matching OPENST_OHLCV_FUNDS.

    The upstream sends `cache-control: no-cache, private`, so it caches nothing
    on our behalf and this TTL is the only cache in the path.
    """
    cfg = load(REAL_CONFIG)
    by_name = {r.name: r for r in cfg.routes}
    route = by_name["OPENST_FUND_CATEGORY_HISTORY"]
    funds = by_name["OPENST_OHLCV_FUNDS"]
    assert route.cache_ttl == funds.cache_ttl == 86400
    assert route.stale_ttl == funds.stale_ttl


def test_fund_category_route_keeps_real_fetch_spacing():
    """Not exempted from pacing: it proxies an external site, one GET per miss.

    Cheaper than the biznesradar scrape behind OPENST_OHLCV_FUNDS (no pagination,
    ~0.3s per call) but still an external request, so it keeps spacing rather
    than adopting the 0.0 floor.
    """
    cfg = load(REAL_CONFIG)
    by_name = {r.name: r for r in cfg.routes}
    assert by_name["OPENST_FUND_CATEGORY_HISTORY"].fetch_interval >= 0.2


def test_fund_category_route_admits_a_ui_page_of_callers():
    cfg = load(REAL_CONFIG)
    by_name = {r.name: r for r in cfg.routes}
    assert by_name["OPENST_FUND_CATEGORY_HISTORY"].queue_depth >= MIN_UI_DEPTH


def test_fund_category_route_timeout_fits_a_single_json_get():
    """30 s, not the 120 s the biznesradar scrape needs — this is one request.

    Measured live at 0.18–0.34 s. The loose timeout would only delay the 404
    passthrough for an unknown code.
    """
    cfg = load(REAL_CONFIG)
    by_name = {r.name: r for r in cfg.routes}
    route = by_name["OPENST_FUND_CATEGORY_HISTORY"]
    assert route.fetch_timeout == 30
    assert route.fetch_timeout < by_name["OPENST_OHLCV_FUNDS"].fetch_timeout
