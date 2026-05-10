import asyncio
import time


class RateLimiter:
    def __init__(self, interval: float, max_wait: float) -> None:
        self._interval = interval
        self._max_wait = max_wait
        self._lock = asyncio.Lock()
        self._last_fetch: float = 0.0

    async def acquire(self) -> bool:
        async with self._lock:
            sleep = self._interval - (time.monotonic() - self._last_fetch)
            if sleep <= 0:
                self._last_fetch = time.monotonic()
                return True
            if sleep > self._max_wait:
                return False
            # Claim the slot now (before releasing lock) so concurrent waiters see the next-available time.
            # Note: if the subsequent fetch fails, the slot remains consumed; the next caller still waits.
            self._last_fetch = time.monotonic() + sleep  # claim the slot now

        await asyncio.sleep(sleep)  # outside the lock
        return True
