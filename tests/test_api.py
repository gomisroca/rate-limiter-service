"""
API-level tests using FastAPI's TestClient (built on httpx), exercising the app
the same way a real HTTP client would.
"""

from __future__ import annotations
import importlib

from fastapi.testclient import TestClient
import pytest

def _build_app(monkeypatch: pytest.MonkeyPatch, **env: str):
    """Reloads app.main with the given env vars, so each test gets a fresh app and Limiter."""

    for key, value in env.items():
        monkeypatch.setenv(key, value)

    import app.config
    import app.main

    importlib.reload(app.config)
    importlib.reload(app.main)

    return app.main.app

def test_health_check(monkeypatch):
    app = _build_app(monkeypatch)

    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}
        
def test_check_allows_then_denies(monkeypatch):
    app = _build_app(monkeypatch, RATE_LIMIT_CAPACITY="3", RATE_LIMIT_WINDOW_SECONDS="60")

    with TestClient(app) as client:
        for i in range(3):
            res = client.get("/check", params={"key": "alice"})
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["allowed"] is True
            assert body["remaining"] == 3 - (i + 1)

        res = client.get("/check", params={"key": "alice"})
        assert res.status_code == 429
        body = res.json()
        assert body["allowed"] is False
        assert "Retry-After" in res.headers

def test_check_different_keys_independent(monkeypatch):
    app = _build_app(monkeypatch, RATE_LIMIT_CAPACITY="1", RATE_LIMIT_WINDOW_SECONDS="60")

    with TestClient(app) as client:
        assert client.get("/check", params={"key": "alice"}).json()["allowed"] is True
        assert client.get("/check", params={"key": "alice"}).json()["allowed"] is False
        assert client.get("/check", params={"key": "bob"}).json()["allowed"] is True

def test_check_post_with_json_body_and_cost(monkeypatch):
    app = _build_app(monkeypatch, RATE_LIMIT_CAPACITY="5", RATE_LIMIT_WINDOW_SECONDS="60")

    with TestClient(app) as client:
        res = client.post("/check", json={"key": "alice", "cost": 3})
        assert res.status_code == 200
        assert res.json()["remaining"] == 2

        res = client.post("/check", json={"key": "alice", "cost": 3})
        assert res.status_code == 429

def test_check_post_empty_body_falls_back_to_ip(monkeypatch):
    app = _build_app(monkeypatch, RATE_LIMIT_CAPACITY="5", RATE_LIMIT_WINDOW_SECONDS="60")

    with TestClient(app) as client:
        res = client.post("/check")
        assert res.status_code == 200
        assert res.json()["allowed"] == True

def test_check_post_malformed_json_returns_422(monkeypatch):
    app = _build_app(monkeypatch, RATE_LIMIT_CAPACITY="5", RATE_LIMIT_WINDOW_SECONDS="60")

    with TestClient(app) as client:
        res = client.post("/check", content="not json", headers={"Content-Type": "application/json"})
        assert res.status_code == 422
    
def test_rate_limit_headers_present(monkeypatch):
    app = _build_app(monkeypatch, RATE_LIMIT_CAPACITY="10", RATE_LIMIT_WINDOW_SECONDS="60")

    with TestClient(app) as client:
        res = client.get("/check", params={"key": "dave"})
        assert res.headers["X-RateLimit-Limit"] == "10"
        assert res.headers["X-RateLimit-Remaining"] == "9"
    
def test_api_key_required_when_configured(monkeypatch):
    app = _build_app(monkeypatch, API_KEY="secret123", RATE_LIMIT_CAPACITY="5", RATE_LIMIT_WINDOW_SECONDS="60")

    with TestClient(app) as client:
        res = client.get("/check", params={"key": "eve"})
        assert res.status_code == 401

        res = client.get("/check", params={"key": "eve"}, headers={"X-API-Key": "wrong"})
        assert res.status_code == 401

        res = client.get("/check", params={"key": "eve"}, headers={"X-API-Key": "secret123"})
        assert res.status_code == 200
    
def test_health_open_even_with_api_key_set(monkeypatch):
    app = _build_app(monkeypatch, API_KEY="secret123")

    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200

    
def test_api_key_open_when_not_configured(monkeypatch):
    app = _build_app(monkeypatch, RATE_LIMIT_CAPACITY="5", RATE_LIMIT_WINDOW_SECONDS="60")
    
    with TestClient(app) as client:
        res = client.get("/check", params={"key": "frank"})
        assert res.status_code == 200