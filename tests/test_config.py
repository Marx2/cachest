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

def test_fetch_interval_defaults(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text(YAML)
    cfg = load(f)
    assert cfg.routes[1].fetch_interval == 2.0
    assert cfg.routes[1].fetch_max_wait == 4.0


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
