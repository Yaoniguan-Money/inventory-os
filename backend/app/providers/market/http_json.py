from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.providers.market.base import MarketDataProvider, MarketEventData, QuoteData


class GenericHttpJsonProvider(MarketDataProvider):
    """
    通用 HTTP/JSON Provider：从配置的 URL 获取行情。
    期望响应形如：
    {"symbols": [{"symbol": "AL-99.7", "buy": "86.0", "sell": "112.0",
                  "currency": "CNY", "region": "DOMESTIC", "observed_at": "..."}]}
    """

    name = "http_json"

    def __init__(self) -> None:
        self.url = os.environ.get("MARKET_HTTP_URL", "")
        self.token = os.environ.get("MARKET_HTTP_TOKEN", "")

    async def _fetch(self, symbol: str) -> list[dict[str, Any]]:
        if not self.url:
            return []
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(self.url, params={"symbol": symbol}, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return data.get("symbols", []) if isinstance(data, dict) else []

    async def get_latest_quotes(self, external_symbol: str, region: str) -> list[QuoteData]:
        rows = await self._fetch(external_symbol)
        out: list[QuoteData] = []
        for row in rows:
            if row.get("symbol") != external_symbol:
                continue
            observed = (
                datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
                if row.get("observed_at")
                else datetime.now(UTC)
            )
            if row.get("buy") is not None:
                out.append(
                    QuoteData(
                        external_symbol=external_symbol,
                        quote_kind="MARKET_BUY",
                        price=Decimal(str(row["buy"])),
                        currency=row.get("currency", "CNY"),
                        source="GenericHttpJsonProvider",
                        region=row.get("region", region),
                        observed_at=observed,
                        raw_payload=row,
                    )
                )
            if row.get("sell") is not None:
                out.append(
                    QuoteData(
                        external_symbol=external_symbol,
                        quote_kind="MARKET_SELL",
                        price=Decimal(str(row["sell"])),
                        currency=row.get("currency", "CNY"),
                        source="GenericHttpJsonProvider",
                        region=row.get("region", region),
                        observed_at=observed,
                        raw_payload=row,
                    )
                )
        return out

    async def get_history(self, external_symbol: str, region: str, limit: int = 30) -> list[QuoteData]:
        return await self.get_latest_quotes(external_symbol, region)

    async def get_market_events(self, external_symbol: str, region: str, limit: int = 20) -> list[MarketEventData]:
        return []
