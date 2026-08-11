from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SupplierCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    contact: str | None = None


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    contact: str | None


class PurchaseOrderLineCreate(BaseModel):
    product_id: uuid.UUID
    ordered_qty: Decimal = Field(gt=0)
    unit_purchase_price: Decimal | None = Field(default=None, ge=0)
    expected_at: datetime | None = None


class PurchaseOrderCreate(BaseModel):
    supplier_id: uuid.UUID
    lines: list[PurchaseOrderLineCreate] = Field(min_length=1)
    ordered_at: datetime | None = None
    expected_at: datetime | None = None
    currency: str = Field(default="CNY", max_length=8)


class PurchaseOrderLineOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    ordered_qty: Decimal
    received_qty: Decimal
    incoming_qty: Decimal
    unit_purchase_price: Decimal | None
    expected_at: datetime | None


class PurchaseOrderOut(BaseModel):
    id: uuid.UUID
    po_no: str
    supplier_id: uuid.UUID
    supplier_name: str
    status: str
    ordered_at: datetime
    expected_at: datetime | None
    currency: str
    lines: list[PurchaseOrderLineOut]


class PurchaseReceiveLine(BaseModel):
    purchase_order_line_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    location_id: uuid.UUID | None = None
    lot_code: str | None = Field(default=None, max_length=64)
    expires_at: datetime | None = None


class PurchaseReceiveRequest(BaseModel):
    lines: list[PurchaseReceiveLine] = Field(min_length=1)


class WorkbenchItem(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    on_hand: Decimal
    reserved: Decimal
    available: Decimal
    expired_qty: Decimal = Decimal("0")
    projected: Decimal = Decimal("0")
    incoming: Decimal
    incoming_before_7d: Decimal = Decimal("0")
    demand_7d: Decimal
    reserved_for_due: Decimal = Decimal("0")
    unreserved_due: Decimal = Decimal("0")
    shortage_7d: Decimal
    last_purchase_price: Decimal | None
    weighted_avg_cost: Decimal | None
    market_quotes: dict[str, dict] = Field(default_factory=dict)
    purchase_history: list[dict] = Field(default_factory=list)
    market_events: list[dict] = Field(default_factory=list)
    suppliers: list[dict]
    purchase_orders: list[dict]
