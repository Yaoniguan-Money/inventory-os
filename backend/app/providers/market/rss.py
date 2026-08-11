from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from app.providers.market.base import MarketDataProvider, MarketEventData, QuoteData


class GenericRssProvider(MarketDataProvider):
    """通用 RSS Provider：把外部 RSS 条目作为 MarketEvent 接入。"""

    name = "rss"

    def __init__(self) -> None:
        self.url = os.environ.get("MARKET_RSS_URL", "")

    async def get_latest_quotes(self, external_symbol: str, region: str) -> list[QuoteData]:
        return []

    async def get_history(self, external_symbol: str, region: str, limit: int = 30) -> list[QuoteData]:
        return []

    async def get_market_events(self, external_symbol: str, region: str, limit: int = 20) -> list[MarketEventData]:
        if not self.url:
            return []
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(self.url)
            resp.raise_for_status()
        root = ET.fromstring(resp.text)
        items: list[MarketEventData] = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            summary = (item.findtext("description") or "").strip()
            link = item.findtext("link") or None
            pub_text = item.findtext("pubDate")
            published = parsedate_to_datetime(pub_text) if pub_text else datetime.now(UTC)
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
            items.append(
                MarketEventData(
                    external_symbol=external_symbol,
                    title=title,
                    summary=summary or None,
                    source="GenericRssProvider",
                    region=region,
                    published_at=published,
                    source_url=link,
                    tags=["rss"],
                )
            )
            if len(items) >= limit:
                break
        return items
