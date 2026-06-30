package limiter

import (
	"context"
	"sync"
	"time"
)

type Limiter struct {
	mu sync.RWMutex
	buckets map[string]*tokenBucket
	capacity float64
	refillRate float64
	idleTTL time.Duration
}


// Create a new limiter. Each key has a separate bucket.
func New(capacity int, window time.Duration, idleTTL time.Duration) *Limiter {
	return &Limiter{
		buckets: make(map[string]*tokenBucket),
		capacity: float64(capacity),
		refillRate: float64(capacity) / window.Seconds(),
		idleTTL: idleTTL,	
	}
}


// Check bucket for key
func (l *Limiter) Allow(key string, cost float64) (allowed bool, remaining int, limit int, retryAfter time.Duration) {
	b := l.getOrCreateBucket(key)
	ok, rem, retry := b.allow(cost)
	return ok, int(rem), int(l.capacity), retry
}


func (l *Limiter) getOrCreateBucket(key string) *tokenBucket {
	l.mu.RLock()
	b, ok := l.buckets[key]
	l.mu.RUnlock()
	if ok {
		return b
	}

	l.mu.Lock()
	defer l.mu.Unlock()

	if b, ok = l.buckets[key]; ok {
		return b
	}

	b = newTokenBucket(l.capacity, l.refillRate)
	l.buckets[key] = b
	return b
}


func (l *Limiter) StartCleanup(ctx context.Context, interval time.Duration) {
	go func() {
		ticket := time.NewTicker(interval)
		defer ticket.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticket.C:
				l.evictIdle()
			}
		}
	}()
}

func (l *Limiter) evictIdle() {
	cutoff := time.Now().Add(-l.idleTTL)

	l.mu.RLock()
	stale := make([]string, 0)
	for key, b := range l.buckets {
		if b.idleSince(cutoff) {
			stale = append(stale, key)
		}
	}
	l.mu.RUnlock()

	if len(stale) == 0 {
		return
	}

	l.mu.Lock()
	defer l.mu.Unlock()
	for _, key := range stale {
		if b, ok := l.buckets[key]; ok && b.idleSince(cutoff) {
			delete(l.buckets, key)
		}
	}
}

func (l *Limiter) Len() int {
	l.mu.RLock()
	defer l.mu.RUnlock()
	return len(l.buckets)
}