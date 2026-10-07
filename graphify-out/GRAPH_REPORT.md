# Graph Report - cachest  (2026-10-07)

## Corpus Check
- 20 files · ~20,257 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 648 nodes · 1013 edges · 41 communities (27 shown, 14 thin omitted)
- Extraction: 79% EXTRACTED · 21% INFERRED · 0% AMBIGUOUS · INFERRED: 208 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d5b45934`
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
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]

## God Nodes (most connected - your core abstractions)
1. `load()` - 71 edges
2. `client()` - 51 edges
3. `create_app()` - 33 edges
4. `_make_config()` - 29 edges
5. `ExtractConfig` - 24 edges
6. `RedisCache` - 21 edges
7. `_write()` - 18 edges
8. `cachest — HTTP Caching Proxy` - 17 edges
9. `cache_key()` - 16 edges
10. `UpstreamError` - 15 edges

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

## Communities (41 total, 14 thin omitted)

### Community 0 - "App Core & Routing"
Cohesion: 0.06
Nodes (56): client(), _quota_config(), Redis being down must not take the endpoint down., A ticker containing a query separator must not extend the upstream URL., A timeout is transient, so the cached value beats a 502., A broken selector or renamed json_field would be indistinguishable from correct, A caller must not be able to turn a key into a pattern and flush a prefix., The prefix becomes part of a SCAN pattern — `prefix=*` would flush everything. (+48 more)

### Community 1 - "Fetcher & Config Loading"
Cohesion: 0.06
Nodes (53): ExtractConfig, build_url(), _extract_from_html(), _extract_json(), ExtractionError, fetch(), _fetch_with(), RateLimitedError (+45 more)

### Community 2 - "Stats Tests"
Cohesion: 0.07
Nodes (45): cache_key(), key_label(), key_pattern(), key_prefix(), key_segments(), path_params_of(), Cache-key construction and the patterns that go with it.  A cache key is derived, Validate a key or key fragment before it is used in a Redis pattern or DEL. (+37 more)

### Community 3 - "AST Semantic Overlap"
Cohesion: 0.05
Nodes (20): Extending the TTL on every call would keep a dead day's counter alive forever., A key removed between SCAN and MGET comes back as None and must be dropped,, One huge MGET would block the Redis event loop, so reads are chunked., Regression: cachest's "stats:" counters are hashes in this same database, and, Regression: invalidation used to SCAN "prefix:ticker" with no wildcard, which, A caller must not be able to smuggle a pattern in and flush a whole prefix., The load-bearing case. A pooled connection can look established while the     se, A non-True reply must not leak through as truthy: `bool()` is the coercion     t (+12 more)

### Community 4 - "Cache Layer & Request Flow"
Cohesion: 0.06
Nodes (21): CacheStale, Return {key: body-preview} for the given keys, reading only a prefix., Return [(key, raw_value)] for every key in the database.          Convenience fo, Yield (key, raw_value) across the whole database in chunks.          The caller, Delete every key matching a glob pattern. Returns the number deleted., Delete exact keys. Rejects anything outside our own key charset so a         cal, Apply several HINCRBYs to one hash in a single round trip., §64.2 — is the cache actually reachable right now?          For the readiness pr (+13 more)

### Community 5 - "Rate Limiter"
Cohesion: 0.07
Nodes (41): CacheMiss, CacheStale, RedisCache, RedisCache.close, RedisCache.get, RedisCache.scan_prefix, RedisCache.set, Config (+33 more)

### Community 6 - "Cache Module"
Cohesion: 0.05
Nodes (38): code:python (import pytest), code:python (import asyncio), code:bash (pytest tests/test_rate_limiter.py -v), code:bash (git add rate_limiter.py tests/test_rate_limiter.py), code:python (import pytest), code:bash (pip install respx --quiet), code:python (import httpx), code:bash (pytest tests/test_fetcher.py -v) (+30 more)

### Community 7 - "Stats & Lifespan"
Cohesion: 0.1
Nodes (35): load(), Config loading and validation.  These tests exercise behaviour that can actually, The validation above runs against the real file on every test session., The NARROW_FANOUT exemption is a decision, not an oversight — pin both halves., Both back a daily refresh job, so they carry the same TTL by the same     reason, Per-keystroke searches share a TTL, unlike the crypto universe search.      The, `/equity/metrics` stays at 24h on purpose.      P/E, market cap and the margins, test_fetch_interval_defaults() (+27 more)

### Community 8 - "Cache Tests"
Cohesion: 0.06
Nodes (9): clean_registry(), Synchronous callers (tests, startup) must not blow up on create_task., stats keeps module-level state, so every test starts from a known baseline., Redis being down must not stop the app; the dashboard just forgets history —, A stats write failing must never surface to the caller., test_all_routes_snapshot(), test_load_from_redis_failure_starts_from_zero(), test_persist_failure_does_not_break_the_request_path() (+1 more)

### Community 9 - "Stats Module"
Cohesion: 0.07
Nodes (34): API Keys, Cache keys, cachest — HTTP Caching Proxy, code:sh (docker compose up --build), code:sh (redis-cli GET "dyhistory:AAPL"     # "<unix-ts>|<value>"), code:sh (docker compose down), code:yaml (routes:), code:yaml (- name: OPENST_OHLCV) (+26 more)

### Community 10 - "Assets"
Cohesion: 0.1
Nodes (29): create_app(), _make_config(), _news_config(), On UpstreamError, serve stale from cache., On UpstreamError, serve stale from cache., On UpstreamError, serve stale from cache., forceRefresh=true is still subject to rate limiting; stale is served if acquire(, forceRefresh=true is still subject to rate limiting; stale is served if acquire( (+21 more)

### Community 11 - "Community 11"
Cohesion: 0.08
Nodes (24): Two routes with one path would share cache keys and serve each other's data., An unresolvable placeholder used to be sent to the upstream literally., Otherwise every value is stale the instant it is written and the fallback is dea, Quota keys are "limit:{name}:{date}" — no name means the limit is ignored., Documents the asymmetry on purpose: REDIS_PORT/REDIS_DB were declared as env var, REDIS_HOST had an env override but REDIS_PASSWORD did not — they now agree., test_api_key_placeholder_always_allowed(), test_api_key_resolved_from_env() (+16 more)

### Community 12 - "Community 12"
Cohesion: 0.14
Nodes (15): RateLimiter, The bug that made CI red for two days.      `_last_fetch` used to be initialised, If required sleep > max_wait, acquire returns False immediately., After enough time passes, acquire returns True without sleeping., Two concurrent callers should both eventually return True, spaced by the interva, Second call within interval should sleep and return True if sleep <= max_wait., If required sleep > max_wait, acquire returns False immediately., After enough time passes, acquire returns True without sleeping. (+7 more)

### Community 13 - "Community 13"
Cohesion: 0.22
Nodes (12): _delete_all_stats(), drain(), _field_for(), get(), load_from_redis(), _persist(), Run a write in the background without losing the task.      The task is held in, Wait for outstanding counter writes. Called from lifespan shutdown. (+4 more)

### Community 14 - "Community 14"
Cohesion: 0.14
Nodes (11): _build_url(), _cache_key(), _histogram_html(), make_handler(), Bar heights + labels for the age histogram., /dy/{ticker} + {"ticker": "AAPL"} → "dy:AAPL", /dy/{ticker} + {"ticker": "AAPL"} → "dy:AAPL"; /calendar/earnings → "calendar:ea, /dy/{ticker} + {"ticker": "AAPL"} → "dy:AAPL"; /calendar/earnings → "calendar:ea (+3 more)

### Community 15 - "Community 15"
Cohesion: 0.14
Nodes (14): CacheMiss, mock_cache(), _query_config(), When acquire() returns False and no stale exists, return 503., When acquire() returns False and no stale exists, return 503., On UpstreamError with no stale, return 503., On UpstreamError with no stale, return 503., On UpstreamError with no stale, return 503. (+6 more)

### Community 16 - "Community 16"
Cohesion: 0.18
Nodes (11): Config, ConfigError, Raised for a config.yaml that would misbehave at runtime., RedisConfig, RouteConfig, _validate(), test_queue_depth_is_floor_max_wait_over_interval_plus_one(), test_queue_depth_is_unbounded_without_pacing() (+3 more)

### Community 17 - "Community 17"
Cohesion: 0.18
Nodes (10): Changes to `fetcher.py`, Changes to `main.py`, code:yaml (routes:), code:python (class RateLimiter:), code:block3 (cache HIT  →  return HIT (unchanged)), Config Changes, Files Touched, Goal (+2 more)

### Community 18 - "Community 18"
Cohesion: 0.22
Nodes (7): btn, entries, entriesEl, keys, removed, renderCacheTable(), setSortDesc()

### Community 19 - "Community 19"
Cohesion: 0.4
Nodes (6): _depth_msg(), The price-bar routes carry the 175+ symbol snapshots-sync burst., Every other symbol-keyed route carries one page of the SPA (~80 rows)., test_real_config_queue_depth_absorbs_a_portfolio_sweep(), test_real_config_queue_depth_absorbs_a_ui_page(), _too_shallow()

### Community 20 - "Community 20"
Cohesion: 0.4
Nodes (5): 16 concurrent callers, the real RateLimiter, the shipped interval/max_wait., The one deliberate depth-1 route must keep rejecting, or the exemption in     te, _real_limiter_client(), test_shipped_ohlcv_route_serves_a_full_portfolio_sweep(), test_shipped_singleton_route_is_still_serialized()

### Community 21 - "Community 21"
Cohesion: 0.4
Nodes (5): limiter(), When acquire() returns False, serve stale from cache., RateLimiter patched for the whole test. Set `limiter.allowed = False` to make, When acquire() returns False, serve stale from cache., test_rate_limiter_false_returns_stale()

### Community 22 - "Community 22"
Cohesion: 0.67
Nodes (3): _ensure_otel(), One MeterProvider per process, shared by every app instance.      create_app() m, setup_otel()

### Community 23 - "Community 23"
Cohesion: 0.5
Nodes (4): Upstream error + CacheStale → serve stale value., Upstream error + CacheStale → serve stale value., Upstream error + CacheStale → serve stale value., test_stale_entry_served_on_upstream_error()

### Community 24 - "Community 24"
Cohesion: 0.33
Nodes (4): Values are embedded as JSON in a data block, so "</script>" inside a cached, A cached value is an upstream body and can be arbitrarily large; only a short, test_stats_page_embeds_json_not_javascript(), test_stats_page_previews_are_truncated()

### Community 25 - "Community 25"
Cohesion: 0.5
Nodes (4): Rate-limited + CacheStale → serve stale value., Rate-limited + CacheStale → serve stale value., Rate-limited + CacheStale → serve stale value., test_stale_entry_served_when_rate_limited()

### Community 26 - "Community 26"
Cohesion: 0.67
Nodes (3): A 404 means "no data for this key" — not a transient outage, so it is neither, A 404 from upstream means 'no data' — pass it through, don't 503/502., test_upstream_404_passes_through()

## Knowledge Gaps
- **215 isolated node(s):** `Raised for a config.yaml that would misbehave at runtime.`, `How many concurrent upstream fetches this route admits.          ``RateLimiter```, `§64.2 — is the cache actually reachable right now?          For the readiness pr`, `Return the value, or raise CacheMiss (absent/unparseable) / CacheStale (too old)`, `Value regardless of age, or None when the key is absent.          For stale fall` (+210 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `load()` connect `Stats & Lifespan` to `Community 32`, `Fetcher & Config Loading`, `Community 34`, `Community 33`, `Community 36`, `Community 37`, `Community 35`, `Stats Tests`, `Assets`, `Community 11`, `Community 16`, `Community 19`, `Community 20`, `Community 27`, `Community 28`, `Community 29`, `Community 31`?**
  _High betweenness centrality (0.209) - this node is a cross-community bridge._
- **Why does `create_app()` connect `Assets` to `Cache Layer & Request Flow`, `Community 12`, `Community 14`, `Community 15`, `Community 20`, `Community 21`, `Community 22`, `Community 23`, `Community 25`, `Community 26`?**
  _High betweenness centrality (0.105) - this node is a cross-community bridge._
- **Why does `RedisCache` connect `Cache Layer & Request Flow` to `Community 16`, `Assets`?**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **Are the 64 inferred relationships involving `load()` (e.g. with `.set()` and `test_loads_defaults()`) actually correct?**
  _`load()` has 64 INFERRED edges - model-reasoned connections that need verification._
- **Are the 31 inferred relationships involving `create_app()` (e.g. with `RedisCache` and `setup_otel()`) actually correct?**
  _`create_app()` has 31 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `_make_config()` (e.g. with `Config` and `RedisConfig`) actually correct?**
  _`_make_config()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 22 inferred relationships involving `ExtractConfig` (e.g. with `UpstreamError` and `RateLimitedError`) actually correct?**
  _`ExtractConfig` has 22 INFERRED edges - model-reasoned connections that need verification._