# Graph Report - cachest  (2026-09-15)

## Corpus Check
- 17 files · ~10,665 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 296 nodes · 419 edges · 17 communities (14 shown, 3 thin omitted)
- Extraction: 80% EXTRACTED · 20% INFERRED · 0% AMBIGUOUS · INFERRED: 84 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `2cd4c38e`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_App Core & Routing|App Core & Routing]]
- [[_COMMUNITY_Fetcher & Config Loading|Fetcher & Config Loading]]
- [[_COMMUNITY_Stats Tests|Stats Tests]]
- [[_COMMUNITY_AST Semantic Overlap|AST Semantic Overlap]]
- [[_COMMUNITY_Cache Layer & Request Flow|Cache Layer & Request Flow]]
- [[_COMMUNITY_Rate Limiter|Rate Limiter]]
- [[_COMMUNITY_Cache Module|Cache Module]]
- [[_COMMUNITY_Stats & Lifespan|Stats & Lifespan]]
- [[_COMMUNITY_Cache Tests|Cache Tests]]
- [[_COMMUNITY_Stats Module|Stats Module]]
- [[_COMMUNITY_Assets|Assets]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]

## God Nodes (most connected - your core abstractions)
1. `create_app()` - 30 edges
2. `_make_config()` - 26 edges
3. `load()` - 17 edges
4. `cachest — HTTP Caching Proxy` - 13 edges
5. `UpstreamError` - 11 edges
6. `Task 5: Build Docker image and test locally` - 11 edges
7. `ExtractConfig` - 10 edges
8. `fetch()` - 10 edges
9. `handler (inner)` - 10 edges
10. `RateLimiter` - 9 edges

## Surprising Connections (you probably didn't know these)
- `cachest README` --references--> `RouteConfig`  [INFERRED]
  readme.md → config.py
- `RateLimiter.acquire` --conceptually_related_to--> `Stale Cache Fallback Pattern`  [INFERRED]
  rate_limiter.py → docs/superpowers/specs/2026-05-10-per-route-rate-limiter-design.md
- `Stale Cache Fallback Pattern` --rationale_for--> `CacheStale`  [INFERRED]
  docs/superpowers/specs/2026-05-10-per-route-rate-limiter-design.md → cache.py
- `Stale Cache Fallback Pattern` --rationale_for--> `handler (inner)`  [INFERRED]
  docs/superpowers/specs/2026-05-10-per-route-rate-limiter-design.md → main.py
- `cachest README` --references--> `create_app`  [INFERRED]
  readme.md → main.py

## Hyperedges (group relationships)
- **Per-Request Cache/Rate-Limit/Fetch Flow** — main_handler, cache_rediscache_get, rate_limiter_ratelimiter_acquire, fetcher_fetch, cache_rediscache_set, main__respond [EXTRACTED 1.00]
- **Stale Fallback Triggers (rate-limit or upstream error)** — rate_limiter_ratelimiter_acquire, fetcher_upstreamerror, cache_cachestale, main_handler [EXTRACTED 1.00]
- **Stats In-Process + Redis Persistence Flow** — stats_record, stats__persist, stats_load_from_redis, stats_routestats [EXTRACTED 1.00]

## Communities (17 total, 3 thin omitted)

### Community 0 - "App Core & Routing"
Cohesion: 0.07
Nodes (52): create_app(), _make_config(), _news_config(), _query_config(), When acquire() returns False and no stale exists, return 503., When acquire() returns False and no stale exists, return 503., On UpstreamError, serve stale from cache., On UpstreamError, serve stale from cache. (+44 more)

### Community 1 - "Fetcher & Config Loading"
Cohesion: 0.05
Nodes (38): code:python (import pytest), code:python (import asyncio), code:bash (pytest tests/test_rate_limiter.py -v), code:bash (git add rate_limiter.py tests/test_rate_limiter.py), code:python (import pytest), code:bash (pip install respx --quiet), code:python (import httpx), code:bash (pytest tests/test_fetcher.py -v) (+30 more)

### Community 2 - "Stats Tests"
Cohesion: 0.08
Nodes (24): API Keys, cachest — HTTP Caching Proxy, code:block1 (docker compose up --build), code:sh (docker compose exec redis redis-cli GET "dyhistory:AAPL"), code:sh (docker compose down), code:yaml (redis:), code:block3 (API_ALPHAVANTAGE=your_alphavantage_key_here), code:sh (docker compose exec redis redis-cli GET "limit:FMP:2026-05-1) (+16 more)

### Community 3 - "AST Semantic Overlap"
Cohesion: 0.1
Nodes (25): CacheMiss, CacheStale, RedisCache.close, RedisCache.get, RedisCache.scan_prefix, RedisCache.set, _build_url, _cache_key (+17 more)

### Community 4 - "Cache Layer & Request Flow"
Cohesion: 0.14
Nodes (11): CacheMiss, CacheStale, Return raw stored values for all keys matching prefix:*, Return [(key, raw_value)] for all keys matching prefix:*, RedisCache, Exception, mock_cache(), On UpstreamError with no stale, return 503. (+3 more)

### Community 5 - "Rate Limiter"
Cohesion: 0.2
Nodes (16): Config, load(), RedisConfig, RouteConfig, test_fetch_interval_defaults(), test_fetch_interval_parsed(), test_query_params_default_empty(), test_query_params_parsed() (+8 more)

### Community 7 - "Stats & Lifespan"
Cohesion: 0.24
Nodes (14): ExtractConfig, _extract_from_html(), fetch(), RateLimitedError, UpstreamError, fetch() passes the timeout arg to httpx.AsyncClient., Default timeout is 15s (no regression)., test_fetch_custom_timeout_is_used() (+6 more)

### Community 8 - "Cache Tests"
Cohesion: 0.23
Nodes (16): RedisCache, Config, ExtractConfig, load, RedisConfig, RouteConfig, _extract_from_html, fetch (+8 more)

### Community 9 - "Stats Module"
Cohesion: 0.19
Nodes (10): RateLimiter, Second call within interval should sleep and return True if sleep <= max_wait., If required sleep > max_wait, acquire returns False immediately., After enough time passes, acquire returns True without sleeping., Two concurrent callers should both eventually return True, spaced by the interva, test_acquire_returns_false_when_wait_exceeds_max(), test_acquire_true_after_interval_has_passed(), test_concurrent_callers_get_distinct_slots() (+2 more)

### Community 10 - "Assets"
Cohesion: 0.17
Nodes (9): _build_url(), _cache_key(), make_handler(), /dy/{ticker} + {"ticker": "AAPL"} → "dy:AAPL", /dy/{ticker} + {"ticker": "AAPL"} → "dy:AAPL"; /calendar/earnings → "calendar:ea, /dy/{ticker} + {"ticker": "AAPL"} → "dy:AAPL"; /calendar/earnings → "calendar:ea, test_build_url_substitutes_query_values(), test_cache_key_no_path_params_routes_dont_collide() (+1 more)

### Community 12 - "Community 12"
Cohesion: 0.18
Nodes (10): Changes to `fetcher.py`, Changes to `main.py`, code:yaml (routes:), code:python (class RateLimiter:), code:block3 (cache HIT  →  return HIT (unchanged)), Config Changes, Files Touched, Goal (+2 more)

### Community 13 - "Community 13"
Cohesion: 0.31
Nodes (7): _delete_all_stats(), get(), load_from_redis(), _persist(), record(), reset_all(), RouteStats

### Community 14 - "Community 14"
Cohesion: 0.67
Nodes (3): _ensure_otel(), One MeterProvider per process, shared by every app instance.      create_app() m, setup_otel()

## Knowledge Gaps
- **103 isolated node(s):** `Return raw stored values for all keys matching prefix:*`, `Return [(key, raw_value)] for all keys matching prefix:*`, `/dy/{ticker} + {"ticker": "AAPL"} → "dy:AAPL"; /calendar/earnings → "calendar:ea`, `One MeterProvider per process, shared by every app instance.      create_app() m`, `Second call within interval should sleep and return True if sleep <= max_wait.` (+98 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `create_app()` connect `App Core & Routing` to `Stats Module`, `Assets`, `Cache Layer & Request Flow`, `Community 14`?**
  _High betweenness centrality (0.145) - this node is a cross-community bridge._
- **Why does `RedisCache` connect `Cache Layer & Request Flow` to `App Core & Routing`, `Cache Module`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Why does `_make_config()` connect `App Core & Routing` to `Cache Layer & Request Flow`, `Rate Limiter`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Are the 28 inferred relationships involving `create_app()` (e.g. with `RedisCache` and `setup_otel()`) actually correct?**
  _`create_app()` has 28 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `_make_config()` (e.g. with `RouteConfig` and `Config`) actually correct?**
  _`_make_config()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `load()` (e.g. with `test_fetch_interval_parsed()` and `test_fetch_interval_defaults()`) actually correct?**
  _`load()` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `UpstreamError` (e.g. with `ExtractConfig` and `test_upstream_error_returns_stale()`) actually correct?**
  _`UpstreamError` has 6 INFERRED edges - model-reasoned connections that need verification._