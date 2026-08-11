from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category: str | None = Field(default=None, max_length=100)
    barcode: str | None = Field(default=None, max_length=128)
    unit: str = Field(default="pcs", max_length=16)
    status: str = Field(default="ACTIVE", max_length=24)
    target_sell_price: Decimal | None = None
    currency: str = Field(default="CNY", max_length=8)
    default_warehouse_id: uuid.UUID | None = None
    default_location_id: uuid.UUID | None = None
    market_tracking_enabled: bool = False


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    category: str | None = Field(default=None, max_length=100)
    barcode: str | None = Field(default=None, max_length=128)
    unit: str | None = Field(default=None, max_length=16)
    status: str | None = Field(default=None, max_length=24)
    target_sell_price: Decimal | None = None
    currency: str | None = Field(default=None, max_length=8)
    default_warehouse_id: uuid.UUID | None = None
    default_location_id: uuid.UUID | None = None
    market_tracking_enabled: bool | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    name: str
    description: str | None
    category: str | None
    barcode: str | None
    unit: str
    status: str
    target_sell_price: Decimal | None
    currency: str
    default_warehouse_id: uuid.UUID | None
    default_location_id: uuid.UUID | None
    market_tracking_enabled: bool
    created_at: datetime
    updated_at: datetime
