from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IntegrationEventEnvelope(BaseModel):
    schema_version: str = Field(min_length=1, max_length=16)
    event_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=64)
    occurred_at: datetime | None = None
    source: str = Field(min_length=1, max_length=64)
    data: dict[str, Any] = Field(default_factory=dict)


class IntegrationEventResult(BaseModel):
    status: str  # accepted / duplicate / rejected
    event_id: str
    message: str | None = None
