"""Cache-key construction and the patterns that go with it.

A cache key is derived from a route's path template plus its declared query params:

    /dy/{ticker}                 + {"ticker": "AAPL"}
        -> "dy:AAPL"
    /ohlcv/{ticker}  query [start, end] + {"ticker": "AAPL", ...}
        -> "ohlcv:AAPL:2025-01-01:2026-01-01"
    /calendar/earnings
        -> "calendar:earnings"

Segments are joined with ":" and query values are appended in declared order, so two
routes never share a key even when they share a leading path segment
("/ohlcv/{ticker}" and "/ohlcv/fund/{ticker}" are disjoint). Values are
percent-encoded on the way in, which is what keeps a ":" inside a ticker from
forging a different route's key.
"""

import re

from urllib.parse import quote

# Separator between key segments. Path params and query values are percent-encoded
# before they become segments, so neither can contain a raw ":".
SEPARATOR = ":"

# A single key segment: anything but the separator.
_SEGMENT = r"[^:]+"

# Keys we generate only ever contain [A-Za-z0-9._:-]. Rejecting everything else before a
# key reaches SCAN/DEL means a caller-supplied value can never act as a wildcard.
SAFE_KEY = re.compile(r"^[A-Za-z0-9._:-]+$")

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def safe_key(key: str) -> str:
    """Validate a key or key fragment before it is used in a Redis pattern or DEL."""
    if not SAFE_KEY.match(key):
        raise ValueError(f"unsafe cache key: {key!r}")
    return key


def path_params_of(path_template: str) -> list[str]:
    """Placeholder names in a route path, in order: "/a/{x}/b/{y}" -> ["x", "y"]."""
    return _PLACEHOLDER.findall(path_template)


def cache_key(
    path_template: str,
    path_params: dict[str, str] | None = None,
    query_values: dict[str, str] | None = None,
) -> str:
    """Build the Redis key for a route + request."""
    key = path_template
    for k, v in (path_params or {}).items():
        key = key.replace("{" + k + "}", quote(str(v), safe=""))
    segments = [key.strip("/").replace("/", SEPARATOR)]
    segments.extend(quote(str(v), safe="") for v in (query_values or {}).values())
    return SEPARATOR.join(segments)


def key_segments(path_template: str) -> list[str]:
    """Path template split into segments, e.g. "/ohlcv/fund/{ticker}" ->
    ["ohlcv", "fund", "{ticker}"]."""
    return [s for s in path_template.strip("/").split("/") if s]


def key_pattern(
    path_template: str, query_params: list[str] | None = None
) -> re.Pattern[str]:
    """Compiled pattern matching exactly the keys a route owns.

    The stats page uses this to attribute each key to a single route instead of
    grouping by first path segment, which merges sibling routes such as
    "/ohlcv/{ticker}" and "/ohlcv/fund/{ticker}".
    """
    body = SEPARATOR.join(
        _SEGMENT if _PLACEHOLDER.fullmatch(s) else re.escape(s)
        for s in key_segments(path_template)
    )
    # One trailing segment per declared query param.
    tail = f"(?:{SEPARATOR}{_SEGMENT})" * len(query_params or [])
    return re.compile(f"^{body}{tail}$")


def key_prefix(path_template: str) -> str:
    """First path segment — the family a route belongs to, used for bulk flushes."""
    return path_template.lstrip("/").split("/")[0]


def key_label(path_template: str, key: str) -> str:
    """Short human label for a cache key.

    The path param identifies *what* was cached ("AAPL"), so that is what the stats
    table shows. For routes without a path param the query values are the only
    distinguishing part, so those are shown instead.
    """
    segments = key.split(SEPARATOR)
    template_segments = key_segments(path_template)
    for i, s in enumerate(template_segments):
        if _PLACEHOLDER.fullmatch(s):
            return segments[i] if i < len(segments) else key
    return SEPARATOR.join(segments[len(template_segments):]) or key
