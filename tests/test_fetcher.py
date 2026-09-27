import json

import httpx
import pytest
import respx

from config import ExtractConfig
from fetcher import (
    ExtractionError,
    RateLimitedError,
    UpstreamError,
    build_url,
    fetch,
)

EXTRACT = ExtractConfig(selector="dl .row", label="Yield", field="dd")


# --- URL building ----------------------------------------------------------


def test_build_url_substitutes_path_params():
    assert build_url("http://up/{ticker}", {"ticker": "AAPL"}) == "http://up/AAPL"


def test_build_url_substitutes_query_values():
    url = build_url(
        "http://up/{ticker}?statement={statement}&period={period}",
        {"ticker": "AAPL"},
        "",
        {"statement": "cash", "period": "quarter"},
    )
    assert url == "http://up/AAPL?statement=cash&period=quarter"


def test_build_url_injects_api_key():
    url = build_url("http://up/{ticker}?apikey={api_key}", {"ticker": "AAPL"}, "KEY123")
    assert url == "http://up/AAPL?apikey=KEY123"


def test_build_url_encodes_path_param_slashes():
    """Regression: a raw value could inject an extra query string into the upstream URL."""
    url = build_url("http://up/{ticker}", {"ticker": "AAPL?x=1&y=2"})
    assert url == "http://up/AAPL%3Fx%3D1%26y%3D2"


def test_build_url_encodes_path_traversal():
    assert build_url("http://up/{ticker}", {"ticker": "../../etc"}) == "http://up/..%2F..%2Fetc"


def test_build_url_encodes_query_value_separators():
    url = build_url("http://up/{t}?start={start}", {"t": "AAPL"}, "", {"start": "a&b=c"})
    assert url == "http://up/AAPL?start=a%26b%3Dc"


def test_build_url_encodes_api_key():
    assert build_url("http://up?apikey={api_key}", {}, "a b&c") == "http://up?apikey=a%20b%26c"


# --- upstream status handling ----------------------------------------------


@respx.mock
@pytest.mark.parametrize("status", [403, 429, 502])
async def test_throttle_statuses_raise_rate_limited(status):
    respx.get("http://up/x").mock(return_value=httpx.Response(status))
    with pytest.raises(RateLimitedError) as exc:
        await fetch("http://up/x", ExtractConfig())
    assert exc.value.status_code == status


@respx.mock
async def test_rate_limited_is_an_upstream_error():
    """main.py catches UpstreamError, so the subclass must stay catchable as one."""
    respx.get("http://up/x").mock(return_value=httpx.Response(429))
    with pytest.raises(UpstreamError):
        await fetch("http://up/x", ExtractConfig())


@respx.mock
async def test_404_raises_upstream_error():
    respx.get("http://up/x").mock(return_value=httpx.Response(404))
    with pytest.raises(UpstreamError) as exc:
        await fetch("http://up/x", ExtractConfig())
    assert exc.value.status_code == 404


@respx.mock
async def test_server_error_raises_upstream_error():
    respx.get("http://up/x").mock(return_value=httpx.Response(500))
    with pytest.raises(UpstreamError) as exc:
        await fetch("http://up/x", ExtractConfig())
    assert exc.value.status_code == 500


@respx.mock
async def test_timeout_is_reported_as_504():
    """A transport failure used to surface as a bare 502 with no stale fallback."""
    respx.get("http://up/x").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamError) as exc:
        await fetch("http://up/x", ExtractConfig())
    assert exc.value.status_code == 504


@respx.mock
async def test_connect_error_is_reported_as_502():
    respx.get("http://up/x").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(UpstreamError) as exc:
        await fetch("http://up/x", ExtractConfig())
    assert exc.value.status_code == 502


# --- body handling ---------------------------------------------------------


@respx.mock
async def test_passthrough_returns_stripped_text():
    respx.get("http://up/x").mock(return_value=httpx.Response(200, text="  42.5%\n"))
    assert await fetch("http://up/x", ExtractConfig()) == "42.5%"


@respx.mock
async def test_json_field_is_extracted():
    respx.get("http://up/x").mock(
        return_value=httpx.Response(200, json={"DividendYield": "0.0525"})
    )
    result = await fetch("http://up/x", ExtractConfig(), json_field="DividendYield")
    assert result == "0.0525"


@respx.mock
async def test_json_passthrough_preserves_provider_extras():
    """§52.5 — the 52 provider extras must survive the passthrough untouched:
    dividendmax history rows (currency/dividend_type/declaration_date) and
    biznesradar calendar rows (status)."""
    payload = json.dumps([
        {
            "date": "2026-08-10", "amount": "0.2700", "payment_date": "2026-08-13",
            "declaration_date": "2026-07-30", "currency": "USD",
            "dividend_type": "Quarterly", "status": "Paid",
        },
        {
            "ex_dividend_date": "2026-09-28", "payment_date": "2026-12-30",
            "amount": "0.22", "symbol": "NTT", "status": "uchwalona",
        },
    ])
    respx.get("http://up/dividends/AAPL").mock(return_value=httpx.Response(200, text=payload))
    assert await fetch("http://up/dividends/AAPL", ExtractConfig()) == payload


@respx.mock
async def test_html_extraction():
    html = """
    <dl><div class="row"><dt>Yield</dt><dd>4.12%</dd></div>
        <div class="row"><dt>Payout</dt><dd>2.00%</dd></div></dl>
    """
    respx.get("http://up/x").mock(return_value=httpx.Response(200, text=html))
    assert await fetch("http://up/x", EXTRACT) == "4.12%"


# --- extraction errors are their own class ---------------------------------


@respx.mock
async def test_missing_json_field_is_an_extraction_error():
    """A renamed json_field is an operator problem — not a transient outage, so it must
    not be answered with stale data."""
    respx.get("http://up/x").mock(return_value=httpx.Response(200, json={"Other": 1}))
    with pytest.raises(ExtractionError, match="DividendYield"):
        await fetch("http://up/x", ExtractConfig(), json_field="DividendYield")


@respx.mock
async def test_non_json_body_for_a_json_field_is_an_extraction_error():
    respx.get("http://up/x").mock(return_value=httpx.Response(200, text="<html>nope</html>"))
    with pytest.raises(ExtractionError, match="not valid JSON"):
        await fetch("http://up/x", ExtractConfig(), json_field="DividendYield")


@respx.mock
async def test_selector_no_longer_matching_is_an_extraction_error():
    """Upstream DOM drift must be distinguishable from a flaky network."""
    respx.get("http://up/x").mock(return_value=httpx.Response(200, text="<html>redesigned</html>"))
    with pytest.raises(ExtractionError, match="not found"):
        await fetch("http://up/x", EXTRACT)


@respx.mock
async def test_extraction_error_is_not_an_upstream_error():
    """main.py treats the two differently: stale for one, hard failure for the other."""
    respx.get("http://up/x").mock(return_value=httpx.Response(200, text="<html/>"))
    with pytest.raises(ExtractionError):
        try:
            await fetch("http://up/x", EXTRACT)
        except UpstreamError as e:  # pragma: no cover - guards the contract
            pytest.fail(f"extraction failure surfaced as UpstreamError: {e}")


# --- client and timeout wiring --------------------------------------------


@respx.mock
async def test_uses_the_supplied_shared_client():
    """One pooled client is shared app-wide; fetch must not build or close its own."""
    respx.get("http://up/x").mock(return_value=httpx.Response(200, text="ok"))
    async with httpx.AsyncClient() as shared:
        assert await fetch("http://up/x", ExtractConfig(), client=shared) == "ok"
        assert shared.is_closed is False, "the shared client must be left open for reuse"


@respx.mock
async def test_timeout_is_applied_per_request():
    """A slow OHLCV scrape and a fast quote share one client, so the timeout has to be
    a request argument rather than a client default."""
    seen = {}
    async with httpx.AsyncClient() as shared:
        original = shared.get

        async def spy(url, **kwargs):
            seen.update(kwargs)
            return await original(url, **kwargs)

        shared.get = spy
        respx.get("http://up/x").mock(return_value=httpx.Response(200, text="ok"))
        await fetch("http://up/x", ExtractConfig(), timeout=120.0, client=shared)
    assert seen["timeout"] == 120.0


def test_default_timeout_is_15():
    import inspect
    assert inspect.signature(fetch).parameters["timeout"].default == 15.0
