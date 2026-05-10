import httpx
from bs4 import BeautifulSoup
from config import ExtractConfig


class UpstreamError(Exception):
    def __init__(self, url: str, status_code: int):
        self.url = url
        self.status_code = status_code
        super().__init__(f"upstream {url!r} returned HTTP {status_code}")


# Keep as alias so any existing imports don't break during transition
RateLimitedError = UpstreamError


async def fetch(url: str, extract: ExtractConfig) -> str:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url)

    if resp.status_code in (403, 429, 502):
        raise UpstreamError(url, resp.status_code)
    resp.raise_for_status()

    if not extract.selector:
        return resp.text.strip()

    return _extract_from_html(resp.text, extract)


def _extract_from_html(html: str, ext: ExtractConfig) -> str:
    soup = BeautifulSoup(html, "lxml")
    for row in soup.select(ext.selector):
        dt = row.find("dt")
        if dt and dt.get_text(strip=True) == ext.label:
            target = row.find(ext.field)
            if target:
                return target.get_text(strip=True)
    raise ValueError(f"label {ext.label!r} not found via selector {ext.selector!r}")
