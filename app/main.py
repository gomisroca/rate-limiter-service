"""
Entry point - run with:
    uvicorn app.main:app --host 0.0.0.0 --port 8080

Wires config, the limiter and the HTTP routes together.

Structural differences from Go's version:
1. Background task lifecycle uses FastAPI's 'lifespan' context manager 
   instead of a context.Context passed down. This is the idiomatic way
   of the pattern "start something on boot, clean it up on shutdown".
2. Auth is a dependency listed on each route rather than a handler 
   wrapped in middleware.
"""

from __future__ import annotations

import math
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.auth import make_api_key_dependency
from app.config import load_settings
from app.limiter import Limiter
from app.models import CheckResponse

settings = load_settings()
limiter = Limiter(
    capacity=settings.capacity,
    window_seconds=settings.window_seconds,
    rate=settings.rate,
)

@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.api_key:
        print("WARNING: API key not set, '/check' is open to anyone who can reach the service")
    limiter.start_cleanup(settings.cleanup_interval_seconds)
    print(f"Rate Limiter Service starting - Capacity={settings.capacity} per {settings.window_seconds}s")
    yield
    await limiter.stop_cleanup()


app = FastAPI(lifespan=lifespan)

# Same permissive CORS policy as Go version
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)

require_api_key = make_api_key_dependency(settings.api_key)

def client_ip(request: Request) -> str:
    """Attempt to get client identifier when no explicit key is given"""
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"

def round_seconds(seconds: float) -> float:
    return round(seconds, 3)

async def run_check(key: str, cost: float, response: Response) -> JSONResponse:
    """Check if the key is allowed to make this request"""
    
    result = await limiter.allow(key, cost)

    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    
    status_code = 200
    if not result.allowed:
        status_code = 429
        response.headers["Retry-After"] = str(math.ceil(result.retry_after_seconds))
    
    body = CheckResponse(
        allowed=result.allowed,
        limit=result.limit,
        remaining=result.remaining,
        resetAfterSeconds=round_seconds(result.retry_after_seconds),
    )

    return JSONResponse(status_code=status_code, content=body.model_dump(), headers=dict(response.headers))

@app.get("/check", dependencies=[Depends(require_api_key)])
async def check_get(
    request: Request,
    response: Response,
    key: Annotated[str | None, Query()] = None,
    cost: Annotated[float | None, Query(gt=0)] = None,
) -> JSONResponse:
    resolved_key = key or client_ip(request)
    resolved_cost = cost if cost is not None else 1.0
    return await run_check(resolved_key, resolved_cost, response)

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

# Bundled demo page
app.mount("/", StaticFiles(directory="web", html=True), name="web")