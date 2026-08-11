from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import record_event
from app.domains.catalog.models import Product
from app.domains.integrations.models import InboundEvent
from app.domains.warehouse.models import Warehouse
from app.domains.warehouse.service import adjust_stock, receive_stock


async def process_integration_event(
    db: AsyncSession,
    *,
    organization_id: str,
    source: str,
    event_id: str,
    event_type: str,
    occurred_at: datetime | None,
    data: dict,
) -> str:
    """Process one external event idempotently. Returns accepted|duplicate."""

    existing = (
        await db.execute(
            select(InboundEvent).where(
                InboundEvent.organization_id == uuid.UUID(organization_id),
                InboundEvent.source == source,
                InboundEvent.event_id == event_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return "duplicate"

    occurred = occurred_at or datetime.now(UTC)
    expires_at = None
    if data.get("expires_at"):
        try:
            expires_at = datetime.fromisoformat(str(data["expires_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("data.expires_at 格式无效（需要 ISO 时间）") from exc
    if event_type == "inventory.received":
        product = await _require_product(db, organization_id, data.get("sku"))
        warehouse = await _require_warehouse(db, organization_id, data.get("warehouse"))
        quantity = Decimal(str(data.get("quantity", "0")))
        if quantity <= 0:
            raise ValueError("data.quantity 必须大于 0")
        unit_price = (
            Decimal(str(data["unit_price"])) if data.get("unit_price") is not None else None
        )
        await receive_stock(
            db,
            organization_id=organization_id,
            actor_id=None,
            product_id=str(product.id),
            warehouse_id=str(warehouse.id),
            location_id=None,
            quantity=quantity,
            unit_cost=unit_price,
            lot_code=data.get("lot_code"),
            expires_at=expires_at,
            supplier_id=None,
            purchase_order_line_id=None,
            reason=f"外部事件 {source}:{event_id}",
            occurred_at=occurred,
        )
    elif event_type == "inventory.adjusted":
        product = await _require_product(db, organization_id, data.get("sku"))
        warehouse = await _require_warehouse(db, organization_id, data.get("warehouse"))
        quantity = Decimal(str(data.get("quantity", "0")))
        if quantity == 0:
            raise ValueError("data.quantity 不能为 0")
        await adjust_stock(
            db,
            organization_id=organization_id,
            actor_id=None,
            product_id=str(product.id),
            warehouse_id=str(warehouse.id),
            quantity=quantity,
            reason=f"外部事件 {source}:{event_id}",
        )
    else:
        raise ValueError(f"不支持的事件类型: {event_type}")

    inbound = InboundEvent(
        organization_id=uuid.UUID(organization_id),
        event_id=event_id,
        source=source,
        event_type=event_type,
        status="ACCEPTED",
        payload=data,
        processed_at=datetime.now(UTC),
    )
    db.add(inbound)
    record_event(
        db,
        organization_id=organization_id,
        event_type=f"integrations.{event_type}",
        aggregate_type="integration",
        aggregate_id=f"{source}:{event_id}",
        payload={"source": source, "event_id": event_id, "data": data},
        occurred_at=occurred,
    )
    return "accepted"


async def _require_product(db: AsyncSession, organization_id: str, sku) -> Product:
    if not sku:
        raise ValueError("data.sku 缺失")
    product = (
        await db.execute(
            select(Product).where(
                Product.organization_id == uuid.UUID(organization_id),
                Product.sku == str(sku),
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise ValueError(f"SKU 不存在: {sku}")
    return product


async def _require_warehouse(db: AsyncSession, organization_id: str, code) -> Warehouse:
    if not code:
        raise ValueError("data.warehouse 缺失")
    warehouse = (
        await db.execute(
            select(Warehouse).where(
                Warehouse.organization_id == uuid.UUID(organization_id),
                Warehouse.code == str(code),
            )
        )
    ).scalar_one_or_none()
    if warehouse is None:
        raise ValueError(f"仓库编码不存在: {code}")
    return warehouse
