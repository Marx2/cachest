import redis.asyncio as aioredis


class CacheMiss(Exception):
    pass


class RedisCache:
    def __init__(self, host: str, port: int, password: str, db: int):
        self._client = aioredis.Redis(
            host=host, port=port, password=password or None, db=db,
            decode_responses=True,
        )

    async def get(self, key: str) -> str:
        value = await self._client.get(key)
        if value is None:
            raise CacheMiss(key)
        return value

    async def set(self, key: str, value: str, ttl: int) -> None:
        await self._client.setex(key, ttl, value)

    async def close(self) -> None:
        await self._client.aclose()
