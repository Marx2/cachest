import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response

load_dotenv()

import stats
from cache import CacheMiss, CacheStale, RedisCache
from config import Config, RouteConfig, load
from fetcher import UpstreamError, fetch
from rate_limiter import RateLimiter

logger = logging.getLogger("cachest")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

CONFIG_PATH = "config.yaml"


def _cache_key(
    path_template: str,
    path_params: dict[str, str],
    query_values: dict[str, str] | None = None,
) -> str:
    """/dy/{ticker} + {"ticker": "AAPL"} → "dy:AAPL"; /calendar/earnings → "calendar:earnings";
    query values are appended in declared order → /ohlcv/{ticker}+{start,end} → "ohlcv:AAPL:<start>:<end>" """
    key = path_template
    for k, v in path_params.items():
        key = key.replace(f"{{{k}}}", str(v))
    parts = [key.strip("/").replace("/", ":")]
    for v in (query_values or {}).values():
        parts.append(str(v))
    return ":".join(parts)


def _build_url(
    template: str,
    path_params: dict[str, str],
    api_key: str = "",
    query_values: dict[str, str] | None = None,
) -> str:
    url = template
    for k, v in path_params.items():
        url = url.replace(f"{{{k}}}", v)
    for k, v in (query_values or {}).items():
        url = url.replace(f"{{{k}}}", v)
    return url.replace("{api_key}", api_key)


def _respond(route_path: str, value: str, x_cache: str, **extra_headers) -> PlainTextResponse:
    stats.record(route_path, x_cache)
    return PlainTextResponse(value, headers={"X-Cache": x_cache, **extra_headers})


def make_handler(route: RouteConfig, cache: RedisCache, limiter: RateLimiter):
    async def handler(request: Request) -> PlainTextResponse:
        path_params: dict[str, Any] = dict(request.path_params)
        query_values = {p: request.query_params.get(p) for p in route.query_params}
        missing = [p for p, v in query_values.items() if v is None]
        if missing:
            stats.record(route.path, "ERROR")
            return PlainTextResponse(
                f"missing required query parameter(s): {', '.join(missing)}",
                status_code=422,
            )
        key = _cache_key(route.path, path_params, {k: v or "" for k, v in query_values.items()})
        force_refresh = request.query_params.get("forceRefresh") == "true"

        if not force_refresh:
            try:
                value = await cache.get(key, route.cache_ttl)
                return _respond(route.path, value, "HIT")
            except CacheMiss:
                pass
            except CacheStale:
                pass  # expired but present; fall through to re-fetch
            except Exception as e:
                logger.warning("cache GET %r failed: %s — proceeding without cache", key, e)

        allowed = await limiter.acquire()
        if not allowed:
            logger.warning("[rate-limit] max_wait exceeded for %r (forceRefresh=%s) — no upstream call made", key, force_refresh)
            try:
                stale = await cache.get(key, route.cache_ttl)
                return _respond(route.path, stale, "STALE", **{"X-Cache-Stale-Reason": "rate-limited"})
            except CacheStale as e:
                return _respond(route.path, e.value, "STALE", **{"X-Cache-Stale-Reason": "rate-limited"})
            except CacheMiss:
                pass
            stats.record(route.path, "ERROR")
            return PlainTextResponse("rate limit exceeded and no cached value available", status_code=503)

        if route.daily_limit > 0 and route.name:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            quota_key = f"limit:{route.name}:{today}"
            count = await cache._client.incr(quota_key)
            if count == 1:
                await cache._client.expire(quota_key, 90_000)
            if count > route.daily_limit:
                logger.warning("[quota] daily limit %d exceeded for %r (count=%d)", route.daily_limit, route.name, count)
                try:
                    stale = await cache.get(key, route.cache_ttl)
                    return _respond(route.path, stale, "STALE", **{"X-Cache-Stale-Reason": "quota-exceeded"})
                except CacheStale as e:
                    return _respond(route.path, e.value, "STALE", **{"X-Cache-Stale-Reason": "quota-exceeded"})
                except CacheMiss:
                    pass
                stats.record(route.path, "ERROR")
                return PlainTextResponse("daily upstream limit reached", status_code=503)

        url = _build_url(route.url, path_params, route.api_key, {k: v or "" for k, v in query_values.items()})
        try:
            value = await fetch(url, route.extract, route.json_field)
        except UpstreamError as e:
            logger.warning("[upstream-error] %r returned HTTP %d — serving stale", e.url, e.status_code)
            try:
                stale = await cache.get(key, route.cache_ttl)
                return _respond(route.path, stale, "STALE", **{"X-Cache-Stale-Reason": f"upstream-{e.status_code}"})
            except CacheStale as exc:
                return _respond(route.path, exc.value, "STALE", **{"X-Cache-Stale-Reason": f"upstream-{e.status_code}"})
            except CacheMiss:
                pass
            stats.record(route.path, "ERROR")
            return PlainTextResponse(
                f"upstream returned {e.status_code} and no cached value available",
                status_code=503,
            )
        except Exception as e:
            logger.error("fetch %r failed: %s", url, e)
            stats.record(route.path, "ERROR")
            return PlainTextResponse("bad gateway: upstream fetch failed", status_code=502)

        try:
            await cache.set(key, value, route.stale_ttl)
        except Exception as e:
            logger.warning("cache SET %r failed: %s", key, e)

        return _respond(route.path, value, "MISS")

    return handler


async def _render_stats(config: Config, cache: RedisCache) -> str:
    now = int(time.time())
    route_map = {r.path: r for r in config.routes}
    all_stats = stats.all_routes()

    cards_html = []
    for route in config.routes:
        path = route.path
        s = all_stats.get(path, stats.RouteStats())

        prefix = path.lstrip("/").split("/")[0]
        raw_values = await cache.scan_prefix(prefix)

        buckets = [0] * 30
        for raw in raw_values:
            try:
                ts_str, _ = raw.split("|", 1)
                age_days = (now - int(ts_str)) // 86400
                if 0 <= age_days < 30:
                    buckets[age_days] += 1
            except (ValueError, IndexError):
                pass

        total_keys = sum(buckets)
        max_bucket = max(buckets) if any(buckets) else 1

        bars_html = []
        for i, count in enumerate(buckets):
            height_pct = int(count / max_bucket * 100) if max_bucket else 0
            label = "today" if i == 0 else (f"{i}d" if i % 5 == 0 else "")
            bars_html.append(f"""
              <div class="bar-wrap">
                <div class="bar" style="height:{height_pct}%" title="{i}d ago: {count} keys"></div>
                <div class="bar-label">{label}</div>
              </div>""")

        upstream_short = route.url[:60] + ("…" if len(route.url) > 60 else "")
        prefix = path.lstrip("/").split("/")[0]
        card = f"""
    <div class="card">
      <div class="card-header">
        <span class="route-path">{path}</span>
        <span class="upstream">{upstream_short}</span>
      </div>
      <div class="pills">
        <span class="pill pill-total">Total {s.total}</span>
        <span class="pill pill-hit">HIT {s.hits}</span>
        <span class="pill pill-miss">MISS {s.misses}</span>
        <span class="pill pill-stale">STALE {s.stale}</span>
        <span class="pill pill-error">ERROR {s.errors}</span>
      </div>
      <div class="redis-keys">Redis keys: {total_keys}</div>
      <div class="chart">{''.join(bars_html)}
      </div>
      <div class="card-actions">
        <button class="btn btn-danger" onclick="resetCache(this, '{prefix}')">Reset cache for {prefix}</button>      </div>
    </div>"""
        cards_html.append(card)

    all_entries: list[dict] = []
    for route in config.routes:
        prefix = route.path.lstrip("/").split("/")[0]
        pairs = await cache.scan_prefix_with_keys(prefix)
        ticker_map: dict[str, dict] = {}
        for key, raw in pairs:
            try:
                ts_str, value = raw.split("|", 1)
                ticker = key.split(":", 1)[1] if ":" in key else key
                ts = int(ts_str)
                if ticker not in ticker_map or ts > ticker_map[ticker]["ts"]:
                    ticker_map[ticker] = {
                        "prefix": prefix,
                        "ticker": ticker,
                        "ts": ts,
                        "value": value[:80],
                    }
            except (ValueError, IndexError):
                pass
        all_entries.extend(ticker_map.values())
    all_entries.sort(key=lambda e: e["ts"], reverse=True)
    cache_entries_json = json.dumps(all_entries)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>cachest / stats</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-canvas:      #f1f5f9;
      --bg-surface:     #ffffff;
      --bg-surface-2:   #f8fafc;
      --bg-surface-3:   #f1f5f9;
      --border-subtle:  rgba(15,23,42,0.08);
      --border-default: rgba(15,23,42,0.14);
      --border-strong:  rgba(15,23,42,0.22);
      --ink-primary:    #0f172a;
      --ink-secondary:  #475569;
      --ink-tertiary:   #94a3b8;
      --ink-muted:      #cbd5e1;
      --accent:         #2563eb;
      --accent-hover:   #1d4ed8;
      --accent-subtle:  rgba(37,99,235,0.08);
      --accent-ring:    rgba(37,99,235,0.25);
      --ctrl-bg:        #ffffff;
      --ctrl-border:    rgba(15,23,42,0.18);
      --r-sm: 4px; --r-md: 6px; --r-lg: 10px; --r-xl: 14px;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg-canvas:      #0f172a;
        --bg-surface:     #1e293b;
        --bg-surface-2:   #263348;
        --bg-surface-3:   #2d3d54;
        --border-subtle:  rgba(241,245,249,0.06);
        --border-default: rgba(241,245,249,0.10);
        --border-strong:  rgba(241,245,249,0.16);
        --ink-primary:    #f1f5f9;
        --ink-secondary:  #94a3b8;
        --ink-tertiary:   #64748b;
        --ink-muted:      #475569;
        --accent:         #3b82f6;
        --accent-hover:   #60a5fa;
        --accent-subtle:  rgba(59,130,246,0.12);
        --accent-ring:    rgba(59,130,246,0.3);
        --ctrl-bg:        #1e293b;
        --ctrl-border:    rgba(241,245,249,0.12);
      }}
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg-canvas);
      color: var(--ink-primary);
      font-family: 'Inter', system-ui, sans-serif;
      font-size: 13px;
      line-height: 1.5;
      padding: 2rem;
      max-width: 1400px;
      margin: 0 auto;
    }}
    h1 {{
      font-size: 22px;
      font-weight: 700;
      letter-spacing: -0.3px;
      color: var(--ink-primary);
      margin: 0;
    }}
    h2 {{
      font-size: 15px;
      font-weight: 600;
      color: var(--ink-primary);
      margin-bottom: 12px;
    }}
    .header-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 28px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--border-default);
    }}
    .header-title {{ display: flex; flex-direction: column; gap: 2px; }}
    .header-subtitle {{ font-size: 12px; color: var(--ink-tertiary); }}

    /* Buttons */
    .btn {{
      display: inline-flex; align-items: center; gap: 6px;
      padding: 6px 14px;
      border-radius: var(--r-md);
      font-size: 12px; font-weight: 600;
      border: 1px solid transparent;
      cursor: pointer;
      transition: background 0.12s, color 0.12s, border-color 0.12s;
      font-family: inherit;
      white-space: nowrap;
    }}
    .btn:disabled {{ opacity: 0.45; cursor: default; }}
    .btn-primary {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    .btn-primary:not(:disabled):hover {{ background: var(--accent-hover); border-color: var(--accent-hover); }}
    .btn-secondary {{
      background: var(--bg-surface-2); color: var(--ink-secondary);
      border-color: var(--border-default);
    }}
    .btn-secondary:not(:disabled):hover {{ background: var(--bg-surface-3); }}
    .btn-secondary.active {{
      background: var(--accent-subtle); color: var(--accent);
      border-color: var(--accent);
    }}
    .btn-danger {{
      background: rgba(220,38,38,0.08); color: #dc2626;
      border-color: rgba(220,38,38,0.2);
    }}
    .btn-danger:not(:disabled):hover {{ background: #dc2626; color: #fff; border-color: #dc2626; }}

    /* Route grid */
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }}
    .card {{
      background: var(--bg-surface);
      border: 1px solid var(--border-default);
      border-radius: var(--r-xl);
      padding: 20px;
    }}
    .card-header {{ margin-bottom: 12px; }}
    .route-path {{ font-size: 14px; font-weight: 600; color: var(--ink-primary); display: block; }}
    .upstream {{ font-size: 11px; color: var(--ink-tertiary); display: block; margin-top: 3px; word-break: break-all; }}

    /* Pills */
    .pills {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }}
    .pill {{
      padding: 2px 8px;
      border-radius: 9999px;
      font-size: 11px; font-weight: 600;
      border: 1px solid transparent;
    }}
    .pill-total {{ background: var(--bg-surface-2); color: var(--ink-secondary); border-color: var(--border-default); }}
    .pill-hit   {{ background: rgba(22,163,74,0.1);  color: #16a34a; border-color: rgba(22,163,74,0.25); }}
    .pill-miss  {{ background: var(--accent-subtle);  color: var(--accent); border-color: rgba(37,99,235,0.2); }}
    .pill-stale {{ background: rgba(217,119,6,0.1);  color: #d97706; border-color: rgba(217,119,6,0.25); }}
    .pill-error {{ background: rgba(220,38,38,0.08); color: #dc2626; border-color: rgba(220,38,38,0.2); }}
    @media (prefers-color-scheme: dark) {{
      .pill-hit   {{ background: rgba(22,163,74,0.15);  color: #4ade80; border-color: rgba(74,222,128,0.2); }}
      .pill-miss  {{ background: var(--accent-subtle);  color: var(--accent); border-color: rgba(59,130,246,0.25); }}
      .pill-stale {{ background: rgba(217,119,6,0.15);  color: #fbbf24; border-color: rgba(251,191,36,0.2); }}
      .pill-error {{ background: rgba(220,38,38,0.12); color: #f87171; border-color: rgba(248,113,113,0.2); }}
    }}

    .redis-keys {{ font-size: 11px; color: var(--ink-tertiary); margin-bottom: 12px; }}

    /* Bar chart */
    .chart {{
      display: flex; align-items: flex-end; gap: 2px;
      height: 52px; padding-bottom: 16px; position: relative;
    }}
    .bar-wrap {{ display: flex; flex-direction: column; align-items: center; flex: 1; height: 100%; justify-content: flex-end; }}
    .bar {{ width: 100%; background: var(--accent); border-radius: 2px 2px 0 0; min-height: 1px; opacity: 0.7; transition: height 0.2s, opacity 0.12s; }}
    .bar:hover {{ opacity: 1; }}
    .bar-label {{ font-size: 9px; color: var(--ink-tertiary); margin-top: 2px; white-space: nowrap; }}
    .card-actions {{ margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border-subtle); display: flex; gap: 8px; }}

    /* Cache browser */
    .section-header {{
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 12px;
    }}
    .cache-controls {{
      display: flex; gap: 8px; align-items: center;
      margin-bottom: 12px; flex-wrap: wrap;
    }}
    .cache-controls input {{
      background: var(--ctrl-bg);
      border: 1px solid var(--ctrl-border);
      color: var(--ink-primary);
      padding: 6px 10px;
      border-radius: var(--r-md);
      font-size: 13px;
      font-family: inherit;
      width: 220px;
      outline: none;
      transition: border-color 0.12s, box-shadow 0.12s;
    }}
    .cache-controls input:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-ring);
    }}
    .cache-controls input::placeholder {{ color: var(--ink-muted); }}
    .sort-group {{ display: flex; gap: 4px; margin-bottom: 12px; }}

    /* Table */
    .table-wrap {{
      border: 1px solid var(--border-default);
      border-radius: var(--r-lg);
      overflow: hidden;
    }}
    .cache-table {{
      width: 100%; border-collapse: collapse; font-size: 13px;
    }}
    .cache-table thead th {{
      background: var(--bg-surface-2);
      color: var(--ink-secondary);
      font-size: 11px; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.05em;
      padding: 10px 16px;
      text-align: left;
      border-bottom: 1px solid var(--border-default);
    }}
    .cache-table tbody td {{
      padding: 10px 16px;
      border-bottom: 1px solid var(--border-subtle);
      color: var(--ink-primary);
      vertical-align: middle;
    }}
    .cache-table tbody tr:last-child td {{ border-bottom: none; }}
    .cache-table tbody tr:hover td {{ background: var(--accent-subtle); }}
    .cell-ticker {{
      font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
      font-variant-numeric: tabular-nums;
      font-weight: 600;
      font-size: 13px;
    }}
    .cell-route {{ color: var(--ink-secondary); font-size: 12px; }}
    .cell-date {{ color: var(--ink-secondary); font-size: 12px; white-space: nowrap; }}
    .cell-value {{
      font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
      font-size: 11px;
      color: var(--ink-tertiary);
      max-width: 320px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
  </style>
</head>
<body>
  <div class="header-row">
    <div class="header-title">
      <h1>cachest</h1>
      <span class="header-subtitle">stats &amp; cache browser</span>
    </div>
    <button class="btn btn-secondary" onclick="resetStats()">Reset statistics</button>
  </div>
  <div class="grid">
    {''.join(cards_html)}
  </div>
  <div class="section-header">
    <h2>Cache Browser <span style="font-weight:400;color:var(--ink-tertiary)">({len(all_entries)} entries)</span></h2>
  </div>
  <div class="cache-controls">
    <input id="cache-filter" type="text" placeholder="Filter by ticker…" autocomplete="off" spellcheck="false">
    <button id="invalidate-btn" class="btn btn-danger" disabled onclick="invalidateFiltered()">Invalidate</button>
  </div>
  <div class="sort-group">
    <button class="btn btn-secondary active" id="sort-desc" onclick="setSortDesc(true)">Newest first</button>
    <button class="btn btn-secondary" id="sort-asc" onclick="setSortDesc(false)">Oldest first</button>
  </div>
  <div class="table-wrap">
    <table class="cache-table">
      <thead><tr><th>Ticker</th><th>Route</th><th>Cached At</th><th>Value</th></tr></thead>
      <tbody id="cache-tbody"></tbody>
    </table>
  </div>
  <script>
    async function resetStats() {{
      if (!confirm('Reset all statistics? This cannot be undone.')) return;
      await fetch('/stats/reset', {{method: 'POST'}});
      location.reload();
    }}
    async function resetCache(btn, prefix) {{
      if (!confirm('Delete all cached keys for "' + prefix + '"? This cannot be undone.')) return;
      await fetch('/stats/reset-cache/' + prefix, {{method: 'POST'}});
      location.reload();
    }}

    const CACHE_ENTRIES = {cache_entries_json};
    let sortDesc = true;
    let filterText = '';

    function getMatchingRows() {{
      return CACHE_ENTRIES.filter(e =>
        filterText && e.ticker.toLowerCase().includes(filterText.toLowerCase())
      );
    }}

    function renderCacheTable() {{
      let rows = filterText
        ? CACHE_ENTRIES.filter(e => e.ticker.toLowerCase().includes(filterText.toLowerCase()))
        : [...CACHE_ENTRIES];
      rows.sort((a, b) => sortDesc ? b.ts - a.ts : a.ts - b.ts);

      const tbody = document.getElementById('cache-tbody');
      tbody.innerHTML = rows.map(e => `
        <tr>
          <td class="cell-ticker">${{e.ticker}}</td>
          <td class="cell-route">${{e.prefix}}</td>
          <td class="cell-date">${{new Date(e.ts * 1000).toLocaleString()}}</td>
          <td class="cell-value">${{e.value}}</td>
        </tr>`).join('');

      const matching = getMatchingRows();
      const btn = document.getElementById('invalidate-btn');
      const ticker = filterText.trim().toUpperCase();
      btn.disabled = !filterText || matching.length === 0;
      btn.textContent = filterText && matching.length > 0
        ? `Invalidate "${{ticker}}" (${{matching.length}})`
        : 'Invalidate';
    }}

    function setSortDesc(desc) {{
      sortDesc = desc;
      document.getElementById('sort-desc').classList.toggle('active', desc);
      document.getElementById('sort-asc').classList.toggle('active', !desc);
      renderCacheTable();
    }}

    document.getElementById('cache-filter').addEventListener('input', e => {{
      filterText = e.target.value;
      renderCacheTable();
    }});

    async function invalidateFiltered() {{
      const matching = getMatchingRows();
      const groups = {{}};
      for (const e of matching) {{
        groups[`${{e.prefix}}/${{e.ticker}}`] = e;
      }}
      await Promise.all(
        Object.entries(groups).map(([_, e]) =>
          fetch(`/stats/invalidate-ticker/${{e.prefix}}/${{e.ticker}}`, {{method: 'POST'}})
        )
      );
      const tickers = new Set(matching.map(e => e.ticker.toLowerCase()));
      CACHE_ENTRIES.splice(0, CACHE_ENTRIES.length,
        ...CACHE_ENTRIES.filter(e => !tickers.has(e.ticker.toLowerCase()))
      );
      renderCacheTable();
    }}

    renderCacheTable();
  </script>
</body>
</html>"""


def create_app(config: Config) -> FastAPI:
    cache = RedisCache(
        host=config.redis.host,
        port=config.redis.port,
        password=config.redis.password,
        db=config.redis.db,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("cachest starting — %d route(s) registered", len(config.routes))
        for r in config.routes:
            logger.info(
                "  %s -> %s (cache_ttl: %ss, stale_ttl: %ss, fetch_interval: %ss, fetch_max_wait: %ss)",
                r.path, r.url, r.cache_ttl, r.stale_ttl, r.fetch_interval, r.fetch_max_wait,
            )
        await stats.load_from_redis(cache._client)
        stats.init(cache._client)
        yield
        await cache.close()

    app = FastAPI(lifespan=lifespan)

    _favicon = (Path(__file__).parent / "favicon.svg").read_bytes()

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(_favicon, media_type="image/svg+xml")

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/stats")

    @app.get("/stats", response_class=HTMLResponse, include_in_schema=False)
    async def stats_page():
        html = await _render_stats(config, cache)
        return HTMLResponse(html)

    @app.post("/stats/reset", include_in_schema=False)
    async def stats_reset():
        stats.reset_all(cache._client)
        return JSONResponse({"ok": True})

    @app.post("/stats/reset-cache/{prefix}", include_in_schema=False)
    async def stats_reset_cache(prefix: str):
        keys = [k async for k in cache._client.scan_iter(f"{prefix}:*")]
        if keys:
            await cache._client.delete(*keys)
        return JSONResponse({"ok": True, "deleted": len(keys)})

    @app.post("/stats/invalidate-ticker/{prefix}/{ticker}", include_in_schema=False)
    async def invalidate_ticker(prefix: str, ticker: str):
        keys = [k async for k in cache._client.scan_iter(f"{prefix}:{ticker}")]
        if keys:
            await cache._client.delete(*keys)
        return JSONResponse({"ok": True, "deleted": len(keys)})

    for route in config.routes:
        limiter = RateLimiter(interval=route.fetch_interval, max_wait=route.fetch_max_wait)
        app.add_api_route(
            route.path,
            make_handler(route, cache, limiter),
            methods=["GET"],
            response_class=PlainTextResponse,
        )

    return app


cfg = load(CONFIG_PATH)
app = create_app(cfg)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
