import time

import redis.asyncio as aioredis

from keys import safe_key

# MGET is a single command; large batches block the Redis event loop, so reads are
# chunked. 1000 values is well inside a normal reply-buffer budget.
SCAN_BATCH = 1000

# Stored values are "<unix-ts>|<body>". The age a dashboard needs is in the first 10
# bytes, so heads are read instead of whole values: the production keyspace is ~50 MB
# across ~1100 keys with a 1.1 MB maximum, and reading it whole OOM-killed the pod.
TIMESTAMP_CHARS = 15


class CacheMiss(Exception):
    pass


class CacheStale(Exception):
    def __init__(self, key: str, value: str):
        self.value = value
        super().__init__(key)


class RedisCache:
    def __init__(self, host: str, port: int, password: str, db: int):
        self._client = aioredis.Redis(
            host=host, port=port, password=password or None, db=db,
            decode_responses=True,
        )

    async def ping(self) -> bool:
        """§64.2 — is the cache actually reachable right now?

        For the readiness probe. Deliberately a real round-trip rather than
        trusting a connection flag: a pooled connection can look established
        while the server has gone away, and readiness is the only honest place
        to drop this pod from rotation.
        """
        try:
            return bool(await self._client.ping())
        except Exception:
            return False

    async def get(self, key: str, cache_ttl: int) -> str:
        """Return the value, or raise CacheMiss (absent/unparseable) / CacheStale (too old)."""
        raw = await self._client.get(key)
        if raw is None:
            raise CacheMiss(key)
        try:
            ts_str, value = raw.split("|", 1)
            age = int(time.time()) - int(ts_str)
        except (ValueError, IndexError):
            raise CacheMiss(key)
        if age > cache_ttl:
            raise CacheStale(key, value)
        return value

    async def get_fresh_or_stale(self, key: str, cache_ttl: int) -> str | None:
        """Value regardless of age, or None when the key is absent.

        For stale fallback: a value that is merely old is still worth serving, an
        absent key is not. Collapses the CacheStale/CacheMiss pair that every
        fallback path used to spell out by hand.
        """
        try:
            return await self.get(key, cache_ttl)
        except CacheStale as e:
            return e.value
        except CacheMiss:
            return None

    async def set(self, key: str, value: str, stale_ttl: int) -> None:
        stamped = f"{int(time.time())}|{value}"
        await self._client.setex(key, stale_ttl, stamped)

    async def incr_with_ttl(self, key: str, ttl: int) -> int:
        """INCR, applying the TTL only when the key is created.

        A crash between INCR and EXPIRE would leave a key with no TTL, so the window
        is kept as small as Redis allows: one INCR, and one EXPIRE only on creation.
        """
        count = int(await self._client.incr(key))
        if count == 1:
            await self._client.expire(key, ttl)
        return count

    async def scan_keys(self, pattern: str) -> list[str]:
        """All keys matching a glob pattern, fully drained."""
        return [k async for k in self._client.scan_iter(pattern)]

    async def read_heads(self, keys: list[str], batch: int = SCAN_BATCH) -> dict[str, str]:
        """Return {key: value_head} for the given keys, reading only the first bytes.

        Enough to place a key in an age histogram without pulling the cached body,
        which is what made /stats OOM. Keys of the wrong type are skipped rather than
        raised: cachest's own ``stats:`` counters are hashes in this same database, and
        a dashboard must not 500 because of its own bookkeeping.
        """
        return await self._read_ranges(keys, 0, TIMESTAMP_CHARS - 1, batch)

    async def read_previews(
        self, keys: list[str], length: int = 80, batch: int = SCAN_BATCH
    ) -> dict[str, str]:
        """Return {key: body-preview} for the given keys, reading only a prefix."""
        raw = await self._read_ranges(keys, 0, TIMESTAMP_CHARS + length - 1, batch)
        return {k: v.split("|", 1)[-1][:length] for k, v in raw.items()}

    async def _read_ranges(
        self, keys: list[str], start: int, end: int, batch: int
    ) -> dict[str, str]:
        out: dict[str, str] = {}
        for i in range(0, len(keys), batch):
            chunk = keys[i:i + batch]
            pipe = self._client.pipeline(transaction=False)
            for key in chunk:
                pipe.getrange(key, start, end)
            for key, value in zip(chunk, await pipe.execute(raise_on_error=False)):
                if isinstance(value, str) and value:
                    out[key] = value
        return out

    async def scan_all_with_values(self) -> list[tuple[str, str]]:
        """Return [(key, raw_value)] for every key in the database.

        Convenience for tests and small keyspaces. Prefer iter_all_with_values() for
        anything user-facing: this materialises the whole keyspace, and a single cached
        OHLCV response can be hundreds of KB.
        """
        return [pair async for pair in self.iter_all_with_values()]

    async def iter_all_with_values(self, batch: int = SCAN_BATCH):
        """Yield (key, raw_value) across the whole database in chunks.

        The caller sees at most `batch` full values at a time, so a page that walks the
        keyspace (the stats dashboard) is bounded in memory regardless of keyspace
        size. Reading it in one list is what OOM-killed the pod against a 128Mi limit.
        """
        keys = await self.scan_keys("*")
        for start in range(0, len(keys), batch):
            chunk = keys[start:start + batch]
            for key, value in zip(chunk, await self._client.mget(*chunk)):
                if value is not None:
                    yield key, value

    async def delete_pattern(self, pattern: str) -> int:
        """Delete every key matching a glob pattern. Returns the number deleted."""
        keys = await self.scan_keys(pattern)
        if not keys:
            return 0
        for start in range(0, len(keys), SCAN_BATCH):
            await self._client.delete(*keys[start:start + SCAN_BATCH])
        return len(keys)

    async def delete_keys(self, keys: list[str]) -> int:
        """Delete exact keys. Rejects anything outside our own key charset so a
        caller-supplied value can never turn into a wildcard pattern."""
        if not keys:
            return 0
        for k in keys:
            safe_key(k)
        for start in range(0, len(keys), SCAN_BATCH):
            await self._client.delete(*keys[start:start + SCAN_BATCH])
        return len(keys)

    async def hgetall(self, key: str) -> dict[str, str]:
        return await self._client.hgetall(key)

    async def hincrby_fields(self, key: str, increments: dict[str, int]) -> None:
        """Apply several HINCRBYs to one hash in a single round trip."""
        if not increments:
            return
        pipe = self._client.pipeline(transaction=False)
        for field, amount in increments.items():
            pipe.hincrby(key, field, amount)
        await pipe.execute()

    async def close(self) -> None:
        await self._client.aclose()
