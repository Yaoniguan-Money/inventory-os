from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class WarehouseCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    address: str | None = None
    status: str = Field(default="ACTIVE", max_length=24)


class WarehouseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    address: str | None
    status: str


class LocationCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str | None = None
    zone: str | None = Field(default=None, max_length=64)
    status: str = Field(default="ACTIVE", max_length=24)


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    warehouse_id: uuid.UUID
    code: str
    name: str | None
    zone: str | None
    status: str


class ReceiveRequest(BaseModel):
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    location_id: uuid.UUID | None = None
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal | None = Field(default=None, ge=0)
    lot_code: str | None = Field(default=None, max_length=64)
    expires_at: datetime | None = None
    supplier_id: uuid.UUID | None = None
    purchase_order_line_id: uuid.UUID | None = None
    reason: str | None = None


class AdjustRequest(BaseModel):
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Decimal  # signed delta; negative reduces stock
    reason: str | None = Field(default=None, max_length=500)


class InventoryBalanceOut(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    warehouse_id: uuid.UUID
    warehouse_code: str
    on_hand: Decimal
    reserved: Decimal
    available: Decimal
    version: int


class InventoryLotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    location_id: uuid.UUID | None
    lot_code: str
    quantity_remaining: Decimal
    unit_cost: Decimal | None
    received_at: datetime
    expires_at: datetime | None


class StockMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    location_id: uuid.UUID | None
    lot_id: uuid.UUID | None
    movement_type: str
    quantity: Decimal
    unit_cost: Decimal | None
    reference_type: str | None
    reference_id: str | None
    reason: str | None
    occurred_at: datetime
    created_by: uuid.UUID | None


class ReceiveResult(BaseModel):
    balance: InventoryBalanceOut
    lot_id: uuid.UUID | None = None
    movement_id: uuid.UUID
    weighted_avg_cost: Decimal | None = None


class AdjustResult(BaseModel):
    balance: InventoryBalanceOut
    movement_id: uuid.UUID
