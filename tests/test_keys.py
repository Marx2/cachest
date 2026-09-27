import pytest

from keys import (
    cache_key,
    key_label,
    key_pattern,
    key_prefix,
    path_params_of,
    safe_key,
)


# --- construction ----------------------------------------------------------


def test_cache_key_substitutes_path_param():
    assert cache_key("/dy/{ticker}", {"ticker": "AAPL"}) == "dy:AAPL"


def test_cache_key_no_path_params():
    assert cache_key("/calendar/earnings", {}) == "calendar:earnings"


def test_cache_key_appends_query_values_in_declared_order():
    key = cache_key(
        "/ohlcv/{ticker}", {"ticker": "AAPL"}, {"start": "2025-01-01", "end": "2026-01-01"}
    )
    assert key == "ohlcv:AAPL:2025-01-01:2026-01-01"


def test_cache_key_omits_leading_slash():
    assert not cache_key("/dy/{ticker}", {"ticker": "AAPL"}).startswith("/")


# --- encoding: the reason a key cannot be forged ----------------------------


def test_cache_key_percent_encodes_path_traversal():
    """A ticker must not be able to reach outside its own path segment.

    "." is an unreserved character and survives encoding; the "/" separators are what
    would create a new path, so those are what must be encoded.
    """
    key = cache_key("/up/{ticker}", {"ticker": "../../etc/passwd"})
    assert "/" not in key
    assert key == "up:..%2F..%2Fetc%2Fpasswd"


def test_cache_key_percent_encodes_separator_in_value():
    """A value containing ":" cannot masquerade as extra key segments."""
    assert cache_key("/equity/search/{query}", {"query": "a:b"}) == "equity:search:a%3Ab"


def test_distinct_values_do_not_collide():
    """The bug this guards: "AAPL/B" and "AAPL:B" must not share a cache entry."""
    slash = cache_key("/up/{ticker}", {"ticker": "AAPL/B"})
    colon = cache_key("/up/{ticker}", {"ticker": "AAPL:B"})
    assert slash != colon


def test_query_values_are_encoded_too():
    key = cache_key("/up/{t}", {"t": "X"}, {"start": "a&b=c"})
    assert key == "up:X:a%26b%3Dc"


# --- pattern / glob --------------------------------------------------------


def test_key_pattern_matches_own_key():
    pattern = key_pattern("/ohlcv/{ticker}", ["start", "end"])
    assert pattern.match(cache_key("/ohlcv/{ticker}", {"ticker": "AAPL"}, {"start": "s", "end": "e"}))


def test_key_pattern_rejects_extra_segments():
    """A query-param route must not claim a key that carries more segments."""
    pattern = key_pattern("/ohlcv/{ticker}", ["start", "end"])
    assert not pattern.match("ohlcv:AAPL:2025-01-01:2026-01-01:extra")


def test_sibling_routes_never_claim_each_others_keys():
    """The stats page attributes keys by pattern; siblings must stay disjoint."""
    equity = key_pattern("/ohlcv/{ticker}", ["start", "end"])
    fund = key_pattern("/ohlcv/fund/{ticker}", ["start", "end"])
    equity_key = cache_key("/ohlcv/{ticker}", {"ticker": "AAPL"}, {"start": "s", "end": "e"})
    fund_key = cache_key("/ohlcv/fund/{ticker}", {"ticker": "VWCE"}, {"start": "s", "end": "e"})
    assert equity.match(equity_key) and not equity.match(fund_key)
    assert fund.match(fund_key) and not fund.match(equity_key)


def test_nested_path_route_is_disjoint_from_its_parent():
    parent = key_pattern("/fundamentals/{ticker}", ["statement", "period"])
    nested = key_pattern("/fundamentals/{ticker}/mda")
    nested_key = cache_key("/fundamentals/{ticker}/mda", {"ticker": "AAPL"})
    assert nested.match(nested_key)
    assert not parent.match(nested_key)


def test_no_param_route_pattern_is_exact():
    pattern = key_pattern("/corp-bond/catalogue")
    assert pattern.match("corp-bond:catalogue")
    assert not pattern.match("corp-bond:catalogue:extra")


# --- prefix / label --------------------------------------------------------


@pytest.mark.parametrize("path,prefix", [
    ("/dy/{ticker}", "dy"),
    ("/ohlcv/fund/{ticker}", "ohlcv"),
    ("/corp-bond/catalogue", "corp-bond"),
])
def test_key_prefix(path, prefix):
    assert key_prefix(path) == prefix


def test_key_label_uses_the_path_param():
    assert key_label("/dy/{ticker}", "dy:AAPL") == "AAPL"


def test_key_label_uses_the_param_not_the_literal_segment():
    """"/ohlcv/fund/{ticker}" labels VWCE, not "fund"."""
    key = cache_key("/ohlcv/fund/{ticker}", {"ticker": "VWCE"}, {"start": "s", "end": "e"})
    assert key_label("/ohlcv/fund/{ticker}", key) == "VWCE"


def test_key_label_falls_back_to_query_values_when_no_path_param():
    key = cache_key("/calendar/earnings", {}, {"start": "2026-01-01", "end": "2026-02-01"})
    assert key_label("/calendar/earnings", key) == "2026-01-01:2026-02-01"


def test_path_params_of():
    assert path_params_of("/a/{x}/b/{y}") == ["x", "y"]
    assert path_params_of("/no/params") == []


# --- key safety ------------------------------------------------------------


@pytest.mark.parametrize("key", ["ohlcv:AAPL", "dy:AAPL", "a.b_c-d:e", "limit:FMP:2026-05-13"])
def test_safe_key_accepts_our_own_charset(key):
    assert safe_key(key) == key


@pytest.mark.parametrize("key", ["*", "ohlcv:*", "a b", "a/b", "a\nb", ""])
def test_safe_key_rejects_anything_that_could_be_a_pattern(key):
    with pytest.raises(ValueError):
        safe_key(key)
