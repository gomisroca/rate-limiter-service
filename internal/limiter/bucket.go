package limiter

import (
	"sync"
	"time"
)

// tokenBucket is a token bucket implementation
// hold 'capacity' tokens, refilling at 'refillRate' tokens per second
// each request consumes 'cost' tokens
type tokenBucket struct {
	mu sync.Mutex
	tokens float64
	capacity float64
	refillRate float64
	lastRefill time.Time
	lastAccess time.Time
}

func newTokenBucket(capacity, refillRate float64) *tokenBucket {
	now := time.Now()

	return &tokenBucket{
		tokens: capacity,
		capacity: capacity,
		refillRate: refillRate,
		lastRefill: now,
		lastAccess: now,
	}
}

// Refill bucket based on elapsed time, attemp to deduct cost tokens. If successful, returns how many tokens remain. Otherwise, returns how long until refill.
func (b *tokenBucket) allow(cost float64) (allowed bool, remaining float64, retryAfter time.Duration) {
	b.mu.Lock()
	defer b.mu.Unlock()

	now := time.Now()
	elapsed := now.Sub(b.lastRefill).Seconds()
	b.tokens = minF(b.capacity, b.tokens+b.refillRate*elapsed)
	b.lastRefill = now
	b.lastAccess = now

	if b.tokens >= cost {
		b.tokens -= cost
		return true, b.tokens, 0
	}

	deficit := cost - b.tokens
	retryAfter = time.Duration(deficit/b.refillRate * float64(time.Second))
	return false, b.tokens, retryAfter
}


// Report if bucket has been untouched since cutoff
func (b *tokenBucket) idleSince(cutoff time.Time) bool {
	b.mu.Lock()
	defer b.mu.Unlock()

	return b.lastAccess.Before(cutoff)
}

func minF(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}