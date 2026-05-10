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
  - path: /dy/{ticker}
    url: "https://dividendhistory.org/payout/{ticker}/"
    extract:
      selector: "dl.metrics-list .metric-row"   # CSS selector for rows
      label: "Yield"                             # <dt> text to match
      field: "dd"                                # sibling element to return
    cache_ttl: 86400       # seconds (24h)
    fetch_interval: 2      # min seconds between remote fetches (default: 2)
    fetch_max_wait: 4      # max seconds to queue before falling back to stale (default: 4)

  - path: /price/{ticker}
    url: "https://someapi.com/price/{ticker}"
    # no extract block = return plain response body as-is
    cache_ttl: 300
    fetch_interval: 2
    fetch_max_wait: 4
```

Path params use `{name}` syntax and are substituted into the URL template.
Multiple params supported: `/foo/{a}/{b}` → url template with `{a}` and `{b}`.

## Usage

```sh
# Fetch dividend yield (cache miss on first call)
curl -D - http://localhost:8080/dy/AAPL

# Repeat — served from Redis cache
curl -D - http://localhost:8080/dy/AAPL

# Force fresh fetch, bypass cache
curl -D - "http://localhost:8080/dy/AAPL?forceRefresh=true"

# Another ticker
curl http://localhost:8080/dy/VZ
```

## Response Headers

| Header | Meaning |
|--------|---------|
| `X-Cache: MISS` | First fetch (value stored in Redis) |
| `X-Cache: HIT` | Served from Redis cache |
| `X-Cache: STALE` | Upstream error (403/429/502) or rate limit exceeded — stale value returned |

`X-Cache-Stale-Reason` header gives the specific cause (`rate-limited`, `upstream-429`, etc.).

## Rate Limiting

Each route enforces a minimum interval between upstream fetches (`fetch_interval`, default 2s).
If a request arrives before the interval has elapsed, it waits up to `fetch_max_wait` seconds
(default 4s). If the wait would exceed `fetch_max_wait`, the latest cached value is returned
immediately (even if days old). This applies to `?forceRefresh=true` as well.

## Error Codes

| Code | Meaning |
|------|---------|
| `502` | Upstream fetch failed (network/other error) |
| `503` | Upstream error or rate limit exceeded AND no cached value available |
| `404` | Route not configured in config.yaml |

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
   curl -D - http://localhost:8080/dy/AAPL
   ```

## Verify Redis Key

```sh
docker compose exec redis redis-cli GET "dy:AAPL"
```

## Teardown

```sh
docker compose down
```
