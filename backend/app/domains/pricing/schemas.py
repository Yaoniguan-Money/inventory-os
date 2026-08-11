from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TargetPriceRequest(BaseModel):
    price: Decimal = Field(ge=0)
    currency: str = Field(default="CNY", max_length=8)


class PriceSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    price_type: str
    price: Decimal
    currency: str
    source_reference_type: str | None
    effective_at: datetime
    created_at: datetime


class ProductPricesOut(BaseModel):
    product_id: uuid.UUID
    last_purchase_price: PriceSnapshotOut | None
    weighted_avg_cost: PriceSnapshotOut | None
    target_sell_price: PriceSnapshotOut | None
    actual_sell_price: PriceSnapshotOut | None
    history: list[PriceSnapshotOut]
