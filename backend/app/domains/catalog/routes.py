from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_scope
from app.core.security import CurrentUser
from app.domains.catalog.models import Product
from app.domains.catalog.schemas import ProductCreate, ProductOut, ProductUpdate
from app.domains.catalog.service import create_product, get_product, update_product
from app.domains.integrations.models import EventLog
from app.domains.pricing.service import get_prices
from app.domains.purchasing.service import incoming_for_product
from app.domains.warehouse.models import InventoryBalance, InventoryLot

router = APIRouter(tags=["catalog"])


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    search: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=24),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("products:read")),
) -> list[ProductOut]:
    stmt = select(Product).where(Product.organization_id == uuid.UUID(user.organization_id))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            Product.sku.ilike(like)
            | Product.name.ilike(like)
            | Product.barcode.ilike(like)
        )
    if status:
        stmt = stmt.where(Product.status == status)
    rows = (await db.execute(stmt.order_by(Product.sku))).scalars().all()
    return [ProductOut.model_validate(row) for row in rows]


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product_route(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("products:write")),
) -> ProductOut:
    product = await create_product(
        db,
        organization_id=user.organization_id,
        actor_id=user.user_id,
        payload=payload,
    )
    await db.commit()
    return ProductOut.model_validate(product)


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product_route(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("products:read")),
) -> ProductOut:
    product = await get_product(db, organization_id=user.organization_id, product_id=product_id)
    return ProductOut.model_validate(product)


@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product_route(
    product_id: str,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("products:write")),
) -> ProductOut:
    product = await update_product(
        db,
        organization_id=user.organization_id,
        actor_id=user.user_id,
        product_id=product_id,
        payload=payload,
    )
    await db.commit()
    return ProductOut.model_validate(product)


@router.get("/products/{product_id}/timeline")
async def product_timeline(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("products:read")),
) -> list[dict]:
    rows = (
        await db.execute(
            select(EventLog)
            .where(
                EventLog.organization_id == uuid.UUID(user.organization_id),
                EventLog.aggregate_type == "product",
                EventLog.aggregate_id == product_id,
            )
            .order_by(EventLog.sequence_id.desc())
            .limit(100)
        )
    ).scalars().all()
    return [
        {
            "sequence_id": row.sequence_id,
            "event_id": str(row.event_id),
            "event_type": row.event_type,
            "payload": row.payload,
            "occurred_at": row.occurred_at,
        }
        for row in rows
    ]


@router.get("/products/{product_id}/overview")
async def product_overview(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("products:read")),
) -> dict:
    product = await get_product(db, organization_id=user.organization_id, product_id=product_id)
    balances = (
        await db.execute(
            select(InventoryBalance).where(
                InventoryBalance.organization_id == uuid.UUID(user.organization_id),
                InventoryBalance.product_id == uuid.UUID(product_id),
            )
        )
    ).scalars().all()
    on_hand = sum((b.on_hand for b in balances), Decimal("0"))
    reserved = sum((b.reserved for b in balances), Decimal("0"))
    lots = (
        await db.execute(
            select(InventoryLot).where(
                InventoryLot.organization_id == uuid.UUID(user.organization_id),
                InventoryLot.product_id == uuid.UUID(product_id),
                InventoryLot.quantity_remaining > 0,
            )
        )
    ).scalars().all()
    prices = await get_prices(db, organization_id=user.organization_id, product_id=product_id)
    incoming = await incoming_for_product(
        db, organization_id=user.organization_id, product_id=product_id
    )
    from app.domains.health.models import InventoryAlert

    alerts = (
        await db.execute(
            select(InventoryAlert)
            .where(
                InventoryAlert.organization_id == uuid.UUID(user.organization_id),
                InventoryAlert.product_id == uuid.UUID(product_id),
                InventoryAlert.status == "OPEN",
            )
            .order_by(InventoryAlert.severity)
        )
    ).scalars().all()
    timeline = (
        await db.execute(
            select(EventLog)
            .where(
                EventLog.organization_id == uuid.UUID(user.organization_id),
                EventLog.aggregate_type == "product",
                EventLog.aggregate_id == product_id,
            )
            .order_by(EventLog.sequence_id.desc())
            .limit(20)
        )
    ).scalars().all()
    return {
        "product": ProductOut.model_validate(product).model_dump(),
        "inventory": {
            "on_hand": on_hand,
            "reserved": reserved,
            "available": on_hand - reserved,
            "incoming": incoming,
            "lot_count": len(lots),
        },
        "prices": {
            "last_purchase_price": (
                prices["last_purchase_price"].price if prices["last_purchase_price"] else None
            ),
            "weighted_avg_cost": (
                prices["weighted_avg_cost"].price if prices["weighted_avg_cost"] else None
            ),
            "target_sell_price": (
                prices["target_sell_price"].price if prices["target_sell_price"] else None
            ),
            "actual_sell_price": (
                prices["actual_sell_price"].price if prices["actual_sell_price"] else None
            ),
        },
        "alerts": [
            {
                "id": str(a.id),
                "alert_type": a.alert_type,
                "severity": a.severity,
                "title": a.title,
                "evidence": a.evidence_json,
            }
            for a in alerts
        ],
        "timeline": [
            {
                "sequence_id": e.sequence_id,
                "event_type": e.event_type,
                "payload": e.payload,
                "occurred_at": e.occurred_at,
            }
            for e in timeline
        ],
    }
