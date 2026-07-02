"""
Limiter manages one TokenBucket per client, plus a background task to clean up idle buckets.
Simplified from Go's version thanks to the use of Python's dicts.
"""

from __future__ import annotations
import asyncio
from dataclasses import dataclass
import time

from app.bucket import AllowResult, TokenBucket

@dataclass
class CheckResult:
    allowed: bool
    remaining: int
    limit: int
    retry_after_seconds: float

class Limiter:
    def __init__(self, capacity: int, window_seconds: float, idle_ttl_seconds: float) -> None:
        self._buckets: dict[str, TokenBucket] = {}
        self._creation_lock = asyncio.Lock()
        self.capacity = float(capacity)
        self.refill_rate = capacity / window_seconds
        self.idle_ttl_seconds = idle_ttl_seconds
        self._cleanup_task = asyncio.Task | None = None

    async def _get_or_create_bucket(self, key: str) -> TokenBucket:
        bucket = self._buckets.get(key)
        if bucket is not None:
            return bucket
        
        # Lock only around the check and create to avoid two coroutines racing to create the same bucket.
        async with self._creation_lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(self.capacity, self.refill_rate)
                self._buckets[key] = bucket
            return bucket

    async def allow(self, key: str, cost: float = 1.0) -> CheckResult:
        bucket = await self._get_or_create_bucket(key)
        result: AllowResult = await bucket.allow(cost)
        return CheckResult(
            allowed=result.allowed,
            remaining=int(result.remaining),
            limit=int(self.capacity),
            retry_after_seconds=result.retry_after_seconds,
        )
    
    async def evict_idle(self) -> None:
        cutoff = time.monotonic() - self.idle_ttl_seconds

        stale: list[str] = []
        for key, bucket in self._buckets.items():
            if await bucket.idle_since(cutoff):
                stale.append(key)

        async with self._creation_lock:
            for key in stale:
                bucket = self._buckets.get(key)
                if bucket is not None and await bucket.idle_since(cutoff):
                    del self._buckets[key]

    async def _cleanup_loop(self, interval_seconds: float) -> None:
        try:
            while True:
                await asyncio.sleep(interval_seconds)
                await self.evict_idle()
        except asyncio.CancelledError:
            pass

    def start_cleanup(self, interval_seconds: float) -> None:
        """Launch the background eviction loop as an asyncio task."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(interval_seconds))

    async def stop_cleanup(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)

    def __len__(self) -> int:
        return len(self._buckets)