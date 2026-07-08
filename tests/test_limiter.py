"""
Direct translation of internal/limiter/limiter_test.go's test cases, plus one Py-specific concurrency test.
"""

from __future__ import annotations
import asyncio

from app.limiter import Limiter

async def test_basic_burst_then_deny():
    limiter = Limiter(capacity=5, window_seconds=1, idle_ttl_seconds=60)

    for i in range(5): # Burst 5 requests, filling the limiter's bucket capacity
        result = await limiter.allow("client-a", 1)
        assert result.allowed, f"Request {i}: expected allowed, got denied"
        assert result.limit == 5
        assert result.remaining == 5 - (i + 1)

    result = await limiter.allow("client-a", 1) # Launch one more request, which should overflow the bucket
    assert not result.allowed, f"6th request within the same window should be denied"
    assert result.retry_after_seconds > 0 # The user should have a cooldown before being allowed again
    
async def test_different_keys_are_independent():
    limiter = Limiter(capacity=1, window_seconds=60, idle_ttl_seconds=60)

    assert (await limiter.allow("client-a", 1)).allowed
    assert not (await limiter.allow("client-a", 1)).allowed # Should be denied, since the "client-a" bucket is full
    assert (await limiter.allow("client-b", 1)).allowed, "client-b should have its own independent bucket"

async def test_refills_over_time():
    limiter = Limiter(capacity=2, window_seconds=0.1, idle_ttl_seconds=60) # 2 tokens, full refill every 0.1s -> ~20 tokens/s

    assert (await limiter.allow("client-a", 1)).allowed
    assert (await limiter.allow("client-a", 1)).allowed
    assert not (await limiter.allow("client-a", 1)).allowed # Should overflow the bucket

    await asyncio.sleep(0.11) # Wait for full refill period

    assert (await limiter.allow("client-a", 1)).allowed, "Expected request to be allowed after refill period"

async def test_cost_greater_than_one():
    limiter = Limiter(capacity=10, window_seconds=1, idle_ttl_seconds=60)

    result = await limiter.allow("client-a", 7)
    assert result.allowed and result.remaining == 3


    result = await limiter.allow("client-a", 4)
    assert not result.allowed, "Expected request costing more than remaining tokens to be denied"

async def test_evict_idle():
    limiter = Limiter(capacity=5, window_seconds=1, idle_ttl_seconds=0.05)
    await limiter.allow("stale-client", 1)
    assert len(limiter) == 1

    await asyncio.sleep(0.06)
    await limiter.evict_idle()

    assert len(limiter) == 0, "Expected idle bucket to be evicted after idle TTL period"

async def test_evict_idle_does_not_evict_active_keys():
    limiter = Limiter(capacity=5, window_seconds=1, idle_ttl_seconds=0.05)

    await limiter.allow("active-client", 1)

    await asyncio.sleep(0.03)

    await limiter.allow("active-client", 1)

    await asyncio.sleep(0.03)
    await limiter.evict_idle()

    assert len(limiter) == 1, "Expected active bucket to be kept after idle TTL period"

async def test_start_cleanup_runs_in_background():
    limiter = Limiter(capacity=5, window_seconds=1, idle_ttl_seconds=0.01)
    await limiter.allow("client-a", 1)

    limiter.start_cleanup(interval_seconds=0.01)
    await asyncio.sleep(0.05) # Wait for the cleanup loop to run at least once

    assert len(limiter) == 0, "Expected background cleanup to have evicted the idle bucket"
    await limiter.stop_cleanup()

async def test_concurrent_access_enforces_capacity_exactly():
    """The asyncio analog of TestAllow_ConcurrentAccess in the Go suite:
    hammer a single key from many coroutines at once via asyncio.gather and
    assert exactly 'capacity' get through, no more, no less."""

    capacity = 100
    coroutine_count = 500 # 500 requests against 100 capacity

    limiter = Limiter(capacity=capacity, window_seconds=3600, idle_ttl_seconds=60)

    results = await asyncio.gather(*[limiter.allow("shared-key", 1) for _ in range(coroutine_count)])
    allowed_count = sum(1 for r in results if r.allowed)

    assert allowed_count == capacity, (f"Expected exactly {capacity} allowed requests out of {coroutine_count}, got {allowed_count}")

async def test_concurrent_different_keys_creates_buckets_safely():
    """Exercises the bucket-creation race path: many coroutines creating many distinct keys at once."""

    limiter = Limiter(capacity=10, window_seconds=3600, idle_ttl_seconds=60)

    keys = [f"key-{i % 26}" for i in range(100)]
    await asyncio.gather(*[limiter.allow(k, 1) for k in keys])

    assert len(limiter) == 26, f"Expected 26 distinct buckets, got {len(limiter)}"