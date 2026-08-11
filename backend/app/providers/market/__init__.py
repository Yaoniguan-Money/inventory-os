"""Market data providers."""

from __future__ import annotations

from app.core.config import settings
from app.providers.market.base import MarketDataProvider
from app.providers.market.http_json import GenericHttpJsonProvider
from app.providers.market.mock import MockMarketProvider
from app.providers.market.open_er_api import OpenErApiFxProvider
from app.providers.market.rss import GenericRssProvider


def get_market_provider(name: str | None = None) -> MarketDataProvider:
    provider_name = (name or settings.market_provider or "mock").lower()
    if provider_name == "http_json":
        return GenericHttpJsonProvider()
    if provider_name == "rss":
        return GenericRssProvider()
    if provider_name == "open_er_api":
        return OpenErApiFxProvider()
    return MockMarketProvider()


__all__ = [
    "get_market_provider",
    "MockMarketProvider",
    "GenericHttpJsonProvider",
    "GenericRssProvider",
    "OpenErApiFxProvider",
]
