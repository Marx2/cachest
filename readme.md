# cachest — HTTP Caching Proxy

Config-driven HTTP caching proxy. Routes, remote URLs, HTML extraction rules,
and TTLs live entirely in `config.yaml`. Fetches upstream on cache miss, stores
in Redis, returns cached value on subsequent requests.

## Quick Start

```
docker compose up --build
```

Builds app image, starts Redis, registers routes. App listens on `:8080`.

## config.yaml Structure

```yaml
redis:
  host: redis        # Docker service name; use "localhost" for local dev
  port: 6379
  password: ""
  db: 0

routes:
  - name: DIVIDENDHISTORY           # used for env var API key lookup and quota keys
    path: /dyhistory/{ticker}
    url: "https://dividendhistory.org/payout/{ticker}/"
    extract:
      selector: "dl.metrics-list .metric-row"   # CSS selector for rows
      label: "Yield"                             # <dt> text to match
      field: "dd"                                # sibling element to return
    cache_ttl: 86400       # seconds (24h) — freshness window
    stale_ttl: 2592000     # seconds (30 days) — how long key survives for stale fallback
    fetch_interval: 2      # min seconds between remote fetches (default: 2)
    fetch_max_wait: 4      # max seconds to queue before falling back to stale (default: 4)

  - name: ALPHAVANTAGE
    path: /dy/{ticker}
    url: "https://www.alphavantage.co/query?function=OVERVIEW&symbol={ticker}&apikey={api_key}&datatype=csv"
    cache_ttl: 86400
    stale_ttl: 2592000
    fetch_interval: 2
    fetch_max_wait: 4

  - name: FMP
    path: /dy2/{ticker}
    url: "https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey={api_key}"
    daily_limit: 250       # max upstream fetches per calendar day; 0 = unlimited (default: 0)
    cache_ttl: 86400
    stale_ttl: 2592000
    fetch_interval: 2
    fetch_max_wait: 4

  - name: PRICE
    path: /price/{ticker}
    url: "https://someapi.com/price/{ticker}"
    cache_ttl: 300
    stale_ttl: 2592000
    fetch_interval: 2
    fetch_max_wait: 4
```

Path params use `{name}` syntax and are substituted into the URL template.
`{api_key}` in a URL template is a special placeholder — resolved from env, not a path param.
Multiple path params supported: `/foo/{a}/{b}` → url template with `{a}` and `{b}`.

## API Keys

Routes with `{api_key}` in their URL template get the key injected at startup from env vars.
Convention: `name: ALPHAVANTAGE` → env var `API_ALPHAVANTAGE`.

Create a `.env` file in the project root (already in `.gitignore`):

```
API_ALPHAVANTAGE=your_alphavantage_key_here
API_FMP=your_fmp_key_here
```

The app loads `.env` automatically via `python-dotenv`. If the file is absent, routes without
a key still work — the `{api_key}` placeholder is replaced with an empty string.

Docker passes the file via `env_file` in `docker-compose.yml` (`required: false` so the
container starts even without a `.env`).

## Daily Quota

Routes can set `daily_limit: N` to cap upstream fetches per UTC calendar day.

When the counter exceeds the limit:
1. Stale cache is returned if available (`X-Cache: STALE`, `X-Cache-Stale-Reason: quota-exceeded`)
2. If no stale value, returns HTTP 503

Counter key in Redis: `limit:{NAME}:{YYYY-MM-DD}` (e.g. `limit:FMP:2026-05-13`). TTL = 90 000 s (~25 h).
Counter increments only on actual upstream calls — cache hits don't count.
`daily_limit: 0` (default) = unlimited.

Inspect or override via redis-cli:
```sh
docker compose exec redis redis-cli GET "limit:FMP:2026-05-13"
docker compose exec redis redis-cli SET "limit:FMP:2026-05-13" 251
```

## Usage

```sh
# Dividend history (dividendhistory.org)
curl -D - http://localhost:8080/dyhistory/AAPL

# Alphavantage overview (requires API_ALPHAVANTAGE in .env)
curl -D - http://localhost:8080/dy/AAPL

# FMP profile (requires API_FMP in .env; subject to daily_limit: 250)
curl -D - http://localhost:8080/dy2/AAPL

# Force fresh fetch, bypass cache
curl -D - "http://localhost:8080/dyhistory/AAPL?forceRefresh=true"

# Price
curl http://localhost:8080/price/VZ
```

## Response Headers

| Header | Meaning |
|--------|---------|
| `X-Cache: MISS` | First fetch (value stored in Redis) |
| `X-Cache: HIT` | Served from Redis cache |
| `X-Cache: STALE` | Upstream error, rate limit, or quota exceeded — stale value returned |

`X-Cache-Stale-Reason` header gives the specific cause (`rate-limited`, `upstream-429`, `quota-exceeded`, etc.).

## Rate Limiting

Each route enforces a minimum interval between upstream fetches (`fetch_interval`, default 2s).
If a request arrives before the interval has elapsed, it waits up to `fetch_max_wait` seconds
(default 4s). If the wait would exceed `fetch_max_wait`, the latest cached value is returned
immediately (even if days old). This applies to `?forceRefresh=true` as well.
On upstream error or rate limit exceeded, stale data up to `stale_ttl` seconds old is served.

## Error Codes

| Code | Meaning |
|------|---------|
| `502` | Upstream fetch failed (network/other error) |
| `503` | Upstream error, rate limit, or daily quota exceeded AND no cached value available |
| `404` | Route not configured in config.yaml |

## Testing with Docker

```sh
docker compose --profile test run --rm test
```

## Local Dev Without Docker

1. Start a local Redis: `redis-server`
2. Edit `config.yaml`: set `redis.host` to `"localhost"`
3. Create venv and install deps:
   ```sh
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
4. Run:
   ```sh
   uvicorn main:app --port 8080
   ```
5. Test:
   ```sh
   curl -D - http://localhost:8080/dyhistory/AAPL
   ```

## Verify Redis Key

```sh
docker compose exec redis redis-cli GET "dyhistory:AAPL"
```

## Teardown

```sh
docker compose down
```
