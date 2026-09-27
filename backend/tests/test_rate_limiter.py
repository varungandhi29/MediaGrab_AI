import pytest
import asyncio
from app.security.rate_limiter import SlidingWindowRateLimiter, ConcurrentJobTracker


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=2, name="test")
    ip = "192.0.2.100"

    # First 3 should succeed
    allowed1, rem1, _ = await limiter.is_allowed(ip)
    allowed2, rem2, _ = await limiter.is_allowed(ip)
    allowed3, rem3, _ = await limiter.is_allowed(ip)

    assert allowed1 is True and rem1 == 2
    assert allowed2 is True and rem2 == 1
    assert allowed3 is True and rem3 == 0

    # 4th should be rejected
    allowed4, rem4, retry_after = await limiter.is_allowed(ip)
    assert allowed4 is False
    assert rem4 == 0
    assert retry_after >= 1

    # Wait for window to slide out
    await asyncio.sleep(2.1)
    allowed5, rem5, _ = await limiter.is_allowed(ip)
    assert allowed5 is True
    assert rem5 == 2


@pytest.mark.asyncio
async def test_concurrent_jobs_tracker():
    tracker = ConcurrentJobTracker(max_concurrent=2)
    ip = "198.51.100.5"

    assert await tracker.acquire(ip) is True
    assert await tracker.acquire(ip) is True
    # 3rd should fail
    assert await tracker.acquire(ip) is False

    # Release one
    await tracker.release(ip)
    # Should now succeed
    assert await tracker.acquire(ip) is True
    assert await tracker.acquire(ip) is False

    await tracker.release(ip)
    await tracker.release(ip)
    assert await tracker.get_active_count(ip) == 0
