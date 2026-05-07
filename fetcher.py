import httpx
from bs4 import BeautifulSoup
from config import ExtractConfig


class RateLimitedError(Exception):
    def __init__(self, url: str):
        self.url = url
        super().__init__(f"rate limited by {url!r} (HTTP 429)")


async def fetch(url: str, extract: ExtractConfig) -> str:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(url)

    if resp.status_code == 429:
        raise RateLimitedError(url)
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
