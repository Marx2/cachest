import time

import redis.asyncio as aioredis

from keys import safe_key

# MGET is a single command; large batches block the Redis event loop, so reads are
# chunked. 1000 values is well inside a normal reply-buffer budget.
SCAN_BATCH = 1000


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

    async def scan_all_with_values(self) -> list[tuple[str, str]]:
        """Return [(key, raw_value)] for every key in the database.

        One SCAN pass feeds the whole stats page, which then attributes each key to a
        route. Values are read in chunks so a large keyspace cannot produce a single
        oversized MGET.
        """
        keys = await self.scan_keys("*")
        if not keys:
            return []
        pairs: list[tuple[str, str]] = []
        for start in range(0, len(keys), SCAN_BATCH):
            chunk = keys[start:start + SCAN_BATCH]
            for key, value in zip(chunk, await self._client.mget(*chunk)):
                if value is not None:
                    pairs.append((key, value))
        return pairs

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
