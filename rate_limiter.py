import asyncio
import time


class RateLimiter:
    def __init__(self, interval: float, max_wait: float) -> None:
        self._interval = interval
        self._max_wait = max_wait
        self._lock = asyncio.Lock()
        # `None` means "no fetch has happened yet", which is a genuinely
        # different state from "a fetch happened at time 0". The old 0.0
        # sentinel silently assumed time.monotonic() is large at process start.
        # Where that does not hold — a container with a namespaced
        # CLOCK_MONOTONIC, i.e. any runtime using Linux time namespaces — the
        # limiter read startup as "a fetch just occurred" and rejected EVERY
        # caller with 503 for the first `interval` seconds. That is what made
        # the depth-1 route test fail in GitHub Actions while passing on a
        # developer machine: on a runner the clock is near zero at container
        # start, so a 60s interval rejected all four callers, and the suite
        # runs in the first ~12s of the container's life.
        self._last_fetch: float | None = None

    async def acquire(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            if self._last_fetch is None:
                # First caller always gets the slot, whatever the clock reads.
                self._last_fetch = now
                return True
            sleep = self._interval - (now - self._last_fetch)
            if sleep <= 0:
                self._last_fetch = now
                return True
            if sleep > self._max_wait:
                return False
            # Claim the slot now (before releasing lock) so concurrent waiters see the next-available time.
            # Note: if the subsequent fetch fails, the slot remains consumed; the next caller still waits.
            self._last_fetch = now + sleep  # claim the slot now

        await asyncio.sleep(sleep)  # outside the lock
        return True
