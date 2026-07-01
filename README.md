# Rate Limiter Service (Go)

A standalone Go microservice that any other app - written in any language -
calls before doing real work, to check "is this client allowed to proceed
right now?" It's the same "plug and play" idea as image-upload-service: a
small, single-purpose service with a plain HTTP interface that anything can
call.

## How it works

Each distinct client **key** (an API key, a user ID, an IP address -
whatever identifies "one client" in your system) gets its own **token
bucket**: a pool of tokens that refills continuously over time. Every
request costs 1 token by default (configurable per-request). Run out of
tokens and you get a `429` until enough time has passed to refill.

This is "X requests per Y seconds," but smoothed - a client doesn't get a
fresh full burst the instant a fixed window rolls over; tokens trickle back
continuously. It's the same algorithm used by most production API gateways
(Stripe, GitHub, etc. all describe their public rate limits this way).

## Why this architecture

- **Lazy refill, no per-key goroutine.** Each bucket computes "how many
  tokens would have refilled since I was last touched?" using simple
  timestamp math under a mutex, rather than running a ticker per key. A
  service with 100,000 distinct client keys doesn't cost 100,000 background
  goroutines - idle keys cost nothing until they're touched again.
- **Concurrency-safe by construction, proven, not just claimed.** The bucket
  map uses a read-mostly RWMutex with double-checked locking (the common
  case - bucket already exists - never takes a write lock), and each
  individual bucket has its own mutex. `internal/limiter/limiter_test.go`
  includes a test that hammers a single key from 50 goroutines at once and
  asserts exactly the configured capacity gets through - run it with
  `go test -race ./...` and the race detector confirms there's no data race,
  not just that the numbers come out right.
- **Background eviction, not unbounded memory growth.** A goroutine sweeps
  periodically and drops buckets that have been idle past a configurable
  TTL - necessary once you realize "key" is often something like a client
  IP, and the set of distinct IPs over a service's lifetime is unbounded.
- **In-memory by design, with the upgrade path called out.** State lives in
  this process's memory - fine for a single instance, but each replica
  behind a load balancer would enforce its own limit independently if you
  scaled this out. See "Possible next steps" below for the Redis-backed
  version of this.
- **Zero external dependencies**, same as image-upload-service's image
  processing - the whole algorithm is standard library `sync` and `time`.

## Running it

```bash
go run .
```

Then open `http://localhost:8080` for a small demo page (drains the bucket
with single clicks or a 20-request burst button and shows it refill live),
or call the API directly:

```bash
curl "http://localhost:8080/check?key=alice"
```

### Config (env vars, all optional)

| Variable                    | Default   | Description                                                                                            |
| --------------------------- | --------- | ------------------------------------------------------------------------------------------------------ |
| `PORT`                      | `8080`    | HTTP port                                                                                              |
| `API_KEY`                   | _(empty)_ | If set, required via `X-API-Key` header on `/check`                                                    |
| `RATE_LIMIT_CAPACITY`       | `100`     | Max tokens (requests) per key                                                                          |
| `RATE_LIMIT_WINDOW_SECONDS` | `60`      | Time for a full refill - e.g. capacity 100 + window 60 = "100 requests/minute," refilling continuously |
| `BUCKET_IDLE_TTL_SECONDS`   | `600`     | How long an unused key's bucket survives before eviction                                               |
| `CLEANUP_INTERVAL_SECONDS`  | `60`      | How often the eviction sweep runs                                                                      |

### Docker

```bash
docker build -t rate-limiter-service .
docker run -p 8080:8080 -e RATE_LIMIT_CAPACITY=100 -e RATE_LIMIT_WINDOW_SECONDS=60 rate-limiter-service
```

## API

### `GET /check?key=alice&cost=1` or `POST /check` with `{"key": "alice", "cost": 1}`

Both `key` and `cost` are optional: an omitted `key` falls back to the
caller's IP (via `X-Forwarded-For` if present, else the raw connection);
`cost` defaults to `1`.

**`200 OK`** when allowed, **`429 Too Many Requests`** when not:

```json
{
  "allowed": true,
  "limit": 100,
  "remaining": 87,
  "resetAfterSeconds": 0
}
```

Response headers on every call: `X-RateLimit-Limit`, `X-RateLimit-Remaining`.
On a `429`, also `Retry-After` (seconds, rounded up - standard HTTP
convention for "come back after this long").

### `GET /health`

Liveness check - `{"status": "ok"}`.

## Calling it from another service

This is the point of building it standalone - your image uploader, your
Next.js API routes, anything, can check in before doing expensive work:

```js
const res = await fetch(
  "https://your-ratelimiter.example.com/check?key=" + userId,
  {
    headers: { "X-API-Key": process.env.RATELIMITER_API_KEY },
  },
);
const { allowed, remaining, resetAfterSeconds } = await res.json();

if (!allowed) {
  return new Response("Too many requests", {
    status: 429,
    headers: { "Retry-After": String(Math.ceil(resetAfterSeconds)) },
  });
}
// proceed with the real work
```

For image-upload-service specifically: call this right before the
`/upload` handler does any decoding/resizing work, keyed on the same
identifier you use for its own `API_KEY`/client concept (or the caller's IP)

- that's exactly the gap this was built to fill.

## Possible next steps

- **Redis-backed limiter for multi-instance deployments.** Implement the
  same `RateLimiter` interface (`internal/handlers/check.go`) backed by
  Redis (`INCR` + `EXPIRE`, or a Lua script for an atomic token-bucket
  check) so multiple replicas of this service share one true limit instead
  of each enforcing its own.
- **Per-key custom limits.** Right now capacity/window are global. A small
  lookup (config file, or a database keyed by API key) could give some
  clients a higher limit than others - e.g. a "pro tier."
- **Metrics.** Counting allowed vs. denied per key over time would make a
  genuinely useful dashboard, and pairs well with the event-delivery
  service idea - denied-request spikes are exactly the kind of thing you'd
  want a webhook/alert for.
