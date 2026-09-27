import json

from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from config import ExtractConfig

# Upstream statuses that mean "we are being throttled" rather than "the answer is bad".
# 502 is included because a scrape-backed upstream reports a gateway error under load.
THROTTLE_STATUSES = frozenset({403, 429, 502})


def build_url(
    template: str,
    path_params: dict[str, str] | None = None,
    api_key: str = "",
    query_values: dict[str, str] | None = None,
) -> str:
    """Fill a URL template.

    Path params and query values are percent-encoded, so a value can never introduce a
    new query string, traverse a path, or reach the upstream host as anything other than
    the single segment it was meant to be. The same encoding feeds cache_key(), which is
    what keeps "AAPL/B" and "AAPL:B" from colliding onto one cache entry.
    """
    url = template
    for k, v in (path_params or {}).items():
        url = url.replace("{" + k + "}", quote(str(v), safe=""))
    for k, v in (query_values or {}).items():
        url = url.replace("{" + k + "}", quote(str(v), safe=""))
    return url.replace("{api_key}", quote(api_key, safe=""))



class UpstreamError(Exception):
    def __init__(self, url: str, status_code: int):
        self.url = url
        self.status_code = status_code
        super().__init__(f"upstream {url!r} returned HTTP {status_code}")


class RateLimitedError(UpstreamError):
    pass


class ExtractionError(Exception):
    """The response arrived but could not be turned into a value.

    Kept distinct from UpstreamError because the fix is different: an upstream DOM
    change or a missing json_field is an operator problem, not a transient outage, so
    it must not be answered with stale data — the stale value would be indistinguishable
    from a correct one.
    """


async def fetch(
    url: str,
    extract: ExtractConfig,
    json_field: str = "",
    timeout: float = 15.0,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Fetch a URL and reduce it to a string.

    `client` is shared app-wide so upstream connections are pooled and reused. When it
    is None a throwaway client is used, which keeps this callable in isolation (tests).
    Timeout is per request, not per client, so a slow OHLCV scrape and a fast quote
    can share one pool.
    """
    if client is not None:
        return await _fetch_with(client, url, extract, json_field, timeout)
    async with httpx.AsyncClient(follow_redirects=True) as own:
        return await _fetch_with(own, url, extract, json_field, timeout)


async def _fetch_with(
    client: httpx.AsyncClient,
    url: str,
    extract: ExtractConfig,
    json_field: str,
    timeout: float,
) -> str:
    try:
        resp = await client.get(url, timeout=timeout)
    except httpx.TimeoutException as e:
        raise UpstreamError(url, 504) from e
    except httpx.HTTPError as e:
        raise UpstreamError(url, 502) from e

    if resp.status_code in THROTTLE_STATUSES:
        raise RateLimitedError(url, resp.status_code)
    if resp.is_client_error or resp.is_server_error:
        # Includes 404 ("no data for key") so main can pass it through.
        raise UpstreamError(url, resp.status_code)

    if json_field:
        return _extract_json(resp.text, json_field, url)

    if not extract.selector:
        return resp.text.strip()

    return _extract_from_html(resp.text, extract, url)


def _extract_json(text: str, json_field: str, url: str) -> str:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ExtractionError(f"{url}: response is not valid JSON: {e}") from e
    try:
        return str(data[json_field])
    except (KeyError, IndexError, TypeError) as e:
        raise ExtractionError(f"{url}: JSON has no {json_field!r} field") from e


def _extract_from_html(html: str, ext: ExtractConfig, url: str = "") -> str:
    soup = BeautifulSoup(html, "lxml")
    for row in soup.select(ext.selector):
        dt = row.find("dt")
        if dt and dt.get_text(strip=True) == ext.label:
            target = row.find(ext.field)
            if target:
                return target.get_text(strip=True)
    where = f" in {url}" if url else ""
    raise ExtractionError(
        f"label {ext.label!r} not found{where} via selector {ext.selector!r}"
    )
