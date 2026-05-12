---
title: Per-Route Rate Limiter
date: 2026-05-10
status: approved
---

## Goal

Prevent cachest from querying any remote site more often than a configurable minimum interval. Limit is per route config entry (all tickers on the same URL template share one limiter).

## Config Changes

`RouteConfig` gains two optional fields:

```yaml
routes:
  - path: /dy/{ticker}
    url: "https://dividendhistory.org/payout/{ticker}/"
    cache_ttl: 86400
    fetch_interval: 2      # min seconds between remote fetches; default 2
    fetch_max_wait: 4      # max queue wait before falling back to stale; default 4
```

`config.py`: add `fetch_interval: float = 2.0` and `fetch_max_wait: float = 4.0` to `RouteConfig` dataclass. Parse from YAML in `load()`.

## New File: `rate_limiter.py`

```python
class RateLimiter:
    def __init__(self, interval: float, max_wait: float): ...
    async def acquire(self) -> bool: ...
```

`acquire()` logic:
1. Acquire `asyncio.Lock` (serialises concurrent fetches for this route)
2. Compute `sleep = interval - (now - last_fetch)`
3. If `sleep <= 0`: update `last_fetch`, release lock, return `True`
4. If `sleep > max_wait`: release lock immediately, return `False`
5. Else: `await asyncio.sleep(sleep)`, update `last_fetch`, release lock, return `True`

Returns `True` = caller should fetch remote. Returns `False` = caller should use stale cache.

## Changes to `fetcher.py`

Add `UpstreamError` exception class raised on HTTP 403, 429, 502 (any status that should trigger stale fallback). Existing `RateLimitedError` subsumed or kept as alias.

## Changes to `main.py`

`make_handler` receives a `RateLimiter` per route (constructed in `create_app`).

Request flow:

```
cache HIT  →  return HIT (unchanged)

cache MISS or forceRefresh:
  limiter.acquire()
    False  →  log WARN "fetch_max_wait exceeded, serving stale"
              return stale from cache  (503 if no stale exists)
    True   →  fetch remote
               UpstreamError (403/429/502)
                 →  log WARN with status code
                    return stale from cache  (503 if no stale)
               other exception  →  502 (unchanged)
               success  →  cache.set + return value
```

## Testing

1. Build Docker image locally.
2. Start stack with `docker compose up`.
3. Use `curl` or dev-browser to hit a route twice in quick succession — second call should be served from cache or queued, not trigger two remote fetches.
4. Verify logs show rate-limiter activity.

## Files Touched

| File | Change |
|------|--------|
| `config.py` | Add `fetch_interval`, `fetch_max_wait` to `RouteConfig`; parse in `load()` |
| `rate_limiter.py` | New file |
| `fetcher.py` | Add `UpstreamError` for 403/429/502 |
| `main.py` | Wire `RateLimiter` per route; update handler fallback logic |
| `config.yaml` | Add example `fetch_interval`/`fetch_max_wait` to existing routes |
