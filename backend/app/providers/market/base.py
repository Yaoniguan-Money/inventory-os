from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol


@dataclass
class QuoteData:
    external_symbol: str
    quote_kind: str  # MARKET_BUY / MARKET_SELL
    price: Decimal
    currency: str
    source: str
    region: str
    observed_at: datetime
    unit: str | None = None
    basis: str | None = None
    source_url: str | None = None
    raw_payload: dict | None = None


@dataclass
class MarketEventData:
    external_symbol: str
    title: str
    summary: str | None
    source: str
    region: str
    published_at: datetime
    source_url: str | None = None
    tags: list[str] = field(default_factory=list)


class MarketDataProvider(Protocol):
    name: str

    async def get_latest_quotes(self, external_symbol: str, region: str) -> list[QuoteData]: ...

    async def get_history(self, external_symbol: str, region: str, limit: int = 30) -> list[QuoteData]: ...

    async def get_market_events(self, external_symbol: str, region: str, limit: int = 20) -> list[MarketEventData]: ...
