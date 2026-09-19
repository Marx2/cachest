import pytest
from pathlib import Path
from config import load

YAML = """
redis:
  host: localhost
  port: 6379
  password: ""
  db: 0
routes:
  - path: /test/{id}
    url: "http://example.com/{id}"
    cache_ttl: 60
    fetch_interval: 3.5
    fetch_max_wait: 7.0
    fetch_timeout: 120.0
  - path: /defaults/{id}
    url: "http://example.com/defaults/{id}"
    cache_ttl: 60
"""

def test_fetch_interval_parsed(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(YAML)
    cfg = load(f)
    assert cfg.routes[0].fetch_interval == 3.5
    assert cfg.routes[0].fetch_max_wait == 7.0
    assert cfg.routes[0].fetch_timeout == 120.0

def test_fetch_interval_defaults(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(YAML)
    cfg = load(f)
    assert cfg.routes[1].fetch_interval == 2.0
    assert cfg.routes[1].fetch_max_wait == 4.0
    assert cfg.routes[1].fetch_timeout == 15.0  # default


def test_stale_ttl_explicit(tmp_path):
    yaml = """
redis:
  host: localhost
  port: 6379
  password: ""
  db: 0
routes:
  - path: /t/{id}
    url: http://example.com/{id}
    cache_ttl: 60
    stale_ttl: 3600
"""
    f = tmp_path / "c.yaml"
    f.write_text(yaml)
    cfg = load(f)
    assert cfg.routes[0].stale_ttl == 3600


def test_stale_ttl_default(tmp_path):
    yaml = """
redis:
  host: localhost
  port: 6379
  password: ""
  db: 0
routes:
  - path: /t/{id}
    url: http://example.com/{id}
    cache_ttl: 60
"""
    f = tmp_path / "c.yaml"
    f.write_text(yaml)
    cfg = load(f)
    assert cfg.routes[0].stale_ttl == 2592000


QUERY_YAML = """
redis:
  host: localhost
routes:
  - path: /ohlcv/{ticker}
    url: "http://example.com/ohlcv/{ticker}?start={start}&end={end}"
    query_params: [start, end]
    cache_ttl: 60
"""

def test_query_params_parsed(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(QUERY_YAML)
    cfg = load(f)
    assert cfg.routes[0].query_params == ["start", "end"]

def test_query_params_default_empty(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(YAML)
    cfg = load(f)
    assert all(r.query_params == [] for r in cfg.routes)


# ---------------------------------------------------------------------------
# stock-news proposal N2 — real config.yaml news route
# ---------------------------------------------------------------------------


def test_real_config_has_company_news_route():
    cfg = load("config.yaml")
    news = next(r for r in cfg.routes if r.path == "/news/company/{ticker}")
    assert news.name == "OPENST_NEWS"
    assert news.url == \
        "http://openst:8080/news/company/{ticker}?start_date={start_date}&limit={limit}"
    assert news.query_params == ["start_date", "limit"]
    assert news.cache_ttl == 3600        # 1h fresh
    assert news.stale_ttl == 86400       # 24h stale fallback
    assert news.fetch_interval == 300    # 5min
    assert news.fetch_max_wait == 4.0


# ---------------------------------------------------------------------------
# D77 funds/bonds — real config.yaml OPENST_OHLCV_FUNDS route
# ---------------------------------------------------------------------------


def test_real_config_has_ohlcv_funds_route():
    cfg = load("config.yaml")
    fund = next(r for r in cfg.routes if r.path == "/ohlcv/fund/{ticker}")
    assert fund.name == "OPENST_OHLCV_FUNDS"
    assert fund.url == \
        "http://openst:8080/price/ohlcv/{ticker}?start={start}&end={end}"
    assert fund.query_params == ["start", "end"]
    assert fund.cache_ttl == 86400       # 24h — NAV updates once per business day
    assert fund.stale_ttl == 2592000
    assert fund.fetch_interval == 60     # 60s min between upstream fetches
    assert fund.fetch_max_wait == 4.0


# ---------------------------------------------------------------------------
# D78 crypto — real config.yaml OPENST_CRYPTO_OHLCV / OPENST_CRYPTO_QUOTE
# ---------------------------------------------------------------------------


def test_real_config_has_crypto_ohlcv_route():
    cfg = load("config.yaml")
    route = next(r for r in cfg.routes if r.path == "/crypto/ohlcv/{pair}")
    assert route.name == "OPENST_CRYPTO_OHLCV"
    assert route.url == \
        "http://openst:8080/crypto/ohlcv/{pair}?start={start}&end={end}"
    assert route.query_params == ["start", "end"]
    assert route.cache_ttl == 21600      # 6h — mirrors OPENST_OHLCV
    assert route.stale_ttl == 2592000


def test_real_config_has_crypto_quote_route():
    cfg = load("config.yaml")
    route = next(r for r in cfg.routes if r.path == "/crypto/quote/{pair}")
    assert route.name == "OPENST_CRYPTO_QUOTE"
    assert route.url == "http://openst:8080/crypto/quote/{pair}"
    assert route.cache_ttl == 21600      # 6h — daily prices only
    assert route.stale_ttl == 2592000


def test_real_config_has_crypto_search_route():
    cfg = load("config.yaml")
    route = next(r for r in cfg.routes if r.path == "/crypto/search/{query}")
    assert route.name == "OPENST_CRYPTO_SEARCH"
    assert route.url == "http://openst:8080/crypto/search/{query}"
    assert route.cache_ttl == 604800      # 7d — universe changes rarely
    assert route.stale_ttl == 2592000


def test_real_config_has_crypto_profile_route():
    cfg = load("config.yaml")
    route = next(r for r in cfg.routes if r.path == "/crypto/profile/{pair}")
    assert route.name == "OPENST_CRYPTO_PROFILE"
    assert route.url == "http://openst:8080/crypto/profile/{pair}"
    assert route.cache_ttl == 21600       # 6h — matches OPENST_CRYPTO_QUOTE
    assert route.stale_ttl == 2592000


# ---------------------------------------------------------------------------
# D79 retail savings bonds — real config.yaml fixed-income routes
# ---------------------------------------------------------------------------


def test_real_config_has_bond_ohlcv_route():
    cfg = load("config.yaml")
    route = next(r for r in cfg.routes if r.path == "/fixedincome/ohlcv/{symbol}")
    assert route.name == "OPENST_BOND_OHLCV"
    assert route.url == \
        "http://openst:8080/fixedincome/ohlcv/{symbol}?start={start}&end={end}"
    assert route.query_params == ["start", "end"]
    assert route.cache_ttl == 21600       # 6h — computed daily prices
    assert route.stale_ttl == 2592000


def test_real_config_has_bond_quote_route():
    cfg = load("config.yaml")
    route = next(r for r in cfg.routes if r.path == "/fixedincome/quote/{symbol}")
    assert route.name == "OPENST_BOND_QUOTE"
    assert route.url == "http://openst:8080/fixedincome/quote/{symbol}"
    assert route.cache_ttl == 21600       # 6h — mirrors OPENST_BOND_OHLCV
    assert route.stale_ttl == 2592000
    assert route.fetch_interval == 2


def test_real_config_has_bond_profile_route():
    cfg = load("config.yaml")
    route = next(r for r in cfg.routes if r.path == "/fixedincome/profile/{symbol}")
    assert route.name == "OPENST_BOND_PROFILE"
    assert route.url == "http://openst:8080/fixedincome/profile/{symbol}"
    assert route.cache_ttl == 86400       # 24h — static bond metadata
    assert route.stale_ttl == 2592000
    assert route.fetch_interval == 60


def test_real_config_has_bond_search_route():
    cfg = load("config.yaml")
    route = next(r for r in cfg.routes if r.path == "/fixedincome/search/{query}")
    assert route.name == "OPENST_BOND_SEARCH"
    assert route.url == "http://openst:8080/fixedincome/search/{query}"
    assert route.cache_ttl == 3600        # 1h — catalogue moves daily
    assert route.stale_ttl == 2592000
    assert route.fetch_interval == 2


def test_real_config_has_corp_bond_profile_route():
    cfg = load("config.yaml")
    route = next(r for r in cfg.routes if r.path == "/corp-bond/profile/{symbol}")
    assert route.name == "OPENST_CORP_BOND_PROFILE"
    assert route.url == "http://openst:8080/corp-bond/profile/{symbol}"
    assert route.cache_ttl == 86400       # 24h — static bond metadata
    assert route.stale_ttl == 2592000
    assert route.fetch_interval == 60


def test_real_config_has_corp_bond_catalogue_route():
    cfg = load("config.yaml")
    route = next(r for r in cfg.routes if r.path == "/corp-bond/catalogue")
    assert route.name == "OPENST_CORP_BOND_CATALOGUE"
    assert route.url == "http://openst:8080/corp-bond/catalogue"
    assert route.cache_ttl == 43200       # 12h — half the openst 24h TTL
    assert route.stale_ttl == 2592000
    assert route.fetch_interval == 60
