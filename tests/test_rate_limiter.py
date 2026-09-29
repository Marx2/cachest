import asyncio
import pytest
from rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_first_acquire_returns_true():
    limiter = RateLimiter(interval=2.0, max_wait=4.0)
    result = await limiter.acquire()
    assert result is True


@pytest.mark.asyncio
async def test_first_acquire_succeeds_when_the_clock_starts_near_zero(monkeypatch):
    """The bug that made CI red for two days.

    `_last_fetch` used to be initialised to 0.0, which reads as "a fetch happened
    at time zero" rather than "no fetch yet". That silently assumes
    time.monotonic() is already large when the process starts. It is not
    everywhere: under a namespaced CLOCK_MONOTONIC the clock starts at ~0, so a
    60s interval computed a 57s wait, exceeded max_wait, and rejected EVERY
    caller with 503 for the first `interval` seconds of process life.

    GitHub Actions runs the suite in the first ~12s of a container's life, so
    the shipped /corp-bond/catalogue route (fetch_interval 60, fetch_max_wait 4)
    rejected all four concurrent callers. A developer machine has host-uptime
    monotonic values, so it passed there — the pre-existing
    test_first_acquire_returns_true was asserting the right thing and passing by
    accident of the platform.

    Pinning the clock to a small value is what makes this a real test.
    """
    clock = [3.0]  # a container 3 seconds into its life

    def fake_monotonic() -> float:
        return clock[0]

    monkeypatch.setattr("rate_limiter.time.monotonic", fake_monotonic)

    limiter = RateLimiter(interval=60.0, max_wait=4.0)
    assert await limiter.acquire() is True, (
        "the first caller must always get the slot, whatever the clock reads"
    )

    # And the limiter must then behave normally: a second caller inside the
    # interval is refused because the wait exceeds max_wait.
    clock[0] = 3.5
    assert await limiter.acquire() is False

    # Once the interval has genuinely elapsed it serves again.
    clock[0] = 3.5 + 61.0
    assert await limiter.acquire() is True


@pytest.mark.asyncio
async def test_immediate_second_acquire_waits_and_returns_true():
    """Second call within interval should sleep and return True if sleep <= max_wait."""
    limiter = RateLimiter(interval=0.1, max_wait=1.0)
    await limiter.acquire()
    start = asyncio.get_running_loop().time()
    result = await limiter.acquire()
    elapsed = asyncio.get_running_loop().time() - start
    assert result is True
    assert elapsed >= 0.05  # slept at least half the interval


@pytest.mark.asyncio
async def test_acquire_returns_false_when_wait_exceeds_max():
    """If required sleep > max_wait, acquire returns False immediately."""
    limiter = RateLimiter(interval=10.0, max_wait=0.5)
    await limiter.acquire()  # set last_fetch
    start = asyncio.get_running_loop().time()
    result = await limiter.acquire()
    elapsed = asyncio.get_running_loop().time() - start
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


@pytest.mark.asyncio
async def test_concurrent_callers_get_distinct_slots():
    """Two concurrent callers should both eventually return True, spaced by the interval."""
    limiter = RateLimiter(interval=0.1, max_wait=1.0)
    results = []

    async def call():
        result = await limiter.acquire()
        results.append(result)

    start = asyncio.get_running_loop().time()
    await asyncio.gather(call(), call())
    elapsed = asyncio.get_running_loop().time() - start

    assert results == [True, True]
    assert elapsed >= 0.05  # second caller had to wait
