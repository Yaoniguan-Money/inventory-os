from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CustomerCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None


class SalesOrderLineCreate(BaseModel):
    product_id: uuid.UUID
    ordered_qty: Decimal = Field(gt=0)
    unit_sell_price: Decimal | None = Field(default=None, ge=0)
    required_at: datetime | None = None


class SalesOrderCreate(BaseModel):
    customer_id: uuid.UUID
    lines: list[SalesOrderLineCreate] = Field(min_length=1)
    ordered_at: datetime | None = None
    required_at: datetime | None = None
    currency: str = Field(default="CNY", max_length=8)
    notes: str | None = None


class SalesOrderLineOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    ordered_qty: Decimal
    reserved_qty: Decimal
    delivered_qty: Decimal
    remaining_qty: Decimal
    unit_sell_price: Decimal | None
    required_at: datetime | None
    available: Decimal | None = None
    incoming: Decimal | None = None
    fulfillment_risk: bool = False


class SalesOrderOut(BaseModel):
    id: uuid.UUID
    order_no: str
    customer_id: uuid.UUID
    customer_name: str
    status: str
    ordered_at: datetime
    required_at: datetime | None
    currency: str
    notes: str | None
    lines: list[SalesOrderLineOut]
    created_at: datetime


class FulfillLineRequest(BaseModel):
    sales_order_line_id: uuid.UUID
    quantity: Decimal = Field(gt=0)


class FulfillRequest(BaseModel):
    lines: list[FulfillLineRequest] = Field(min_length=1)


class ConfirmResult(BaseModel):
    order: SalesOrderOut
    shortages: list[dict] = Field(default_factory=list)


class ReservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sales_order_line_id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: Decimal
    status: str
    created_at: datetime
    released_at: datetime | None
