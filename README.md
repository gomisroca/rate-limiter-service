# Rate Limiter Service (Python)

A Python/FastAPI port of [`Rate Limiter Service`](https://github.com/gomisroca/rate-limiter-service/tree/go)
(the Go version). Same algorithm, same HTTP API - you can point anything
that calls one at the other and nothing downstream needs to change. The
interesting part of this exercise isn't the API, it's everything _behind_
it: the same token-bucket idea looks meaningfully different once it's
expressed in Python's concurrency model instead of Go's.

## Running it

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Then open `http://localhost:8080` for the same demo page as the Go
version (it's the literal same HTML file - the API is identical), or call
it directly:

```bash
curl "http://localhost:8080/check?key=alice"
```

### Tests

```bash
pip install -r requirements.txt
pytest -v
```

19 tests: the same logical test cases as the Go suite's
`limiter_test.go` (burst-then-deny, independent keys, refill-over-time,
idle eviction, background cleanup), translated to `pytest-asyncio`, plus
full API-level tests using FastAPI's `TestClient`.

### Docker

```bash
docker build -t rate-limiter-service-py .
docker run -p 8080:8080 -e RATE_LIMIT_CAPACITY=100 -e RATE_LIMIT_WINDOW_SECONDS=60 rate-limiter-service-py
```

### Config

Identical env vars to the Go version - `PORT`, `API_KEY`,
`RATE_LIMIT_CAPACITY`, `RATE_LIMIT_WINDOW_SECONDS`, `BUCKET_IDLE_TTL_SECONDS`,
`CLEANUP_INTERVAL_SECONDS`. See the Go README for the full table; it's not
repeated here since it'd just be a duplicate.

## What's the same

- **Algorithm.** Lazy-refilled token bucket per client key, computed from
  elapsed wall-clock time on each access - no per-key background timer.
- **HTTP contract.** Same routes, same request/response JSON shape, same
  headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `Retry-After`),
  same status codes. A client built against one works unmodified against
  the other.
- **Background eviction** of idle buckets, same TTL-based sweep.
- **API key auth** via `X-API-Key`, constant-time comparison, skippable
  for local dev.
- **In-memory, single-instance** - same limitation as the Go version: this
  doesn't share state across multiple replicas. See the Go README's
  "Possible next steps" for the Redis-backed multi-instance discussion;
  it applies equally here.

## What's different, and why

**Concurrency model.** Go's `net/http` gives every request its own
goroutine; goroutines are preemptible and can run on real OS threads in
parallel, so two requests can genuinely execute Go code at the same
instant on a multi-core machine. That's why the Go version needs a real
`sync.Mutex`/`sync.RWMutex` and why `go test -race` is a meaningful thing
to run against it - there's a real race to detect.

FastAPI route handlers here are `async def` coroutines running on a single
event loop thread. Python's GIL means two coroutines can never execute
Python bytecode at literally the same instant, and `async`/`await` only
yields control at explicit `await` points - so a block of code with no
`await` in it is implicitly atomic with respect to other coroutines, no
lock required. `app/bucket.py`'s docstring goes into this in more detail:
we still use `asyncio.Lock` for the bucket's critical section, less because
correctness strictly requires it today and more because it keeps the
invariant explicit and safe against future changes (e.g. if someone later
adds an `await` inside that block for some reason).

One consequence: there's no Python equivalent of `go test -race` here,
because the specific bug class it catches (true simultaneous memory access
from parallel threads) isn't possible under the GIL in the first place. The
bug class that _can_ happen in asyncio - two coroutines both observing
"key missing" and both creating a bucket, with an `await` between the
check and the create - is what `test_concurrent_access_enforces_capacity_exactly`
and `test_concurrent_different_keys_creates_buckets_safely` in
`tests/test_limiter.py` are built to catch, using `asyncio.gather` to fire
many coroutines at once rather than goroutines.

**Multi-process scaling looks different too.** Go's goroutines let one
process handle huge concurrency on its own; people often run a single Go
binary per container. Python/FastAPI more commonly scales by running
multiple **worker processes** (`uvicorn --workers 4`, or behind Gunicorn).
Critically: each worker process has **its own separate memory**, so each
would enforce its own independent rate limit - the in-memory single-instance
caveat that already applies to the Go version going from one replica to many
applies here even faster, going from one _worker_ to many, on the very same
machine. If you deploy this with more than one worker, you need the
Redis-backed version (or similar shared store) for the limit to mean what
it says.

**Auth as a dependency, not middleware.** Go's `RequireAPIKey` takes an
`http.Handler` and returns a wrapped one - middleware in the classic sense.
FastAPI's idiom is dependency injection: `app/auth.py` exposes a function
that the framework calls before the route runs, and routes opt in by
listing it (`dependencies=[Depends(require_api_key)]`). Same effect,
different shape - neither is "more correct," it's just what's idiomatic in
each framework.

**Background task lifecycle.** Go's version threads a `context.Context`
through `main()` and cancels it on `SIGINT`/`SIGTERM` to stop the cleanup
goroutine. FastAPI's `lifespan` context manager (`app/main.py`) is the
idiomatic equivalent - code before `yield` runs on startup, code after runs
on shutdown, and FastAPI handles wiring it to the ASGI server's lifecycle
events.

**Validation.** Go's version manually decodes JSON and writes a custom
`400` on bad input. Pydantic models (`app/models.py`) validate the request
body automatically; malformed JSON gets a `422` (FastAPI's standard
validation-error status) without any handler code having to check for it.
Less code, but it means giving up some control over the exact error shape

- a tradeoff that goes the other way in the Go version, where you write
  more validation code but it returns exactly what you tell it to.

## Possible next steps

Same list as the Go version applies: a Redis-backed limiter for real
multi-instance/multi-worker deployments, per-key custom limits, and
metrics on allow/deny rates. Nothing here is Python-specific.
