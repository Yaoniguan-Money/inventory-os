from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from app.providers.market.base import MarketDataProvider, MarketEventData, QuoteData


class OpenErApiFxProvider(MarketDataProvider):
    """
    真实国际参考价 Provider（开箱即用、无需 Key）：
    使用 open.er-api.com 的实时汇率，把 external_symbol（如 USD）换算为
    CNY/单位 作为国际市场参考价保存。数据有来源与时间，不是 Mock。
    """

    name = "open_er_api"
    base_url = "https://open.er-api.com/v6/latest/CNY"

    async def get_latest_quotes(self, external_symbol: str, region: str) -> list[QuoteData]:
        symbol = external_symbol.strip().upper()
        if not symbol:
            return []
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(self.base_url)
            resp.raise_for_status()
            data = resp.json()
        rates = data.get("rates", {})
        rate = rates.get(symbol)
        if not rate:
            return []
        price = (Decimal("1") / Decimal(str(rate))).quantize(Decimal("0.0001"))
        now = datetime.now(UTC)
        return [
            QuoteData(
                external_symbol=symbol,
                quote_kind="MARKET_SELL",
                price=price,
                currency="CNY",
                source="OpenErApiFxProvider (真实国际汇率参考)",
                region=region or "INTERNATIONAL",
                unit="CNY",
                basis="FX",
                observed_at=now,
                raw_payload={"base": "CNY", "rate": str(rate)},
            )
        ]

    async def get_history(
        self, external_symbol: str, region: str, limit: int = 30
    ) -> list[QuoteData]:
        return await self.get_latest_quotes(external_symbol, region)

    async def get_market_events(
        self, external_symbol: str, region: str, limit: int = 20
    ) -> list[MarketEventData]:
        return []
