# cachest — HTTP Caching Proxy

Config-driven HTTP caching proxy. Routes, upstream URLs, extraction rules, and TTLs live
entirely in `config.yaml`. On a cache miss cachest fetches the upstream and stores the
result in Redis; subsequent requests are served from Redis. When an upstream is slow,
throttled, or down, the last known value is served stale rather than failing.

## Quick Start

```sh
docker compose up --build
```

Starts Redis and the app (`:8080`), plus the `openst` dependency that most routes proxy.
`/` redirects to `/stats`.

## Configuration

Everything is declared in `config.yaml`. A minimal route:

```yaml
routes:
  - name: VENDOR                 # used for the API-key env var and the quota key
    path: /price/{ticker}        # the public path; {ticker} is a path param
    url: "https://api.vendor.com/price/{ticker}"
    cache_ttl: 300               # seconds before a value goes stale
    stale_ttl: 2592000           # seconds the key survives for stale fallback
    fetch_interval: 2            # min seconds between upstream fetches (default 2)
    fetch_max_wait: 4            # max queue wait before serving stale (default 4)
```

| Key | Default | Meaning |
|-----|---------|---------|
| `path` | required | Public path. `{name}` placeholders become path params. |
| `url` | required | Upstream URL template. |
| `cache_ttl` | required | Seconds a value counts as fresh. |
| `stale_ttl` | `2592000` (30d) | How long the key survives in Redis. Must be ≥ `cache_ttl`. |
| `name` | `""` | Identifies the vendor. Required for `api_key` and `daily_limit`. |
| `daily_limit` | `0` (unlimited) | Max upstream fetches per UTC day. |
| `json_field` | `""` | Pull one field out of a JSON response. |
| `extract.selector` | `""` | CSS selector for HTML extraction. |
| `extract.label` | `""` | `<dt>` text to match inside the selected row. |
| `extract.field` | `""` | Element to return from the matched row. |
| `query_params` | `[]` | Required query parameters, appended to the cache key. |
| `fetch_interval` | `2.0` | Min seconds between upstream fetches. |
| `fetch_max_wait` | `4.0` | Max seconds a request queues before serving stale. |
| `fetch_timeout` | `15.0` | Per-request upstream timeout, in seconds. |

### Extraction

`fetcher.py` applies exactly one strategy, in this order:

1. **`json_field`** — parse the response as JSON and return `str(data[json_field])`.
2. **`extract.selector`** — find rows matching the selector, match `extract.label`
   against the row's `<dt>`, return the text of `extract.field`.
3. **Neither** — return the response body, stripped. This is the passthrough used by
   29 of the 31 shipped routes, so provider-specific fields survive untouched.

A failure in (1) or (2) returns `502` and is **never** answered with stale data — a
stale value would be indistinguishable from a correct one. Only upstream errors and
transport failures fall back to stale.

### Query parameters

```yaml
  - name: OPENST_OHLCV
    path: /ohlcv/{ticker}
    url: "http://openst:8080/price/ohlcv/{ticker}?start={start}&end={end}"
    query_params: [start, end]
    cache_ttl: 21600
    fetch_timeout: 120           # a multi-page scrape can take ~20s
```

Every name in `query_params` becomes part of the cache key, so
`?end=2026-01-01` and `?end=2026-02-01` are cached separately. A request missing one of
them gets `422` and is never sent upstream.

Path params and query values are percent-encoded before they reach the upstream URL, so
a value can never inject a query string or traverse a path.

### Validation

`config.load()` rejects a config that would misbehave, naming the offending route:
duplicate `path` (colliding cache keys), a `{placeholder}` in `url` that is neither a
path param nor a declared `query_param` nor `{api_key}`, `stale_ttl` shorter than
`cache_ttl`, `daily_limit` without a `name`, negative TTLs, and `json_field` set
together with `extract.selector`.

### Cache keys

A key is the path template with `{}` substituted, `/` turned into `:`, and one segment
appended per query param:

| Route | Request | Key |
|-------|---------|-----|
| `/dy/{ticker}` | `/dy/AAPL` | `dy:AAPL` |
| `/ohlcv/{ticker}` | `?start=a&end=b` | `ohlcv:AAPL:a:b` |
| `/ohlcv/fund/{ticker}` | `?start=a&end=b` | `ohlcv:fund:AAPL:a:b` |
| `/calendar/earnings` | `?start=a&end=b` | `calendar:earnings:a:b` |

Sibling routes never share a key, which is what lets `/stats` attribute every key to
exactly one route.

## API Keys

Routes with `{api_key}` in their URL get it injected at load time from the environment.
Convention: `name: ALPHAVANTAGE` → `API_ALPHAVANTAGE`.

Create a `.env` in the project root (already in `.gitignore`):

```
API_ALPHAVANTAGE=your_alphavantage_key
API_FMP=your_fmp_key
```

If `.env` is absent, those routes still start and `{api_key}` resolves to an empty
string. The key never appears in a log line, on the `/stats` page, or in a cache key.
Docker passes the file via `env_file` in `docker-compose.yml`.

## Daily Quota

`daily_limit: N` caps upstream fetches per UTC calendar day. On exceeding it, cachest
serves stale if available (`X-Cache: STALE`, `X-Cache-Stale-Reason: quota-exceeded`),
else `503`.

Counter key: `limit:{NAME}:{YYYY-MM-DD}`, TTL 90 000 s (~25 h) so it outlives the day it
counts. The TTL is set only when the counter is created, so traffic never extends the
life of a dead day's counter. Only requests that reach the upstream consume quota —
cache hits do not.

```sh
docker compose exec redis redis-cli GET "limit:FMP:$(date -u +%F)"
docker compose exec redis redis-cli SET "limit:FMP:$(date -u +%F)" 10   # reset
```

## Rate Limiting

Each route enforces `fetch_interval` between upstream fetches. A request arriving early
waits up to `fetch_max_wait`, then gets the cached value immediately however old it is.
`?forceRefresh=true` skips the cache read but is still rate limited and still subject to
the daily quota.

## Response Headers

| Header | Meaning |
|--------|---------|
| `X-Cache: HIT` | Served from Redis |
| `X-Cache: MISS` | Fetched from upstream and stored |
| `X-Cache: STALE` | Upstream problem; cached value served instead |
| `X-Cache-Stale-Reason` | `rate-limited`, `quota-exceeded`, `upstream-429`, … |

## Error Codes

| Code | Meaning |
|------|---------|
| `404` | Upstream has no data for this key, or no such route. Not cached, not retried. |
| `422` | A required query parameter is missing. |
| `502` | Upstream responded but the body could not be parsed (selector drift, bad `json_field`), or the request failed outright. |
| `503` | Upstream error, rate limit, or quota exceeded **and** no cached value exists. |

`502` and `503` are deliberately different: `503` means "ask again later or take the
stale value", `502` means "our extraction is broken and a human should look".

## Operations

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Liveness. |
| `GET /__meta` | Service name and `APP_VERSION`. |
| `GET /metrics` | Prometheus, including per-upstream client latency. |
| `GET /stats` | Dashboard: per-route HIT/MISS/STALE/ERROR, key-age histogram, cache browser. |

`/stats` also drives three admin endpoints. **They are unauthenticated and destructive —
put them behind your ingress.**

| Endpoint | Effect |
|----------|--------|
| `POST /stats/reset` | Zero all counters. |
| `POST /stats/reset-cache/{prefix}` | Delete every key under a path prefix. |
| `POST /stats/invalidate-keys` | Body `{"keys": [...]}`. Deletes exactly those keys. |

`invalidate-keys` takes full keys rather than a `prefix/ticker` pattern, because a
ticker alone cannot address a key that carries query segments. Both endpoints validate
their input against cachest's own key charset, so a caller cannot pass a wildcard and
flush a prefix — or the whole keyspace — by accident.

## Testing

```sh
docker compose --profile test run --rm test     # local
docker build --target test -t cachest-test . && docker run --rm cachest-test   # as CI runs it
```

No services are required — every test mocks Redis and the upstream. Tests also run on
every push and pull request via the `test` job in `.github/workflows/docker-image.yml`.

## Local Dev Without Docker

```sh
redis-server
```

Set `redis.host: "localhost"` in `config.yaml`, then:

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8080
```

Inspect a cached value:

```sh
redis-cli GET "dyhistory:AAPL"     # "<unix-ts>|<value>"
```

## Layout

| File | Role |
|------|------|
| `main.py` | App wiring, request handler, stats page data. |
| `config.py` | Config parsing and validation. |
| `cache.py` | Redis access. The only module that talks to Redis. |
| `keys.py` | Cache-key construction, patterns, and key safety. |
| `fetcher.py` | Upstream fetch and extraction. |
| `rate_limiter.py` | Per-route upstream spacing. |
| `stats.py` | Per-route counters. |
| `otel.py` | Metrics and tracing setup. |
| `templates/`, `static/` | `/stats` page. Styles follow `.interface-design/system.md`. |
