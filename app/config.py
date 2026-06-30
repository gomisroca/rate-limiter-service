"""
Config - Same environment variables as used by the Go version, so the two versions are interchangeable from the outside.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    port: int
    api_key: str

    capacity: int
    window_seconds: float
    idle_ttle_seconds: float
    cleanup_interval_seconds: float

def load_settings() -> Settings:
    return Settings(
        port=int(os.getenv("PORT", "8080")),
        api_key=os.getenv("API_KEY", ""),
        capacity=int(os.getenv("RATE_LIMIT_CAPACITY", "100")),
        window_seconds=float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
        idle_ttl_seconds=float(os.getenv("BUCKET_IDLE_TTL_SECONDS", "600")),
        cleanup_interval_seconds=float(os.getenv("CLEANUP_INTERVAL_SECONDS", "60")),
    )