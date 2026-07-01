"""
API key check as a FastAPI dependency.
"""

from __future__ import annotations
import hmac

from fastapi import HTTPException, Header

def make_api_key_dependency(expected_key: str):
    """
    Returns a FastAPI dependency fn bound to expected_key.
    If expected_key is empty, auth is skipped.
    """

    async def verify(x_api_key: str | None = Header(default=None)) -> None:
        if not expected_key:
            return
        provided = x_api_key or ""
        if not hmac.compare_digest(provided, expected_key):
            raise HTTPException(status_code=401, detail="Missing or invalid API key")
        
    return verify