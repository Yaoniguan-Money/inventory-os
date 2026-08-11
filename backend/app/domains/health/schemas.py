from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    alert_type: str
    severity: str
    status: str
    title: str
    evidence_json: dict[str, Any]
    opened_at: datetime
    resolved_at: datetime | None


class ProductHealthOut(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    score: int
    alerts: list[AlertOut]
    deductions: list[dict]


class HealthOverviewOut(BaseModel):
    org_score: int
    open_alert_count: int
    by_severity: dict[str, int]
    by_type: dict[str, int]
    products: list[ProductHealthOut]
