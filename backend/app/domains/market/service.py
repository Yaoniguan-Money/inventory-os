from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import record_event
from app.domains.market.models import MarketEvent, MarketQuote, ProductMarketMapping
from app.providers.market import get_market_provider

logger = logging.getLogger(__name__)


async def refresh_market(db: AsyncSession, *, organization_id: str) -> dict:
    mappings = (
        await db.execute(
            select(ProductMarketMapping).where(
                ProductMarketMapping.organization_id == uuid.UUID(organization_id),
                ProductMarketMapping.enabled.is_(True),
            )
        )
    ).scalars().all()
    quotes_saved = 0
    events_saved = 0
    for mapping in mappings:
        provider = get_market_provider(mapping.provider)
        try:
            quotes = await provider.get_latest_quotes(mapping.external_symbol, mapping.region)
        except Exception as exc:  # noqa: BLE001 - 外部源失败不应阻断整体刷新
            logger.warning(
                "market provider %s failed for %s: %s",
                mapping.provider,
                mapping.external_symbol,
                exc,
            )
            quotes = []
        for quote in quotes:
            exists_quote = (
                await db.execute(
                    select(MarketQuote).where(
                        MarketQuote.organization_id == uuid.UUID(organization_id),
                        MarketQuote.product_id == mapping.product_id,
                        MarketQuote.external_symbol == quote.external_symbol,
                        MarketQuote.quote_kind == quote.quote_kind,
                        MarketQuote.region == quote.region,
                        MarketQuote.observed_at == quote.observed_at,
                    )
                )
            ).scalar_one_or_none()
            if exists_quote is None:
                db.add(
                    MarketQuote(
                        organization_id=uuid.UUID(organization_id),
                        product_id=mapping.product_id,
                        external_symbol=quote.external_symbol,
                        quote_kind=quote.quote_kind,
                        price=quote.price,
                        currency=quote.currency,
                        source=quote.source,
                        source_url=quote.source_url,
                        region=quote.region,
                        observed_at=quote.observed_at,
                        fetched_at=datetime.now(UTC),
                        raw_payload=quote.raw_payload,
                    )
                )
                quotes_saved += 1
                record_event(
                    db,
                    organization_id=organization_id,
                    event_type="market.quote.refreshed",
                    aggregate_type="product",
                    aggregate_id=str(mapping.product_id),
                    payload={
                        "external_symbol": quote.external_symbol,
                        "quote_kind": quote.quote_kind,
                        "price": str(quote.price),
                        "source": quote.source,
                    },
                )
        try:
            events = await provider.get_market_events(mapping.external_symbol, mapping.region)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "market event provider %s failed for %s: %s",
                mapping.provider,
                mapping.external_symbol,
                exc,
            )
            events = []
        for event in events:
            exists_event = (
                await db.execute(
                    select(MarketEvent).where(
                        MarketEvent.organization_id == uuid.UUID(organization_id),
                        MarketEvent.product_id == mapping.product_id,
                        MarketEvent.title == event.title,
                        MarketEvent.source == event.source,
                        MarketEvent.published_at == event.published_at,
                    )
                )
            ).scalar_one_or_none()
            if exists_event is None:
                db.add(
                    MarketEvent(
                        organization_id=uuid.UUID(organization_id),
                        product_id=mapping.product_id,
                        title=event.title,
                        summary=event.summary,
                        source=event.source,
                        source_url=event.source_url,
                        published_at=event.published_at,
                        region=event.region,
                        tags=event.tags,
                    )
                )
                events_saved += 1
                record_event(
                    db,
                    organization_id=organization_id,
                    event_type="market.event.ingested",
                    aggregate_type="product",
                    aggregate_id=str(mapping.product_id),
                    payload={"title": event.title, "source": event.source},
                )
    await db.flush()
    return {"refreshed": len(mappings), "quotes_saved": quotes_saved, "events_saved": events_saved}


async def get_product_market(db: AsyncSession, *, organization_id: str, product_id: str) -> dict:
    quotes = (
        await db.execute(
            select(MarketQuote)
            .where(
                MarketQuote.organization_id == uuid.UUID(organization_id),
                MarketQuote.product_id == uuid.UUID(product_id),
            )
            .order_by(MarketQuote.observed_at.desc())
            .limit(100)
        )
    ).scalars().all()
    events = (
        await db.execute(
            select(MarketEvent)
            .where(
                MarketEvent.organization_id == uuid.UUID(organization_id),
                MarketEvent.product_id == uuid.UUID(product_id),
            )
            .order_by(MarketEvent.published_at.desc())
            .limit(50)
        )
    ).scalars().all()
    mappings = (
        await db.execute(
            select(ProductMarketMapping).where(
                ProductMarketMapping.organization_id == uuid.UUID(organization_id),
                ProductMarketMapping.product_id == uuid.UUID(product_id),
            )
        )
    ).scalars().all()
    return {
        "product_id": uuid.UUID(product_id),
        "quotes": list(quotes),
        "events": list(events),
        "mappings": list(mappings),
    }


async def create_mapping(
    db: AsyncSession,
    *,
    organization_id: str,
    product_id: str,
    provider: str,
    external_symbol: str,
    region: str,
    enabled: bool,
) -> ProductMarketMapping:
    from app.core.errors import ConflictError

    existing = (
        await db.execute(
            select(ProductMarketMapping).where(
                ProductMarketMapping.organization_id == uuid.UUID(organization_id),
                ProductMarketMapping.product_id == uuid.UUID(product_id),
                ProductMarketMapping.provider == provider,
                ProductMarketMapping.external_symbol == external_symbol,
                ProductMarketMapping.region == region,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("该商品映射已存在")
    mapping = ProductMarketMapping(
        organization_id=uuid.UUID(organization_id),
        product_id=uuid.UUID(product_id),
        provider=provider,
        external_symbol=external_symbol,
        region=region,
        enabled=enabled,
    )
    db.add(mapping)
    await db.flush()
    return mapping
