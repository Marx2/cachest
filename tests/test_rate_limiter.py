import asyncio
import pytest
from rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_first_acquire_returns_true():
    limiter = RateLimiter(interval=2.0, max_wait=4.0)
    result = await limiter.acquire()
    assert result is True


@pytest.mark.asyncio
async def test_immediate_second_acquire_waits_and_returns_true():
    """Second call within interval should sleep and return True if sleep <= max_wait."""
    limiter = RateLimiter(interval=0.1, max_wait=1.0)
    await limiter.acquire()
    start = asyncio.get_event_loop().time()
    result = await limiter.acquire()
    elapsed = asyncio.get_event_loop().time() - start
    assert result is True
    assert elapsed >= 0.05  # slept at least half the interval


@pytest.mark.asyncio
async def test_acquire_returns_false_when_wait_exceeds_max():
    """If required sleep > max_wait, acquire returns False immediately."""
    limiter = RateLimiter(interval=10.0, max_wait=0.5)
    await limiter.acquire()  # set last_fetch
    start = asyncio.get_event_loop().time()
    result = await limiter.acquire()
    elapsed = asyncio.get_event_loop().time() - start
    assert result is False
    assert elapsed < 1.0  # did not actually sleep the full interval


@pytest.mark.asyncio
async def test_acquire_true_after_interval_has_passed():
    """After enough time passes, acquire returns True without sleeping."""
    limiter = RateLimiter(interval=0.05, max_wait=1.0)
    await limiter.acquire()
    await asyncio.sleep(0.1)  # wait longer than interval
    result = await limiter.acquire()
    assert result is True
