import pytest
import httpx
import respx
from unittest.mock import patch, AsyncMock
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


@pytest.mark.asyncio
@respx.mock
async def test_fetch_custom_timeout_is_used(monkeypatch):
    """fetch() passes the timeout arg to httpx.AsyncClient."""
    captured = {}

    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    respx.get("http://example.com/test").mock(return_value=httpx.Response(200, text="ok"))
    await fetch("http://example.com/test", ExtractConfig(), timeout=120.0)
    assert captured["timeout"] == 120.0


@pytest.mark.asyncio
async def test_fetch_timeout_default_is_15():
    """Default timeout is 15s (no regression)."""
    import inspect
    sig = inspect.signature(fetch)
    assert sig.parameters["timeout"].default == 15.0
