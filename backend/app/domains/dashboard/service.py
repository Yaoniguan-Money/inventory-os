from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.models import Product
from app.domains.health.service import health_overview
from app.domains.integrations.models import EventLog
from app.domains.market.models import MarketQuote
from app.domains.orders.models import Customer, SalesOrder, SalesOrderLine
from app.domains.pricing.models import InternalPriceSnapshot
from app.domains.purchasing.models import PurchaseOrder, PurchaseOrderLine
from app.domains.warehouse.models import InventoryBalance


async def _latest_price(
    db: AsyncSession, organization_id: str, product_id: str, price_type: str
) -> Decimal | None:
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
    return snapshot.price if snapshot else None


async def _incoming_before(
    db: AsyncSession, organization_id: str, product_id: str, deadline: datetime | None
) -> Decimal:
    stmt = (
        select(PurchaseOrderLine)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(
            PurchaseOrder.organization_id == uuid.UUID(organization_id),
            PurchaseOrderLine.product_id == uuid.UUID(product_id),
            PurchaseOrder.status.in_(["CONFIRMED", "PARTIAL"]),
        )
    )
    if deadline is not None:
        stmt = stmt.where(
            (PurchaseOrderLine.expected_at <= deadline) | (PurchaseOrder.expected_at <= deadline)
        )
    lines = (await db.execute(stmt)).scalars().all()
    return sum((line.ordered_qty - line.received_qty for line in lines), Decimal("0"))


async def dashboard(db: AsyncSession, *, organization_id: str) -> dict:
    org_uuid = uuid.UUID(organization_id)
    now = datetime.now(UTC)
    horizon = now + timedelta(days=7)

    products = (
        await db.execute(select(Product).where(Product.organization_id == org_uuid))
    ).scalars().all()
    balances = (
        await db.execute(
            select(InventoryBalance).where(InventoryBalance.organization_id == org_uuid)
        )
    ).scalars().all()
    by_product: dict[str, list[InventoryBalance]] = {}
    for balance in balances:
        by_product.setdefault(str(balance.product_id), []).append(balance)

    inventory_value = Decimal("0")
    on_hand_units = Decimal("0")
    reserved_units = Decimal("0")
    sku_count = 0
    for product in products:
        product_balances = by_product.get(str(product.id), [])
        if not product_balances:
            continue
        on_hand = sum((b.on_hand for b in product_balances), Decimal("0"))
        reserved = sum((b.reserved for b in product_balances), Decimal("0"))
        on_hand_units += on_hand
        reserved_units += reserved
        sku_count += 1
        avg_cost = await _latest_price(
            db, organization_id, str(product.id), "WEIGHTED_AVG_COST"
        )
        if avg_cost is None:
            avg_cost = await _latest_price(
                db, organization_id, str(product.id), "LAST_PURCHASE_PRICE"
            )
        if avg_cost is not None:
            inventory_value += on_hand * avg_cost

    orders = (
        await db.execute(
            select(SalesOrder, Customer)
            .join(Customer, Customer.id == SalesOrder.customer_id)
            .where(
                SalesOrder.organization_id == org_uuid,
                SalesOrder.status.in_(["CONFIRMED", "PARTIAL"]),
            )
        )
    ).all()
    orders_due = sum(
        1
        for order, _ in orders
        if order.required_at is not None and order.required_at <= horizon
    )
    at_risk_orders = 0
    upcoming: list[dict] = []
    for order, customer in orders:
        lines = (
            await db.execute(
                select(SalesOrderLine).where(SalesOrderLine.sales_order_id == order.id)
            )
        ).scalars().all()
        order_risk = False
        remaining_total = Decimal("0")
        for line in lines:
            remaining = line.ordered_qty - line.delivered_qty
            remaining_total += remaining
            if remaining <= 0:
                continue
            product_balances = by_product.get(str(line.product_id), [])
            available = sum((b.on_hand - b.reserved for b in product_balances), Decimal("0"))
            deadline = line.required_at or order.required_at
            incoming = await _incoming_before(
                db, organization_id, str(line.product_id), deadline
            )
            if remaining > available + incoming:
                order_risk = True
        if order_risk:
            at_risk_orders += 1
        upcoming.append(
            {
                "id": str(order.id),
                "order_no": order.order_no,
                "customer_name": customer.name,
                "required_at": order.required_at,
                "status": order.status,
                "remaining_total": str(remaining_total),
            }
        )
    upcoming.sort(
        key=lambda item: (
            item["required_at"] is None,
            item["required_at"] or datetime.max.replace(tzinfo=UTC),
        )
    )
    upcoming = upcoming[:8]

    pressure_7d: list[dict] = []
    for product in products:
        product_balances = by_product.get(str(product.id), [])
        available = sum((b.on_hand - b.reserved for b in product_balances), Decimal("0"))
        demand_rows = (
            await db.execute(
                select(SalesOrderLine, SalesOrder)
                .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
                .where(
                    SalesOrder.organization_id == org_uuid,
                    SalesOrderLine.product_id == product.id,
                    SalesOrder.status.in_(["CONFIRMED", "PARTIAL"]),
                    (SalesOrderLine.required_at <= horizon) | (SalesOrder.required_at <= horizon),
                )
            )
        ).all()
        due_demand = sum(
            (line.ordered_qty - line.delivered_qty for line, _ in demand_rows), Decimal("0")
        )
        incoming = await _incoming_before(db, organization_id, str(product.id), horizon)
        shortage = due_demand - available - incoming
        if shortage > 0:
            pressure_7d.append(
                {
                    "product_id": str(product.id),
                    "sku": product.sku,
                    "name": product.name,
                    "due_demand": str(due_demand),
                    "available": str(available),
                    "incoming": str(incoming),
                    "shortage": str(shortage),
                }
            )

    health = await health_overview(db, organization_id=organization_id)
    market_anomalies: list[dict] = []
    for product_health in health["products"]:
        for alert in product_health["alerts"]:
            if alert.alert_type == "PRICE_PRESSURE":
                market_anomalies.append(
                    {
                        "product_id": str(product_health["product_id"]),
                        "sku": product_health["sku"],
                        "name": product_health["name"],
                        "title": alert.title,
                        "evidence": alert.evidence_json,
                    }
                )
    if not market_anomalies:
        for product in products:
            product_balances = by_product.get(str(product.id), [])
            if not product_balances:
                continue
            avg_cost = await _latest_price(
                db, organization_id, str(product.id), "WEIGHTED_AVG_COST"
            )
            quote = (
                await db.execute(
                    select(MarketQuote)
                    .where(
                        MarketQuote.organization_id == org_uuid,
                        MarketQuote.product_id == product.id,
                        MarketQuote.quote_kind == "MARKET_BUY",
                    )
                    .order_by(MarketQuote.observed_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if avg_cost and quote and avg_cost > 0:
                ratio = (avg_cost - quote.price) / avg_cost
                if ratio > Decimal("0.1"):
                    market_anomalies.append(
                        {
                            "product_id": str(product.id),
                            "sku": product.sku,
                            "name": product.name,
                            "title": "市场采购价明显低于当前平均成本",
                            "evidence": {
                                "weighted_avg_cost": str(avg_cost),
                                "market_buy": str(quote.price),
                            },
                        }
                    )

    events = (
        await db.execute(
            select(EventLog)
            .where(EventLog.organization_id == org_uuid)
            .order_by(EventLog.sequence_id.desc())
            .limit(10)
        )
    ).scalars().all()
    return {
        "inventory_value": str(inventory_value),
        "on_hand_units": str(on_hand_units),
        "sku_count": sku_count,
        "reserved_units": str(reserved_units),
        "orders_due": orders_due,
        "at_risk_orders": at_risk_orders,
        "health_score": health["org_score"],
        "health_by_severity": health["by_severity"],
        "health_by_type": health["by_type"],
        "pressure_7d": pressure_7d,
        "upcoming_orders": upcoming,
        "market_anomalies": market_anomalies,
        "recent_events": [
            {
                "sequence_id": event.sequence_id,
                "event_type": event.event_type,
                "occurred_at": event.occurred_at,
                "payload": event.payload,
            }
            for event in events
        ],
    }
