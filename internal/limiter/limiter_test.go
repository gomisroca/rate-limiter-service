package limiter

import (
	"context"
	"sync"
	"testing"
	"time"
)

func TestAllow_BasicBurstThenDeny(t *testing.T) {
	l := New(5, time.Second, time.Minute) // 5 tokens, refill 5/s

	for i := range 5 {
		allowed, remaining, limit, _ := l.Allow("client-a", 1)
		if !allowed {
			t.Fatalf("Request %d: expected allowed, got denied", i)
		}
		if limit != 5 {
			t.Fatalf("Expected limit 5, got %d", limit)
		}
		if remaining != 5-(i+1) {
			t.Fatalf("Request %d: expected remaining %d, got %d", i, 5-(i+1), remaining)
		}
	}

	allowed, _, _, retryAfter := l.Allow("client-a", 1)
	if allowed {
		t.Fatalf("6th request within the same instant should be denied")
	}
	if retryAfter <= 0 {
		t.Fatalf("Expected a positive retryAfter when denied")
	}
}

func TestAllow_DifferentKeysAreIndependent(t *testing.T) {
	l := New(1, time.Second, time.Minute)
	
	if allowed, _, _, _ := l.Allow("client-a", 1); !allowed {
		t.Fatal("client-a's first request should be allowed")
	}
	if allowed, _, _, _ := l.Allow("client-a", 1); allowed {
		t.Fatal("client-a's second request should be denied (capacity 1)")
	}
	if allowed, _, _, _ := l.Allow("client-b", 1); !allowed {
		t.Fatal("client-b should have its own independent bucket")
	}
}
func TestAllow_RefillsOverTime(t *testing.T) {
	// 2 tokens, full refill every 100ms -> ~20 tokens/sec
	l := New(2, 100*time.Millisecond, time.Minute)

	if allowed, _, _, _ := l.Allow("client-a", 1); !allowed {
		t.Fatal("Expected first request allowed")
	}
	if allowed, _, _, _ := l.Allow("client-a", 1); !allowed {
		t.Fatal("Expected second request allowed (capacity 2)")
	}
	if allowed, _, _, _ := l.Allow("client-a", 1); allowed {
		t.Fatal("Expected third immediate request denied")
	}

	time.Sleep(110 * time.Millisecond) // wait for full refill

	if allowed, _, _, _ := l.Allow("client-a", 1); !allowed {
		t.Fatal("Expected fourth request allowed")
	}
}

func TestAllow_CostGreaterThanOne(t *testing.T) {
	l := New(10, time.Second, time.Minute)

	allowed, remaining, _, _ := l.Allow("client-a", 7)
	if !allowed || remaining != 3 {
		t.Fatalf("Expected allowed with remaining 3, got allowed=%v, remaining=%d", allowed, remaining)
	}

	allowed, _, _, _ = l.Allow("client-a", 4)
	if allowed {
		t.Fatal("Expected request costing more than remaining tokens to be denied")
	}
}

func TestEvictIdle(t *testing.T) {
	l := New(5, time.Second, 50*time.Millisecond)
	l.Allow("stale-client", 1)

	if l.Len() != 1 {
		t.Fatalf("Expected 1 bucket, got %d", l.Len())
	}

	
	time.Sleep(60 * time.Millisecond)
	l.evictIdle()

	if l.Len() != 0 {
		t.Fatalf("Expected idle bucket to be evicted, got %d remaining", l.Len())
	}
}

func TestEvictIdle_DoesNotEvictActiveKeys(t *testing.T) {
	l := New(5, time.Second, 50*time.Millisecond)
	l.Allow("active-client", 1)

	time.Sleep(30 * time.Millisecond)
	l.Allow("active-client", 1) // touch again before TTL elapses

	time.Sleep(30 * time.Millisecond) // 60ms since first touch, but only 30ms since the second
	l.evictIdle()

	if l.Len() != 1 {
		t.Fatalf("Expected bucket to survive the sweep")
	}
}


func TestStartCleanup_StopsOnContextCancel(t *testing.T) {
	l := New(5, time.Second, 10*time.Millisecond)
	l.Allow("client-a", 1)

	ctx, cancel := context.WithCancel(context.Background())
	l.StartCleanup(ctx, 10*time.Millisecond)

	time.Sleep(30 * time.Millisecond)
	if l.Len() != 0 {
		t.Fatal("Expected background cleanup to evict the idle bucket")
	}

	cancel()

	time.Sleep(20 * time.Millisecond)
}

func TestAllow_ConcurrentAccess(t *testing.T) {
	const capacity = 100
	const goroutines = 50
	const requestsPerGoroutine = 10 

	l := New(capacity, time.Hour, time.Minute)

	var wg sync.WaitGroup
	var mu sync.Mutex
	allowedCount := 0

	for g := 0; g < goroutines; g++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < requestsPerGoroutine; i++ {
				allowed, _, _, _ := l.Allow("shared-key", 1)
				if allowed {
					mu.Lock()
					allowedCount++
					mu.Unlock()
				}
			}
		}()
	}
	wg.Wait()

	if allowedCount != capacity {
		t.Fatalf("Expected exactly %d allowed requests out of %d total, got %d",
			capacity, goroutines*requestsPerGoroutine, allowedCount)
	}
}

func TestAllow_ConcurrentDifferentKeys(t *testing.T) {
	l := New(10, time.Hour, time.Minute)

	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			key := "key-" + string(rune('a'+i%26))
			l.Allow(key, 1)
		}(i)
	}
	wg.Wait()

	if l.Len() == 0 {
		t.Fatal("Expected buckets to have been created")
	}
}
