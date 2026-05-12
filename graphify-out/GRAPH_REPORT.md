# Graph Report - .  (2026-05-12)

## Corpus Check
- Corpus is ~6,763 words - fits in a single context window. You may not need a graph.

## Summary
- 153 nodes · 226 edges · 11 communities (9 shown, 2 thin omitted)
- Extraction: 78% EXTRACTED · 22% INFERRED · 0% AMBIGUOUS · INFERRED: 49 edges (avg confidence: 0.8)
- Token cost: 9,800 input · 3,100 output

## Community Hubs (Navigation)
- [[_COMMUNITY_App Core & Routing|App Core & Routing]]
- [[_COMMUNITY_Fetcher & Config Loading|Fetcher & Config Loading]]
- [[_COMMUNITY_Stats Tests|Stats Tests]]
- [[_COMMUNITY_AST Semantic Overlap|AST Semantic Overlap]]
- [[_COMMUNITY_Cache Layer & Request Flow|Cache Layer & Request Flow]]
- [[_COMMUNITY_Rate Limiter|Rate Limiter]]
- [[_COMMUNITY_Cache Module|Cache Module]]
- [[_COMMUNITY_Stats & Lifespan|Stats & Lifespan]]
- [[_COMMUNITY_Stats Module|Stats Module]]
- [[_COMMUNITY_Assets|Assets]]

## God Nodes (most connected - your core abstractions)
1. `create_app()` - 14 edges
2. `_make_config()` - 14 edges
3. `handler (inner)` - 10 edges
4. `load()` - 9 edges
5. `RateLimiter` - 9 edges
6. `UpstreamError` - 9 edges
7. `ExtractConfig` - 8 edges
8. `RedisCache` - 7 edges
9. `fetch()` - 7 edges
10. `CacheMiss` - 6 edges

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

## Communities (11 total, 2 thin omitted)

### Community 0 - "App Core & Routing"
Cohesion: 0.1
Nodes (26): Config, RedisConfig, RouteConfig, _cache_key(), create_app(), make_handler(), /dy/{ticker} + {"ticker": "AAPL"} → "dy:AAPL", _make_config() (+18 more)

### Community 1 - "Fetcher & Config Loading"
Cohesion: 0.2
Nodes (14): ExtractConfig, load(), _extract_from_html(), fetch(), RateLimitedError, UpstreamError, test_fetch_interval_defaults(), test_fetch_interval_parsed() (+6 more)

### Community 3 - "AST Semantic Overlap"
Cohesion: 0.23
Nodes (16): RedisCache, Config, ExtractConfig, load, RedisConfig, RouteConfig, _extract_from_html, fetch (+8 more)

### Community 4 - "Cache Layer & Request Flow"
Cohesion: 0.18
Nodes (15): CacheMiss, CacheStale, RedisCache.get, RedisCache.set, _build_url, _cache_key, _respond, handler (inner) (+7 more)

### Community 5 - "Rate Limiter"
Cohesion: 0.19
Nodes (10): RateLimiter, Second call within interval should sleep and return True if sleep <= max_wait., If required sleep > max_wait, acquire returns False immediately., After enough time passes, acquire returns True without sleeping., Two concurrent callers should both eventually return True, spaced by the interva, test_acquire_returns_false_when_wait_exceeds_max(), test_acquire_true_after_interval_has_passed(), test_concurrent_callers_get_distinct_slots() (+2 more)

### Community 6 - "Cache Module"
Cohesion: 0.23
Nodes (6): CacheMiss, CacheStale, Return raw stored values for all keys matching prefix:*, RedisCache, Exception, mock_cache()

### Community 7 - "Stats & Lifespan"
Cohesion: 0.2
Nodes (10): RedisCache.close, RedisCache.scan_prefix, _render_stats, lifespan (async context manager), stats_page route handler, stats.all_routes, stats.get, stats.init (+2 more)

### Community 9 - "Stats Module"
Cohesion: 0.39
Nodes (5): get(), load_from_redis(), _persist(), record(), RouteStats

## Knowledge Gaps
- **25 isolated node(s):** `Return raw stored values for all keys matching prefix:*`, `/dy/{ticker} + {"ticker": "AAPL"} → "dy:AAPL"`, `Second call within interval should sleep and return True if sleep <= max_wait.`, `If required sleep > max_wait, acquire returns False immediately.`, `After enough time passes, acquire returns True without sleeping.` (+20 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `create_app()` connect `App Core & Routing` to `Rate Limiter`, `Cache Module`?**
  _High betweenness centrality (0.233) - this node is a cross-community bridge._
- **Why does `RedisCache` connect `Cache Module` to `App Core & Routing`, `Stats Tests`?**
  _High betweenness centrality (0.145) - this node is a cross-community bridge._
- **Are the 12 inferred relationships involving `create_app()` (e.g. with `RedisCache` and `RateLimiter`) actually correct?**
  _`create_app()` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `_make_config()` (e.g. with `RouteConfig` and `Config`) actually correct?**
  _`_make_config()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `load()` (e.g. with `test_fetch_interval_parsed()` and `test_fetch_interval_defaults()`) actually correct?**
  _`load()` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `RateLimiter` (e.g. with `create_app()` and `test_first_acquire_returns_true()`) actually correct?**
  _`RateLimiter` has 6 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Return raw stored values for all keys matching prefix:*`, `/dy/{ticker} + {"ticker": "AAPL"} → "dy:AAPL"`, `Second call within interval should sleep and return True if sleep <= max_wait.` to the rest of the system?**
  _25 weakly-connected nodes found - possible documentation gaps or missing edges._