from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.providers.market.base import MarketDataProvider, MarketEventData, QuoteData


class MockMarketProvider(MarketDataProvider):
    """明确标记的 Demo/Mock Provider：提供可复现的演示行情，接口可替换为真实 Provider。"""

    name = "mock"

    def _seed(self, external_symbol: str) -> int:
        digest = hashlib.sha256(external_symbol.encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    async def get_latest_quotes(self, external_symbol: str, region: str) -> list[QuoteData]:
        seed = self._seed(external_symbol)
        buy = Decimal(str(80 + seed % 30))
        sell = buy + Decimal(str(20 + seed % 25))
        now = datetime.now(UTC)
        currency = "CNY"
        return [
            QuoteData(
                external_symbol=external_symbol,
                quote_kind="MARKET_BUY",
                price=buy,
                currency=currency,
                source="MockMarketProvider (Demo)",
                region=region,
                observed_at=now - timedelta(hours=1),
            ),
            QuoteData(
                external_symbol=external_symbol,
                quote_kind="MARKET_SELL",
                price=sell,
                currency=currency,
                source="MockMarketProvider (Demo)",
                region=region,
                observed_at=now - timedelta(hours=1),
            ),
        ]

    async def get_history(self, external_symbol: str, region: str, limit: int = 30) -> list[QuoteData]:
        seed = self._seed(external_symbol)
        base = Decimal(str(80 + seed % 30))
        now = datetime.now(UTC)
        out: list[QuoteData] = []
        for i in range(limit):
            day = Decimal(str(1 + (seed + i * 7) % 10)) / Decimal("10")
            out.append(
                QuoteData(
                    external_symbol=external_symbol,
                    quote_kind="MARKET_BUY",
                    price=base + day,
                    currency="CNY",
                    source="MockMarketProvider (Demo)",
                    region=region,
                    observed_at=now - timedelta(days=limit - i),
                )
            )
        return out

    async def get_market_events(self, external_symbol: str, region: str, limit: int = 20) -> list[MarketEventData]:
        seed = self._seed(external_symbol)
        now = datetime.now(UTC)
        templates = [
            ("原材料现货成交活跃，报价小幅上行", "贸易商反馈近期采购询价增加，成交价环比持稳。"),
            ("下游订单回暖带动备货需求", "部分工厂开始补充安全库存，市场关注供应节奏。"),
            ("港口到货量环比变化", "本周到货节奏正常，库存水平中性。"),
        ]
        return [
            MarketEventData(
                external_symbol=external_symbol,
                title=templates[(seed + i) % len(templates)][0],
                summary=templates[(seed + i) % len(templates)][1],
                source="MockMarketProvider (Demo)",
                region=region,
                published_at=now - timedelta(days=i),
                tags=["mock", "行情"],
            )
            for i in range(min(limit, len(templates)))
        ]
