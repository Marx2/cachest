import time
import redis.asyncio as aioredis


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

    async def set(self, key: str, value: str, stale_ttl: int) -> None:
        stamped = f"{int(time.time())}|{value}"
        await self._client.setex(key, stale_ttl, stamped)

    async def close(self) -> None:
        await self._client.aclose()
