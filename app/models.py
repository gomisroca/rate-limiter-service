from __future__ import annotations

from pydantic import BaseModel, Field


class CheckRequestBody(BaseModel):
    """
    Optional JSON body for POST /check
    """

    key: str | None = None
    cost: float | None = Field(default=None, gt=0)

class CheckResponse(BaseModel):
    allowed: bool
    limit: int
    remaining: int
    resetAfterSeconds: float