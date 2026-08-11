"""Market data providers."""

from __future__ import annotations

from app.providers.market.base import MarketDataProvider
from app.providers.market.http_json import GenericHttpJsonProvider
from app.providers.market.mock import MockMarketProvider
from app.providers.market.open_er_api import OpenErApiFxProvider
from app.providers.market.rss import GenericRssProvider

MARKET_PROVIDER_REGISTRY: dict[str, type[MarketDataProvider]] = {
    "mock": MockMarketProvider,
    "http_json": GenericHttpJsonProvider,
    "rss": GenericRssProvider,
    "open_er_api": OpenErApiFxProvider,
}


def get_market_provider(name: str | None = None) -> MarketDataProvider:
    """按注册表解析 Provider；未知名称直接报错，禁止 silent fallback。"""

    from app.core.config import settings

    provider_name = (name or settings.market_provider or "mock").lower()
    if provider_name not in MARKET_PROVIDER_REGISTRY:
        raise ValueError(f"未知 Market Provider: {provider_name}（可选: {sorted(MARKET_PROVIDER_REGISTRY)}）")
    return MARKET_PROVIDER_REGISTRY[provider_name]()


__all__ = [
    "get_market_provider",
    "MockMarketProvider",
    "GenericHttpJsonProvider",
    "GenericRssProvider",
    "OpenErApiFxProvider",
]
