from __future__ import annotations

import random
import string
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.errors import ConflictError, NotFoundError, ValidationFailureError
from app.core.events import record_event
from app.domains.catalog.models import Product
from app.domains.market.models import MarketEvent, MarketQuote
from app.domains.orders.models import SalesOrder, SalesOrderLine
from app.domains.purchasing.models import PurchaseOrder, PurchaseOrderLine, Supplier
from app.domains.warehouse.models import InventoryBalance, StockMovement, Warehouse
from app.domains.warehouse.service import expired_lot_quantity, latest_snapshot, receive_stock


def _po_no() -> str:
    today = datetime.now(UTC).strftime("%Y%m%d")
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PO-{today}-{suffix}"


async def get_purchase_order(
    db: AsyncSession, *, organization_id: str, po_id: str, for_update: bool = False
) -> PurchaseOrder:
    stmt = select(PurchaseOrder).where(
        PurchaseOrder.id == uuid.UUID(po_id),
        PurchaseOrder.organization_id == uuid.UUID(organization_id),
    )
    if for_update:
        stmt = stmt.with_for_update()
    po = (await db.execute(stmt)).scalar_one_or_none()
    if po is None:
        raise NotFoundError("采购订单不存在")
    return po


async def build_po_out(db: AsyncSession, organization_id: str, po: PurchaseOrder) -> dict:
    supplier = await db.get(Supplier, po.supplier_id)
    lines = (
        await db.execute(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id))
    ).scalars().all()
    product_ids = {str(line.product_id) for line in lines}
    products = {
        str(p.id): p
        for p in (
            await db.execute(select(Product).where(Product.id.in_([uuid.UUID(x) for x in product_ids])))
        ).scalars()
    }
    return {
        "id": po.id,
        "po_no": po.po_no,
        "supplier_id": po.supplier_id,
        "supplier_name": supplier.name if supplier else "",
        "status": po.status,
        "ordered_at": po.ordered_at,
        "expected_at": po.expected_at,
        "currency": po.currency,
        "lines": [
            {
                "id": line.id,
                "product_id": line.product_id,
                "sku": products[str(line.product_id)].sku,
                "name": products[str(line.product_id)].name,
                "ordered_qty": line.ordered_qty,
                "received_qty": line.received_qty,
                "incoming_qty": (
                    Decimal("0") if po.status == "DRAFT" else line.ordered_qty - line.received_qty
                ),
                "unit_purchase_price": line.unit_purchase_price,
                "expected_at": line.expected_at,
            }
            for line in lines
        ],
    }


async def create_purchase_order(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    payload,
) -> PurchaseOrder:
    supplier = (
        await db.execute(
            select(Supplier).where(
                Supplier.id == payload.supplier_id,
                Supplier.organization_id == uuid.UUID(organization_id),
            )
        )
    ).scalar_one_or_none()
    if supplier is None:
        raise NotFoundError("供应商不存在")
    product_ids = [str(line.product_id) for line in payload.lines]
    products = (
        await db.execute(
            select(Product).where(
                Product.organization_id == uuid.UUID(organization_id),
                Product.id.in_([uuid.UUID(x) for x in product_ids]),
            )
        )
    ).scalars().all()
    found = {str(p.id) for p in products}
    missing = [pid for pid in product_ids if pid not in found]
    if missing:
        raise NotFoundError(f"商品不存在: {missing}")

    po = PurchaseOrder(
        organization_id=uuid.UUID(organization_id),
        po_no=_po_no(),
        supplier_id=payload.supplier_id,
        status="DRAFT",
        ordered_at=payload.ordered_at or datetime.now(UTC),
        expected_at=payload.expected_at,
        currency=payload.currency,
        created_by=uuid.UUID(actor_id),
    )
    db.add(po)
    await db.flush()
    for line in payload.lines:
        db.add(
            PurchaseOrderLine(
                purchase_order_id=po.id,
                product_id=line.product_id,
                ordered_qty=line.ordered_qty,
                received_qty=Decimal("0"),
                unit_purchase_price=line.unit_purchase_price,
                expected_at=line.expected_at,
            )
        )
    await db.flush()
    record_event(
        db,
        organization_id=organization_id,
        event_type="purchasing.po.created",
        aggregate_type="purchase_order",
        aggregate_id=str(po.id),
        payload={"po_no": po.po_no, "supplier_id": str(po.supplier_id)},
    )
    for line in payload.lines:
        record_event(
            db,
            organization_id=organization_id,
            event_type="purchasing.incoming.planned",
            aggregate_type="product",
            aggregate_id=str(line.product_id),
            payload={"po_id": str(po.id), "quantity": str(line.ordered_qty)},
        )
    return po


async def confirm_purchase_order(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    po_id: str,
) -> PurchaseOrder:
    po = await get_purchase_order(db, organization_id=organization_id, po_id=po_id, for_update=True)
    if po.status != "DRAFT":
        raise ConflictError(f"采购订单当前状态不可确认: {po.status}")
    po.status = "CONFIRMED"
    await db.flush()
    lines = (
        await db.execute(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id))
    ).scalars().all()
    for line in lines:
        record_event(
            db,
            organization_id=organization_id,
            event_type="purchasing.incoming.confirmed",
            aggregate_type="product",
            aggregate_id=str(line.product_id),
            payload={
                "po_id": str(po.id),
                "quantity": str(line.ordered_qty - line.received_qty),
            },
        )
    record_event(
        db,
        organization_id=organization_id,
        event_type="purchasing.po.confirmed",
        aggregate_type="purchase_order",
        aggregate_id=str(po.id),
        payload={"po_no": po.po_no},
    )
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="purchase.confirm",
        entity_type="purchase_order",
        entity_id=str(po.id),
        after_json={"status": "CONFIRMED"},
    )
    return po


async def receive_purchase_order(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    po_id: str,
    receive_lines: list[dict],
) -> PurchaseOrder:
    po = await get_purchase_order(db, organization_id=organization_id, po_id=po_id, for_update=True)
    if po.status not in ("CONFIRMED", "PARTIAL"):
        raise ConflictError(f"采购订单当前状态不可收货: {po.status}")
    lines = {
        str(line.id): line
        for line in (
            await db.execute(select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == po.id))
        ).scalars()
    }
    supplier = await db.get(Supplier, po.supplier_id)

    for item in receive_lines:
        line = lines.get(str(item["purchase_order_line_id"]))
        if line is None:
            raise NotFoundError(f"采购行不存在: {item['purchase_order_line_id']}")
        qty = Decimal(item["quantity"])
        if qty <= 0:
            raise ValidationFailureError("收货数量必须大于 0")
        if line.received_qty + qty > line.ordered_qty:
            raise ValidationFailureError(
                "收货数量超过订单剩余数量",
                details={
                    "purchase_order_line_id": str(line.id),
                    "remaining": str(line.ordered_qty - line.received_qty),
                },
            )

    for item in receive_lines:
        line = lines[str(item["purchase_order_line_id"])]
        qty = Decimal(item["quantity"])
        await receive_stock(
            db,
            organization_id=organization_id,
            actor_id=actor_id,
            product_id=str(line.product_id),
            warehouse_id=str(
                await line_product_default_warehouse(db, organization_id, str(line.product_id))
            ),
            location_id=item.get("location_id"),
            quantity=qty,
            unit_cost=line.unit_purchase_price,
            lot_code=item.get("lot_code"),
            expires_at=item.get("expires_at"),
            supplier_id=str(supplier.id) if supplier else None,
            purchase_order_line_id=str(line.id),
            reason=f"采购订单 {po.po_no} 到货",
        )
        line.received_qty += qty

    all_lines = list(lines.values())
    po.status = "RECEIVED" if all(line.received_qty == line.ordered_qty for line in all_lines) else "PARTIAL"
    await db.flush()
    record_event(
        db,
        organization_id=organization_id,
        event_type="purchasing.po.received",
        aggregate_type="purchase_order",
        aggregate_id=str(po.id),
        payload={"po_no": po.po_no, "status": po.status},
    )
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="purchase.receive",
        entity_type="purchase_order",
        entity_id=str(po.id),
        after_json={"status": po.status},
    )
    return po


async def line_product_default_warehouse(db: AsyncSession, organization_id: str, product_id: str) -> uuid.UUID:
    product = await db.get(Product, product_id)
    if product is None:
        raise NotFoundError("商品不存在")
    if product.default_warehouse_id:
        return product.default_warehouse_id
    warehouse = (
        await db.execute(
            select(Warehouse).where(Warehouse.organization_id == uuid.UUID(organization_id))
            .order_by(Warehouse.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if warehouse is None:
        raise NotFoundError("尚未创建仓库，无法收货")
    return warehouse.id


async def incoming_for_product(
    db: AsyncSession, *, organization_id: str, product_id: str, before: datetime | None = None
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
    if before is not None:
        stmt = stmt.where(
                func.coalesce(PurchaseOrderLine.expected_at, PurchaseOrder.expected_at) <= before
        )
    lines = (await db.execute(stmt)).scalars().all()
    return sum((line.ordered_qty - line.received_qty for line in lines), Decimal("0"))


async def workbench(db: AsyncSession, *, organization_id: str) -> list[dict]:
    products = (
        await db.execute(
            select(Product).where(Product.organization_id == uuid.UUID(organization_id))
            .order_by(Product.sku)
        )
    ).scalars().all()
    now = datetime.now(UTC)
    horizon = now + timedelta(days=7)
    items: list[dict] = []
    for product in products:
        pid = str(product.id)
        market_quotes: dict[str, dict] = {"DOMESTIC": {}, "INTERNATIONAL": {}}
        quotes = (
            await db.execute(
                select(MarketQuote)
                .where(
                    MarketQuote.organization_id == uuid.UUID(organization_id),
                    MarketQuote.product_id == product.id,
                )
                .order_by(MarketQuote.observed_at.desc())
            )
        ).scalars().all()
        for quote in quotes:
            region_quotes = market_quotes.setdefault(quote.region, {})
            if quote.quote_kind not in region_quotes:
                region_quotes[quote.quote_kind] = {
                    "price": str(quote.price),
                    "currency": quote.currency,
                    "source": quote.source,
                    "unit": quote.unit,
                    "basis": quote.basis,
                    "observed_at": quote.observed_at.isoformat(),
                }
        receipts = (
            await db.execute(
                select(StockMovement)
                .where(
                    StockMovement.organization_id == uuid.UUID(organization_id),
                    StockMovement.product_id == product.id,
                    StockMovement.movement_type == "RECEIPT",
                )
                .order_by(StockMovement.occurred_at.desc())
                .limit(10)
            )
        ).scalars().all()
        purchase_history = [
            {
                "date": movement.occurred_at.isoformat(),
                "quantity": str(movement.quantity),
                "unit_cost": str(movement.unit_cost) if movement.unit_cost is not None else None,
                "reference_id": movement.reference_id,
            }
            for movement in receipts
        ]
        market_events = (
            await db.execute(
                select(MarketEvent)
                .where(
                    MarketEvent.organization_id == uuid.UUID(organization_id),
                    MarketEvent.product_id == product.id,
                )
                .order_by(MarketEvent.published_at.desc())
                .limit(3)
            )
        ).scalars().all()
        market_events_out = [
            {
                "title": event.title,
                "source": event.source,
                "published_at": event.published_at.isoformat(),
            }
            for event in market_events
        ]
        balances = (
            await db.execute(
                select(InventoryBalance).where(
                    InventoryBalance.organization_id == uuid.UUID(organization_id),
                    InventoryBalance.product_id == product.id,
                )
            )
        ).scalars().all()
        on_hand = sum((b.on_hand for b in balances), Decimal("0"))
        reserved = sum((b.reserved for b in balances), Decimal("0"))
        expired_qty = await expired_lot_quantity(
            db, organization_id=organization_id, product_id=pid
        )
        available = max(on_hand - reserved - expired_qty, Decimal("0"))
        incoming = await incoming_for_product(db, organization_id=organization_id, product_id=pid)
        demand_lines = (
            await db.execute(
                select(SalesOrderLine)
                .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
                .where(
                    SalesOrder.organization_id == uuid.UUID(organization_id),
                    SalesOrderLine.product_id == product.id,
                    SalesOrder.status.in_(["CONFIRMED", "PARTIAL"]),
                func.coalesce(SalesOrderLine.required_at, SalesOrder.required_at) <= horizon,
                )
            )
        ).scalars().all()
        demand = sum((line.ordered_qty - line.delivered_qty for line in demand_lines), Decimal("0"))
        last_purchase = await latest_snapshot(
            db, organization_id=organization_id, product_id=pid, price_type="LAST_PURCHASE_PRICE"
        )
        avg_cost = await latest_snapshot(
            db, organization_id=organization_id, product_id=pid, price_type="WEIGHTED_AVG_COST"
        )
        po_rows = (
            await db.execute(
                select(PurchaseOrder, PurchaseOrderLine)
                .join(PurchaseOrderLine, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
                .where(
                    PurchaseOrder.organization_id == uuid.UUID(organization_id),
                    PurchaseOrderLine.product_id == product.id,
                    PurchaseOrder.status.in_(["CONFIRMED", "PARTIAL"]),
                )
                .order_by(PurchaseOrder.expected_at)
            )
        ).all()
        supplier_names: dict[str, str] = {}
        for po, _ in po_rows:
            supplier = await db.get(Supplier, po.supplier_id)
            if supplier is not None:
                supplier_names[str(po.supplier_id)] = supplier.name
        items.append(
            {
                "product_id": product.id,
                "sku": product.sku,
                "name": product.name,
                "on_hand": on_hand,
                "reserved": reserved,
                "available": available,
                "expired_qty": expired_qty,
                "projected": available + incoming,
                "incoming": incoming,
                "demand_7d": demand,
                "shortage_7d": max(demand - available - incoming, Decimal("0")),
                "last_purchase_price": last_purchase.price if last_purchase else None,
                "weighted_avg_cost": avg_cost.price if avg_cost else None,
                "market_quotes": market_quotes,
                "purchase_history": purchase_history,
                "market_events": market_events_out,
                "suppliers": [
                    {"supplier_id": sid, "name": name} for sid, name in supplier_names.items()
                ],
                "purchase_orders": [
                    {
                        "po_id": str(po.id),
                        "po_no": po.po_no,
                        "expected_at": po.expected_at,
                        "incoming": str(line.ordered_qty - line.received_qty),
                    }
                    for po, line in po_rows
                ],
            }
        )
    return items
