from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.errors import NotFoundError
from app.core.events import record_event
from app.domains.catalog.models import Product
from app.domains.pricing.models import InternalPriceSnapshot


def record_price_snapshot(
    db: AsyncSession,
    *,
    organization_id: str,
    product_id: str,
    price_type: str,
    price,
    currency: str,
    source_reference_type: str | None = None,
    source_reference_id: str | None = None,
    effective_at: datetime | None = None,
) -> InternalPriceSnapshot:
    snapshot = InternalPriceSnapshot(
        organization_id=uuid.UUID(organization_id),
        product_id=uuid.UUID(product_id),
        price_type=price_type,
        price=price,
        currency=currency,
        source_reference_type=source_reference_type,
        source_reference_id=source_reference_id,
        effective_at=effective_at or datetime.now(UTC),
    )
    db.add(snapshot)
    return snapshot


async def get_prices(db: AsyncSession, *, organization_id: str, product_id: str) -> dict:
    product = (
        await db.execute(
            select(Product).where(
                Product.id == uuid.UUID(product_id),
                Product.organization_id == uuid.UUID(organization_id),
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise NotFoundError("商品不存在")

    async def latest(price_type: str) -> InternalPriceSnapshot | None:
        snapshot = (
            await db.execute(
                select(InternalPriceSnapshot)
                .where(
                    InternalPriceSnapshot.organization_id == uuid.UUID(organization_id),
                    InternalPriceSnapshot.product_id == uuid.UUID(product_id),
                    InternalPriceSnapshot.price_type == price_type,
                )
                .order_by(
                    InternalPriceSnapshot.effective_at.desc(),
                    InternalPriceSnapshot.created_at.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if (
            snapshot is not None
            and price_type == "TARGET_SELL_PRICE"
            and snapshot.source_reference_type == "CLEARED"
        ):
            return None
        return snapshot

    history = (
        await db.execute(
            select(InternalPriceSnapshot)
            .where(
                InternalPriceSnapshot.organization_id == uuid.UUID(organization_id),
                InternalPriceSnapshot.product_id == uuid.UUID(product_id),
            )
            .order_by(InternalPriceSnapshot.effective_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return {
        "product_id": product.id,
        "last_purchase_price": await latest("LAST_PURCHASE_PRICE"),
        "weighted_avg_cost": await latest("WEIGHTED_AVG_COST"),
        "target_sell_price": await latest("TARGET_SELL_PRICE"),
        "actual_sell_price": await latest("ACTUAL_SELL_PRICE"),
        "history": list(history),
    }


async def set_target_price(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    product_id: str,
    price,
    currency: str,
) -> Product:
    product = (
        await db.execute(
            select(Product).where(
                Product.id == uuid.UUID(product_id),
                Product.organization_id == uuid.UUID(organization_id),
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise NotFoundError("商品不存在")
    before = {"target_sell_price": str(product.target_sell_price), "currency": product.currency}
    product.target_sell_price = price
    product.currency = currency
    record_price_snapshot(
        db,
        organization_id=organization_id,
        product_id=product_id,
        price_type="TARGET_SELL_PRICE",
        price=price,
        currency=currency,
        source_reference_type="MANUAL",
    )
    await db.flush()
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="price.target.update",
        entity_type="product",
        entity_id=str(product.id),
        before_json=before,
        after_json={"target_sell_price": str(product.target_sell_price), "currency": product.currency},
    )
    record_event(
        db,
        organization_id=organization_id,
        event_type="price.target.updated",
        aggregate_type="product",
        aggregate_id=str(product.id),
        payload={"price": str(price), "currency": currency},
    )
    return product
