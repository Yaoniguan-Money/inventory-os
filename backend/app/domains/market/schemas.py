from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MarketQuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_symbol: str
    quote_kind: str
    price: Decimal
    currency: str
    source: str
    source_url: str | None
    region: str
    observed_at: datetime
    fetched_at: datetime


class MarketEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    summary: str | None
    source: str
    source_url: str | None
    published_at: datetime
    region: str
    tags: list[Any]


class MarketMappingCreate(BaseModel):
    provider: str = Field(default="mock", max_length=64)
    external_symbol: str = Field(min_length=1, max_length=128)
    region: str = Field(default="DOMESTIC", max_length=24)
    enabled: bool = True


class MarketMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    provider: str
    external_symbol: str
    region: str
    enabled: bool


class ProductMarketOut(BaseModel):
    product_id: uuid.UUID
    quotes: list[MarketQuoteOut]
    events: list[MarketEventOut]
    mappings: list[MarketMappingOut]


class MarketRefreshResult(BaseModel):
    refreshed: int
    quotes_saved: int
    events_saved: int
