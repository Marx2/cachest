import pytest
import httpx
import respx
from fetcher import fetch, UpstreamError
from config import ExtractConfig


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_upstream_error_on_429():
    respx.get("http://example.com/test").mock(return_value=httpx.Response(429))
    with pytest.raises(UpstreamError) as exc_info:
        await fetch("http://example.com/test", ExtractConfig())
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_upstream_error_on_403():
    respx.get("http://example.com/test").mock(return_value=httpx.Response(403))
    with pytest.raises(UpstreamError) as exc_info:
        await fetch("http://example.com/test", ExtractConfig())
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_upstream_error_on_502():
    respx.get("http://example.com/test").mock(return_value=httpx.Response(502))
    with pytest.raises(UpstreamError) as exc_info:
        await fetch("http://example.com/test", ExtractConfig())
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_text_on_200():
    respx.get("http://example.com/test").mock(
        return_value=httpx.Response(200, text="42.5%")
    )
    result = await fetch("http://example.com/test", ExtractConfig())
    assert result == "42.5%"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_raises_upstream_error_on_404():
    respx.get("http://example.com/test").mock(return_value=httpx.Response(404))
    with pytest.raises(UpstreamError) as exc_info:
        await fetch("http://example.com/test", ExtractConfig())
    assert exc_info.value.status_code == 404
