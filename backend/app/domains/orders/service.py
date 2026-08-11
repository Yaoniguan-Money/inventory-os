from __future__ import annotations

import random
import string
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.errors import ConflictError, InsufficientStockError, NotFoundError, ValidationFailureError
from app.core.events import record_event
from app.domains.catalog.models import Product
from app.domains.orders.models import (
    Customer,
    Delivery,
    DeliveryLine,
    InventoryReservation,
    SalesOrder,
    SalesOrderLine,
)
from app.domains.pricing.service import record_price_snapshot
from app.domains.purchasing.models import PurchaseOrder, PurchaseOrderLine
from app.domains.warehouse.models import InventoryLot, StockMovement, Warehouse
from app.domains.warehouse.service import get_balance_locked, latest_snapshot


def _order_no(db: AsyncSession, organization_id: str, prefix: str = "SO") -> str:
    today = datetime.now(UTC).strftime("%Y%m%d")
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{prefix}-{today}-{suffix}"


async def get_order(
    db: AsyncSession, *, organization_id: str, order_id: str, for_update: bool = False
) -> SalesOrder:
    stmt = select(SalesOrder).where(
        SalesOrder.id == uuid.UUID(order_id),
        SalesOrder.organization_id == uuid.UUID(organization_id),
    )
    if for_update:
        stmt = stmt.with_for_update()
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise NotFoundError("订单不存在")
    return order


def order_out(order: SalesOrder, customer: Customer, lines: list[SalesOrderLine], products: dict[str, Product]) -> dict:
    return {
        "id": order.id,
        "order_no": order.order_no,
        "customer_id": order.customer_id,
        "customer_name": customer.name,
        "status": order.status,
        "ordered_at": order.ordered_at,
        "required_at": order.required_at,
        "currency": order.currency,
        "notes": order.notes,
        "created_at": order.created_at,
        "lines": [
            {
                "id": line.id,
                "product_id": line.product_id,
                "sku": products[str(line.product_id)].sku,
                "name": products[str(line.product_id)].name,
                "ordered_qty": line.ordered_qty,
                "reserved_qty": line.reserved_qty,
                "delivered_qty": line.delivered_qty,
                "remaining_qty": line.ordered_qty - line.delivered_qty,
                "unit_sell_price": line.unit_sell_price,
                "required_at": line.required_at,
            }
            for line in lines
        ],
    }


async def build_order_out(db: AsyncSession, organization_id: str, order: SalesOrder) -> dict:
    customer = await db.get(Customer, order.customer_id)
    if customer is None:
        raise NotFoundError("客户不存在")
    lines = (
        await db.execute(
            select(SalesOrderLine).where(SalesOrderLine.sales_order_id == order.id)
        )
    ).scalars().all()
    product_ids = {str(line.product_id) for line in lines}
    products = {
        str(p.id): p
        for p in (
            await db.execute(select(Product).where(Product.id.in_([uuid.UUID(x) for x in product_ids])))
        ).scalars()
    }
    return order_out(order, customer, list(lines), products)


async def create_sales_order(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    payload,
) -> SalesOrder:
    customer = (
        await db.execute(
            select(Customer).where(
                Customer.id == payload.customer_id,
                Customer.organization_id == uuid.UUID(organization_id),
            )
        )
    ).scalar_one_or_none()
    if customer is None:
        raise NotFoundError("客户不存在")

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

    order = SalesOrder(
        organization_id=uuid.UUID(organization_id),
        order_no=_order_no(db, organization_id),
        customer_id=payload.customer_id,
        status="DRAFT",
        ordered_at=payload.ordered_at or datetime.now(UTC),
        required_at=payload.required_at,
        currency=payload.currency,
        notes=payload.notes,
        created_by=uuid.UUID(actor_id),
    )
    db.add(order)
    await db.flush()
    for line in payload.lines:
        db.add(
            SalesOrderLine(
                sales_order_id=order.id,
                product_id=line.product_id,
                ordered_qty=line.ordered_qty,
                reserved_qty=Decimal("0"),
                delivered_qty=Decimal("0"),
                unit_sell_price=line.unit_sell_price,
                required_at=line.required_at,
            )
        )
    await db.flush()
    record_event(
        db,
        organization_id=organization_id,
        event_type="orders.order.created",
        aggregate_type="order",
        aggregate_id=str(order.id),
        payload={
            "order_no": order.order_no,
            "customer_id": str(order.customer_id),
            "lines": [
                {"product_id": str(line.product_id), "ordered_qty": str(line.ordered_qty)}
                for line in payload.lines
            ],
        },
        occurred_at=order.ordered_at,
    )
    for line in payload.lines:
        record_event(
            db,
            organization_id=organization_id,
            event_type="orders.line.created",
            aggregate_type="product",
            aggregate_id=str(line.product_id),
            payload={"order_id": str(order.id), "ordered_qty": str(line.ordered_qty)},
            occurred_at=order.ordered_at,
        )
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="order.create",
        entity_type="order",
        entity_id=str(order.id),
        after_json={"order_no": order.order_no, "customer_id": str(order.customer_id)},
    )
    return order


async def confirm_order(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    order_id: str,
) -> tuple[SalesOrder, list[dict]]:
    order = await get_order(db, organization_id=organization_id, order_id=order_id, for_update=True)
    if order.status != "DRAFT":
        raise ConflictError(f"订单当前状态不可确认: {order.status}")
    lines = (
        await db.execute(
            select(SalesOrderLine).where(SalesOrderLine.sales_order_id == order.id)
        )
    ).scalars().all()

    shortages: list[dict] = []
    # Validate all lines first (availability check with locks).
    for line in lines:
        product = await db.get(Product, line.product_id)
        if product is None:
            raise NotFoundError("商品不存在")
        warehouse = await _default_warehouse(db, organization_id, product)
        balance = await get_balance_locked(
            db,
            organization_id=organization_id,
            product_id=str(line.product_id),
            warehouse_id=str(warehouse.id),
        )
        available = balance.on_hand - balance.reserved
        if available < line.ordered_qty:
            incoming = await _incoming_before(
                db,
                organization_id,
                str(line.product_id),
                line.required_at or order.required_at,
            )
            shortages.append(
                {
                    "product_id": str(line.product_id),
                    "sku": product.sku,
                    "ordered_qty": str(line.ordered_qty),
                    "available": str(available),
                    "shortage": str(line.ordered_qty - available),
                    "incoming": str(incoming),
                }
            )
    if shortages:
        raise InsufficientStockError(
            "可用库存不足，无法确认订单",
            details={"shortages": shortages},
        )

    for line in lines:
        product = await db.get(Product, line.product_id)
        if product is None:
            raise NotFoundError("商品不存在")
        warehouse = await _default_warehouse(db, organization_id, product)
        balance = await get_balance_locked(
            db,
            organization_id=organization_id,
            product_id=str(line.product_id),
            warehouse_id=str(warehouse.id),
        )
        balance.reserved += line.ordered_qty
        balance.version += 1
        line.reserved_qty = line.ordered_qty
        reservation = InventoryReservation(
            organization_id=uuid.UUID(organization_id),
            sales_order_line_id=line.id,
            product_id=line.product_id,
            warehouse_id=warehouse.id,
            quantity=line.ordered_qty,
            status="ACTIVE",
        )
        db.add(reservation)
        if line.unit_sell_price is not None:
            record_price_snapshot(
                db,
                organization_id=organization_id,
                product_id=str(line.product_id),
                price_type="ACTUAL_SELL_PRICE",
                price=line.unit_sell_price,
                currency=order.currency,
                source_reference_type="SALES_ORDER_LINE",
                source_reference_id=str(line.id),
            )
        record_event(
            db,
            organization_id=organization_id,
            event_type="orders.order.confirmed",
            aggregate_type="order",
            aggregate_id=str(order.id),
            payload={
                "product_id": str(line.product_id),
                "quantity": str(line.ordered_qty),
                "warehouse_id": str(warehouse.id),
            },
        )
        record_event(
            db,
            organization_id=organization_id,
            event_type="inventory.reserved",
            aggregate_type="product",
            aggregate_id=str(line.product_id),
            payload={
                "order_id": str(order.id),
                "quantity": str(line.ordered_qty),
                "reserved": str(balance.reserved),
                "available": str(balance.on_hand - balance.reserved),
            },
        )
    order.status = "CONFIRMED"
    await db.flush()
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="order.confirm",
        entity_type="order",
        entity_id=str(order.id),
        after_json={"status": "CONFIRMED"},
    )
    return order, shortages


async def _default_warehouse(db: AsyncSession, organization_id: str, product: Product) -> Warehouse:
    if product.default_warehouse_id:
        warehouse = await db.get(Warehouse, product.default_warehouse_id)
        if warehouse is not None:
            return warehouse
    warehouse = (
        await db.execute(
            select(Warehouse).where(Warehouse.organization_id == uuid.UUID(organization_id))
            .order_by(Warehouse.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if warehouse is None:
        raise NotFoundError("尚未创建仓库，无法确认订单")
    return warehouse


async def _incoming_before(
    db: AsyncSession,
    organization_id: str,
    product_id: str,
    deadline: datetime | None,
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


async def fulfill_order(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    order_id: str,
    fulfill_lines: list[dict],
) -> SalesOrder:
    order = await get_order(db, organization_id=organization_id, order_id=order_id, for_update=True)
    if order.status not in ("CONFIRMED", "PARTIAL"):
        raise ConflictError(f"订单当前状态不可交付: {order.status}")

    line_ids = [uuid.UUID(str(x["sales_order_line_id"])) for x in fulfill_lines]
    lines = (
        await db.execute(
            select(SalesOrderLine).where(
                SalesOrderLine.sales_order_id == order.id,
                SalesOrderLine.id.in_(line_ids),
            )
        )
    ).scalars().all()
    by_id = {str(line.id): line for line in lines}
    for item in fulfill_lines:
        line = by_id.get(str(item["sales_order_line_id"]))
        if line is None:
            raise NotFoundError(f"订单行不存在: {item['sales_order_line_id']}")
        qty = Decimal(item["quantity"])
        remaining = line.ordered_qty - line.delivered_qty
        if qty > line.reserved_qty:
            raise InsufficientStockError(
                "交付数量超过已预留数量",
                details={
                    "sales_order_line_id": str(line.id),
                    "reserved": str(line.reserved_qty),
                    "requested": str(qty),
                },
            )
        if qty > remaining:
            raise ValidationFailureError(
                "交付数量超过订单剩余数量",
                details={"remaining": str(remaining), "requested": str(qty)},
            )

    delivery = Delivery(
        organization_id=uuid.UUID(organization_id),
        sales_order_id=order.id,
        delivery_no=_order_no(db, organization_id, prefix="DLV"),
        delivered_at=datetime.now(UTC),
        status="SHIPPED",
        created_by=uuid.UUID(actor_id),
    )
    db.add(delivery)
    await db.flush()

    for item in fulfill_lines:
        line = by_id[str(item["sales_order_line_id"])]
        qty = Decimal(item["quantity"])
        product = await db.get(Product, line.product_id)
        if product is None:
            raise NotFoundError("商品不存在")
        warehouse = await _default_warehouse(db, organization_id, product)
        balance = await get_balance_locked(
            db,
            organization_id=organization_id,
            product_id=str(line.product_id),
            warehouse_id=str(warehouse.id),
        )
        if balance.on_hand < qty:
            raise InsufficientStockError(
                "实物库存不足",
                details={"on_hand": str(balance.on_hand), "requested": str(qty)},
            )

        movements, unit_cost = await _consume_lots(
            db,
            organization_id=organization_id,
            product_id=str(line.product_id),
            warehouse_id=str(warehouse.id),
            quantity=qty,
            actor_id=actor_id,
            delivery_id=str(delivery.id),
        )
        balance.on_hand -= qty
        balance.reserved -= qty
        balance.version += 1
        line.reserved_qty -= qty
        line.delivered_qty += qty

        reservation = (
            await db.execute(
                select(InventoryReservation)
                .where(
                    InventoryReservation.sales_order_line_id == line.id,
                    InventoryReservation.status == "ACTIVE",
                )
                .with_for_update()
            )
        ).scalars().first()
        if reservation is not None:
            reservation.quantity -= qty
            if reservation.quantity <= 0:
                reservation.status = "CONSUMED"

        snapshot_cost = unit_cost
        if snapshot_cost is None:
            avg = await latest_snapshot(
                db, organization_id=organization_id, product_id=str(line.product_id), price_type="WEIGHTED_AVG_COST"
            )
            snapshot_cost = avg.price if avg else None
        db.add(
            DeliveryLine(
                delivery_id=delivery.id,
                sales_order_line_id=line.id,
                product_id=line.product_id,
                quantity=qty,
                stock_movement_id=movements[0].id if movements else None,
                unit_cost_snapshot=snapshot_cost,
                unit_sell_price_snapshot=line.unit_sell_price,
            )
        )
        record_event(
            db,
            organization_id=organization_id,
            event_type="inventory.shipped",
            aggregate_type="product",
            aggregate_id=str(line.product_id),
            payload={
                "order_id": str(order.id),
                "delivery_id": str(delivery.id),
                "quantity": str(qty),
                "on_hand": str(balance.on_hand),
                "reserved": str(balance.reserved),
            },
        )

    all_lines = (
        await db.execute(select(SalesOrderLine).where(SalesOrderLine.sales_order_id == order.id))
    ).scalars().all()
    remaining_total = sum(
        (line.ordered_qty - line.delivered_qty for line in all_lines), Decimal("0")
    )
    order.status = "FULFILLED" if remaining_total == 0 else "PARTIAL"
    await db.flush()
    record_event(
        db,
        organization_id=organization_id,
        event_type="orders.order.fulfilled" if order.status == "FULFILLED" else "orders.order.partial",
        aggregate_type="order",
        aggregate_id=str(order.id),
        payload={"delivery_id": str(delivery.id), "status": order.status},
    )
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="order.fulfill",
        entity_type="order",
        entity_id=str(order.id),
        after_json={"status": order.status, "delivery_id": str(delivery.id)},
    )
    return order


async def _consume_lots(
    db: AsyncSession,
    *,
    organization_id: str,
    product_id: str,
    warehouse_id: str,
    quantity: Decimal,
    actor_id: str,
    delivery_id: str,
) -> tuple[list[StockMovement], Decimal | None]:
    lots = (
        await db.execute(
            select(InventoryLot)
            .where(
                InventoryLot.organization_id == uuid.UUID(organization_id),
                InventoryLot.product_id == uuid.UUID(product_id),
                InventoryLot.warehouse_id == uuid.UUID(warehouse_id),
                InventoryLot.quantity_remaining > 0,
            )
            .order_by(InventoryLot.received_at, InventoryLot.expires_at)
            .with_for_update()
        )
    ).scalars().all()
    to_consume = quantity
    movements: list[StockMovement] = []
    first_cost: Decimal | None = None
    for lot in lots:
        if to_consume <= 0:
            break
        take = min(lot.quantity_remaining, to_consume)
        lot.quantity_remaining -= take
        to_consume -= take
        movement = StockMovement(
            organization_id=uuid.UUID(organization_id),
            product_id=uuid.UUID(product_id),
            warehouse_id=uuid.UUID(warehouse_id),
            location_id=lot.location_id,
            lot_id=lot.id,
            movement_type="SHIPMENT",
            quantity=-take,
            unit_cost=lot.unit_cost,
            reference_type="DELIVERY",
            reference_id=delivery_id,
            occurred_at=datetime.now(UTC),
            created_by=uuid.UUID(actor_id),
        )
        db.add(movement)
        movements.append(movement)
        if first_cost is None:
            first_cost = lot.unit_cost
    if to_consume > 0:
        if not movements:
            movement = StockMovement(
                organization_id=uuid.UUID(organization_id),
                product_id=uuid.UUID(product_id),
                warehouse_id=uuid.UUID(warehouse_id),
                movement_type="SHIPMENT",
                quantity=-to_consume,
                reference_type="DELIVERY",
                reference_id=delivery_id,
                occurred_at=datetime.now(UTC),
                created_by=uuid.UUID(actor_id),
            )
            db.add(movement)
            movements.append(movement)
        else:
            raise InsufficientStockError(
                "批次库存不足",
                details={"shortage": str(to_consume)},
            )
    await db.flush()
    return movements, first_cost


async def cancel_order(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    order_id: str,
) -> SalesOrder:
    order = await get_order(db, organization_id=organization_id, order_id=order_id, for_update=True)
    if order.status in ("FULFILLED", "CANCELLED"):
        raise ConflictError(f"订单当前状态不可取消: {order.status}")
    lines = (
        await db.execute(select(SalesOrderLine).where(SalesOrderLine.sales_order_id == order.id))
    ).scalars().all()
    for line in lines:
        if line.reserved_qty <= 0:
            continue
        product = await db.get(Product, line.product_id)
        if product is None:
            raise NotFoundError("商品不存在")
        warehouse = await _default_warehouse(db, organization_id, product)
        balance = await get_balance_locked(
            db,
            organization_id=organization_id,
            product_id=str(line.product_id),
            warehouse_id=str(warehouse.id),
        )
        balance.reserved -= line.reserved_qty
        balance.version += 1
        reservations = (
            await db.execute(
                select(InventoryReservation).where(
                    InventoryReservation.sales_order_line_id == line.id,
                    InventoryReservation.status == "ACTIVE",
                )
                .with_for_update()
            )
        ).scalars().all()
        now = datetime.now(UTC)
        for reservation in reservations:
            reservation.status = "RELEASED"
            reservation.released_at = now
            reservation.quantity = Decimal("0")
        line.reserved_qty = Decimal("0")
        record_event(
            db,
            organization_id=organization_id,
            event_type="inventory.reservation.released",
            aggregate_type="product",
            aggregate_id=str(line.product_id),
            payload={
                "order_id": str(order.id),
                "quantity": str(line.ordered_qty - line.delivered_qty),
                "reserved": str(balance.reserved),
            },
        )
    order.status = "CANCELLED"
    await db.flush()
    record_event(
        db,
        organization_id=organization_id,
        event_type="orders.order.cancelled",
        aggregate_type="order",
        aggregate_id=str(order.id),
        payload={"order_no": order.order_no},
    )
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="order.cancel",
        entity_type="order",
        entity_id=str(order.id),
        after_json={"status": "CANCELLED"},
    )
    return order


async def list_customer_orders(db: AsyncSession, *, organization_id: str) -> list[SalesOrder]:
    rows = (
        await db.execute(
            select(SalesOrder)
            .where(SalesOrder.organization_id == uuid.UUID(organization_id))
            .order_by(SalesOrder.ordered_at.desc())
        )
    ).scalars().all()
    return list(rows)
