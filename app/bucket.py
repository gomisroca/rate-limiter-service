"""
Token bucket implementation.

FastAPI route handlers are async def, so many asyncio coroutines interleaving on a single threat, not OS threads running in parallel like in Go's goroutines.
We use asyncio.Lock as it is the idiomatic equivalent to Go's mutex.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

@dataclass
class AllowResult:
    allowed: bool
    remaining: int
    retry_after_seconds: float

class TokenBucket:
    """One bucket per client key."""

    __slots__ = ("_lock", "tokens", "capacity", "refill_rate", "last_refill", "last_access")

    def __init__(self, capacity: int, refill_rate: float) -> None:
        now = time.monotonic()
        self._lock = asyncio.Lock()
        self.tokens = capacity
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.last_refill = now
        self.last_access = now

    async def allow(self, cost: float) -> AllowResult:
        """Refill based on elapsed time, then attempt to consume 'cost' tokens."""

        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_access
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now
            self.last_access = now

            if self.tokens >= cost:
                self.tokens -= cost
                return AllowResult(allowed=True, remaining=self.tokens, retry_after_seconds=0.0)
            
            deficit = cost - self.tokens
            retry_after = deficit / self.refill_rate
            return AllowResult(allowed=False, remaining=self.tokens, retry_after_seconds=retry_after)
        
    async def idle_since(self, cutoff: float) -> bool:
        """Report if the bucket has been idle since cutoff."""
        async with self._lock:
            return self.last_access < cutoff