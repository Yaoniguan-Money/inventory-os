from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.errors import InsufficientStockError, NotFoundError, ValidationFailureError
from app.core.events import record_event
from app.domains.catalog.models import Product
from app.domains.pricing.models import InternalPriceSnapshot
from app.domains.purchasing.models import PurchaseOrder, PurchaseOrderLine
from app.domains.warehouse.models import (
    InventoryBalance,
    InventoryLot,
    Location,
    StockMovement,
    Warehouse,
)


async def get_warehouse(
    db: AsyncSession, *, organization_id: str, warehouse_id: str | uuid.UUID
) -> Warehouse:
    warehouse = (
        await db.execute(
            select(Warehouse).where(
                Warehouse.id == (uuid.UUID(warehouse_id) if isinstance(warehouse_id, str) else warehouse_id),
                Warehouse.organization_id == uuid.UUID(organization_id),
            )
        )
    ).scalar_one_or_none()
    if warehouse is None:
        raise NotFoundError("仓库不存在")
    return warehouse


async def expired_lot_quantity(
    db: AsyncSession,
    *,
    organization_id: str,
    product_id: str,
    warehouse_id: str | None = None,
    at: datetime | None = None,
) -> Decimal:
    """统计已过期（expires_at < now）且仍有正余量的批次数量。"""

    cutoff = at or datetime.now(UTC)
    stmt = select(InventoryLot).where(
        InventoryLot.organization_id == uuid.UUID(organization_id),
        InventoryLot.product_id == uuid.UUID(product_id),
        InventoryLot.quantity_remaining > 0,
        InventoryLot.expires_at.is_not(None),
        InventoryLot.expires_at < cutoff,
    )
    if warehouse_id:
        stmt = stmt.where(InventoryLot.warehouse_id == uuid.UUID(warehouse_id))
    lots = (await db.execute(stmt)).scalars().all()
    return sum((lot.quantity_remaining for lot in lots), Decimal("0"))


async def allocate_issue(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str | None,
    product_id: str,
    quantity: Decimal,
    reason: str | None,
    reference_type: str | None = None,
    reference_id: str | None = None,
    preferred_warehouse_id: str | None = None,
) -> list[tuple[InventoryBalance, list[StockMovement]]]:
    """跨仓可用库存分配出库：默认仓优先，逐仓扣减，总量不足时显式报错。"""

    if quantity <= 0:
        raise ValidationFailureError("出库数量必须大于 0")
    rows = (
        await db.execute(
            select(InventoryBalance)
            .where(
                InventoryBalance.organization_id == uuid.UUID(organization_id),
                InventoryBalance.product_id == uuid.UUID(product_id),
            )
            .order_by(InventoryBalance.created_at)
        )
    ).scalars().all()
    rows = sorted(
        rows,
        key=lambda balance: (
            preferred_warehouse_id is not None
            and balance.warehouse_id != uuid.UUID(preferred_warehouse_id),
            balance.created_at,
        ),
    )
    remaining = quantity
    results: list[tuple[InventoryBalance, list[StockMovement]]] = []
    total_available = Decimal("0")
    for balance in rows:
        expired = await expired_lot_quantity(
            db, organization_id=organization_id, product_id=product_id,
            warehouse_id=str(balance.warehouse_id),
        )
        total_available += balance.on_hand - balance.reserved - expired
    if total_available < quantity:
        raise InsufficientStockError(
            "可用库存不足（已预留与过期批次不可挪用）",
            details={
                "product_id": product_id,
                "available": str(total_available),
                "requested": str(quantity),
            },
        )
    for balance in rows:
        if remaining <= 0:
            break
        expired = await expired_lot_quantity(
            db, organization_id=organization_id, product_id=product_id,
            warehouse_id=str(balance.warehouse_id),
        )
        sellable = balance.on_hand - balance.reserved - expired
        take = min(sellable, remaining)
        if take <= 0:
            continue
        issued_balance, movements = await issue_stock(
            db,
            organization_id=organization_id,
            actor_id=actor_id,
            product_id=product_id,
            warehouse_id=str(balance.warehouse_id),
            quantity=take,
            reason=reason,
            reference_type=reference_type,
            reference_id=reference_id,
        )
        remaining -= take
        results.append((issued_balance, movements))
    return results


async def get_balance_locked(
    db: AsyncSession, *, organization_id: str, product_id: str, warehouse_id: str
) -> InventoryBalance:
    balance = (
        await db.execute(
            select(InventoryBalance)
            .where(
                InventoryBalance.organization_id == uuid.UUID(organization_id),
                InventoryBalance.product_id == uuid.UUID(product_id),
                InventoryBalance.warehouse_id == uuid.UUID(warehouse_id),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if balance is None:
        try:
            async with db.begin_nested():
                balance = InventoryBalance(
                    organization_id=uuid.UUID(organization_id),
                    product_id=uuid.UUID(product_id),
                    warehouse_id=uuid.UUID(warehouse_id),
                    on_hand=Decimal("0"),
                    reserved=Decimal("0"),
                    version=0,
                )
                db.add(balance)
                await db.flush()
        except IntegrityError:
            balance = (
                await db.execute(
                    select(InventoryBalance)
                    .where(
                        InventoryBalance.organization_id == uuid.UUID(organization_id),
                        InventoryBalance.product_id == uuid.UUID(product_id),
                        InventoryBalance.warehouse_id == uuid.UUID(warehouse_id),
                    )
                    .with_for_update()
                )
            ).scalar_one()
    return balance


async def latest_snapshot(
    db: AsyncSession, *, organization_id: str, product_id: str, price_type: str
) -> InternalPriceSnapshot | None:
    return (
        await db.execute(
            select(InternalPriceSnapshot)
            .where(
                InternalPriceSnapshot.organization_id == uuid.UUID(organization_id),
                InternalPriceSnapshot.product_id == uuid.UUID(product_id),
                InternalPriceSnapshot.price_type == price_type,
            )
            .order_by(InternalPriceSnapshot.effective_at.desc(), InternalPriceSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def receive_stock(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str | None,
    product_id: str,
    warehouse_id: str,
    location_id: str | None,
    quantity: Decimal,
    unit_cost: Decimal | None,
    lot_code: str | None,
    expires_at: datetime | None,
    supplier_id: str | None,
    purchase_order_line_id: str | None,
    reason: str | None,
    occurred_at: datetime | None = None,
) -> tuple[InventoryBalance, InventoryLot | None, StockMovement]:
    occurred = occurred_at or datetime.now(UTC)
    product = (
        await db.execute(
            select(Product).where(
                Product.id == uuid.UUID(product_id),
                Product.organization_id == uuid.UUID(organization_id),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if product is None:
        raise NotFoundError("商品不存在")
    if purchase_order_line_id:
        poline = (
            await db.execute(
                select(PurchaseOrderLine)
                .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
                .where(
                    PurchaseOrderLine.id == uuid.UUID(purchase_order_line_id),
                    PurchaseOrder.organization_id == uuid.UUID(organization_id),
                    PurchaseOrderLine.product_id == uuid.UUID(product_id),
                    PurchaseOrder.status.in_(["CONFIRMED", "PARTIAL"]),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if poline is None:
            raise NotFoundError("采购订单行不存在、不属于当前组织或商品不匹配")
        if quantity > poline.ordered_qty - poline.received_qty:
            raise InsufficientStockError(
                "入库数量超过采购订单剩余数量",
                details={
                    "purchase_order_line_id": purchase_order_line_id,
                    "remaining": str(poline.ordered_qty - poline.received_qty),
                    "requested": str(quantity),
                },
            )
        poline.received_qty += quantity
    warehouse = await get_warehouse(db, organization_id=organization_id, warehouse_id=warehouse_id)
    if location_id:
        location = (
            await db.execute(
                select(Location).where(
                    Location.id == uuid.UUID(location_id),
                    Location.warehouse_id == warehouse.id,
                )
            )
        ).scalar_one_or_none()
        if location is None:
            raise NotFoundError("库位不存在或不属于该仓库")

    balance = await get_balance_locked(
        db, organization_id=organization_id, product_id=product_id, warehouse_id=warehouse_id
    )
    all_balances = (
        await db.execute(
            select(InventoryBalance).where(
                InventoryBalance.organization_id == uuid.UUID(organization_id),
                InventoryBalance.product_id == uuid.UUID(product_id),
            )
        )
    ).scalars().all()
    # 价格快照是 SKU 全局的，入库前的 old_on_hand 必须聚合全仓库存。
    old_on_hand = sum((b.on_hand for b in all_balances), Decimal("0"))
    old_avg = Decimal("0")
    if unit_cost is not None:
        old_snapshot = await latest_snapshot(
            db, organization_id=organization_id, product_id=product_id, price_type="WEIGHTED_AVG_COST"
        )
        if old_snapshot is not None:
            old_avg = old_snapshot.price

    lot: InventoryLot | None = None
    if lot_code:
        lot = (
            await db.execute(
                select(InventoryLot).where(
                    InventoryLot.organization_id == uuid.UUID(organization_id),
                    InventoryLot.product_id == uuid.UUID(product_id),
                    InventoryLot.warehouse_id == uuid.UUID(warehouse_id),
                    InventoryLot.lot_code == lot_code,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if lot is None:
            try:
                async with db.begin_nested():
                    lot = InventoryLot(
                        organization_id=uuid.UUID(organization_id),
                        product_id=uuid.UUID(product_id),
                        warehouse_id=uuid.UUID(warehouse_id),
                        location_id=uuid.UUID(location_id) if location_id else None,
                        lot_code=lot_code,
                        quantity_remaining=Decimal("0"),
                        unit_cost=unit_cost,
                        received_at=occurred,
                        expires_at=expires_at,
                        supplier_id=uuid.UUID(supplier_id) if supplier_id else None,
                        purchase_order_line_id=(
                            uuid.UUID(purchase_order_line_id)
                            if purchase_order_line_id
                            else None
                        ),
                    )
                    db.add(lot)
                    await db.flush()
            except IntegrityError:
                lot = (
                    await db.execute(
                        select(InventoryLot).where(
                            InventoryLot.organization_id == uuid.UUID(organization_id),
                            InventoryLot.product_id == uuid.UUID(product_id),
                            InventoryLot.warehouse_id == uuid.UUID(warehouse_id),
                            InventoryLot.lot_code == lot_code,
                        )
                        .with_for_update()
                    )
                ).scalar_one()
        lot.quantity_remaining += quantity
        if unit_cost is not None:
            lot.unit_cost = unit_cost
        if expires_at is not None:
            lot.expires_at = expires_at

    balance.on_hand += quantity
    balance.version += 1

    movement = StockMovement(
        organization_id=uuid.UUID(organization_id),
        product_id=uuid.UUID(product_id),
        warehouse_id=uuid.UUID(warehouse_id),
        location_id=uuid.UUID(location_id) if location_id else None,
        lot_id=lot.id if lot else None,
        movement_type="RECEIPT",
        quantity=quantity,
        unit_cost=unit_cost,
        reference_type="PURCHASE_ORDER_LINE" if purchase_order_line_id else None,
        reference_id=purchase_order_line_id or None,
        reason=reason,
        occurred_at=occurred,
        created_by=uuid.UUID(actor_id) if actor_id else None,
    )
    db.add(movement)
    await db.flush()

    if unit_cost is not None:
        now = datetime.now(UTC)
        db.add(
            InternalPriceSnapshot(
                organization_id=uuid.UUID(organization_id),
                product_id=uuid.UUID(product_id),
                price_type="LAST_PURCHASE_PRICE",
                price=unit_cost,
                currency=product.currency,
                source_reference_type="STOCK_MOVEMENT",
                source_reference_id=str(movement.id),
                effective_at=occurred,
            )
        )
        new_avg = (old_on_hand * old_avg + quantity * unit_cost) / (old_on_hand + quantity)
        db.add(
            InternalPriceSnapshot(
                organization_id=uuid.UUID(organization_id),
                product_id=uuid.UUID(product_id),
                price_type="WEIGHTED_AVG_COST",
                price=new_avg,
                currency=product.currency,
                source_reference_type="STOCK_MOVEMENT",
                source_reference_id=str(movement.id),
                effective_at=now,
            )
        )
    else:
        new_avg = old_avg

    record_event(
        db,
        organization_id=organization_id,
        event_type="inventory.received",
        aggregate_type="product",
        aggregate_id=product_id,
        payload={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity": str(quantity),
            "unit_cost": str(unit_cost) if unit_cost is not None else None,
            "lot_code": lot_code,
            "on_hand": str(balance.on_hand),
            "weighted_avg_cost": str(new_avg) if unit_cost is not None else None,
        },
        occurred_at=occurred,
    )
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="inventory.receive",
        entity_type="product",
        entity_id=product_id,
        after_json={
            "warehouse_id": warehouse_id,
            "quantity": str(quantity),
            "unit_cost": str(unit_cost) if unit_cost is not None else None,
            "on_hand_after": str(balance.on_hand),
        },
    )
    if purchase_order_line_id and poline is not None:
        po = await db.get(PurchaseOrder, poline.purchase_order_id)
        if po is not None:
            po_lines = (
                await db.execute(
                    select(PurchaseOrderLine).where(
                        PurchaseOrderLine.purchase_order_id == po.id
                    )
                )
            ).scalars().all()
            po.status = (
                "RECEIVED"
                if all(line.received_qty == line.ordered_qty for line in po_lines)
                else "PARTIAL"
            )
    return balance, lot, movement


async def adjust_stock(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str | None,
    product_id: str,
    warehouse_id: str,
    quantity: Decimal,
    reason: str | None,
) -> tuple[InventoryBalance, StockMovement]:
    occurred = datetime.now(UTC)
    if quantity == 0:
        raise ValidationFailureError("调整数量不能为 0")
    await get_warehouse(db, organization_id=organization_id, warehouse_id=warehouse_id)
    balance = await get_balance_locked(
        db, organization_id=organization_id, product_id=product_id, warehouse_id=warehouse_id
    )
    new_on_hand = balance.on_hand + quantity
    if new_on_hand < 0:
        raise InsufficientStockError(
            "调整后库存不能为负",
            details={
                "on_hand": str(balance.on_hand),
                "adjustment": str(quantity),
            },
        )
    if new_on_hand < balance.reserved:
        raise InsufficientStockError(
            "调整后可用库存不能为负（已预留库存不可挪用）",
            details={
                "on_hand": str(balance.on_hand),
                "reserved": str(balance.reserved),
                "available": str(balance.on_hand - balance.reserved),
                "adjustment": str(quantity),
            },
        )
    if quantity < 0:
        expired_before = await expired_lot_quantity(
            db,
            organization_id=organization_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
        )
        if new_on_hand - expired_before < balance.reserved:
            raise InsufficientStockError(
                "调整后未过期可售库存无法覆盖已预留量（预留不可被过期库存替代）",
                details={
                    "on_hand_after": str(new_on_hand),
                    "expired": str(expired_before),
                    "reserved": str(balance.reserved),
                    "adjustment": str(quantity),
                },
            )
    before = {"on_hand": str(balance.on_hand), "version": balance.version}
    balance.on_hand = new_on_hand
    balance.version += 1
    movements: list[StockMovement] = []
    if quantity > 0:
        avg_snapshot = await latest_snapshot(
            db,
            organization_id=organization_id,
            product_id=product_id,
            price_type="WEIGHTED_AVG_COST",
        )
        lot = InventoryLot(
            organization_id=uuid.UUID(organization_id),
            product_id=uuid.UUID(product_id),
            warehouse_id=uuid.UUID(warehouse_id),
            lot_code=f"ADJ-{uuid.uuid4().hex[:8]}",
            quantity_remaining=quantity,
            unit_cost=avg_snapshot.price if avg_snapshot else None,
            received_at=occurred,
        )
        db.add(lot)
        await db.flush()
        movements.append(
            StockMovement(
                organization_id=uuid.UUID(organization_id),
                product_id=uuid.UUID(product_id),
                warehouse_id=uuid.UUID(warehouse_id),
                lot_id=lot.id,
                movement_type="ADJUST_IN",
                quantity=quantity,
                unit_cost=lot.unit_cost,
                reference_type="MANUAL",
                reason=reason,
                occurred_at=occurred,
                created_by=uuid.UUID(actor_id) if actor_id else None,
            )
        )
    else:
        lots = (
            await db.execute(
                select(InventoryLot)
                .where(
                    InventoryLot.organization_id == uuid.UUID(organization_id),
                    InventoryLot.product_id == uuid.UUID(product_id),
                    InventoryLot.warehouse_id == uuid.UUID(warehouse_id),
                    InventoryLot.quantity_remaining > 0,
                )
                .order_by(InventoryLot.received_at)
                .with_for_update()
            )
        ).scalars().all()
        remaining = -quantity
        for lot in lots:
            if remaining <= 0:
                break
            take = min(lot.quantity_remaining, remaining)
            lot.quantity_remaining -= take
            remaining -= take
            movements.append(
                StockMovement(
                    organization_id=uuid.UUID(organization_id),
                    product_id=uuid.UUID(product_id),
                    warehouse_id=uuid.UUID(warehouse_id),
                    lot_id=lot.id,
                    movement_type="ADJUST_OUT",
                    quantity=-take,
                    unit_cost=lot.unit_cost,
                    reference_type="MANUAL",
                    reason=reason,
                    occurred_at=occurred,
                    created_by=uuid.UUID(actor_id) if actor_id else None,
                )
            )
        if remaining > 0:
            movements.append(
                StockMovement(
                    organization_id=uuid.UUID(organization_id),
                    product_id=uuid.UUID(product_id),
                    warehouse_id=uuid.UUID(warehouse_id),
                    movement_type="ADJUST_OUT",
                    quantity=-remaining,
                    reference_type="MANUAL",
                    reason=reason,
                    occurred_at=occurred,
                    created_by=uuid.UUID(actor_id) if actor_id else None,
                )
            )
    db.add_all(movements)
    await db.flush()
    record_event(
        db,
        organization_id=organization_id,
        event_type="inventory.adjusted",
        aggregate_type="product",
        aggregate_id=product_id,
        payload={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity": str(quantity),
            "on_hand": str(balance.on_hand),
            "reason": reason,
        },
        occurred_at=occurred,
    )
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="inventory.adjust",
        entity_type="product",
        entity_id=product_id,
        before_json=before,
        after_json={"on_hand": str(balance.on_hand), "version": balance.version},
    )
    return balance, movements[0]


async def issue_stock(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str | None,
    product_id: str,
    warehouse_id: str,
    quantity: Decimal,
    reason: str | None,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> tuple[InventoryBalance, list[StockMovement]]:
    """出库（领用/发货）：从批次 FIFO 扣减 on_hand，创建 SHIPMENT 流水。不处理预留。"""

    if quantity <= 0:
        raise ValidationFailureError("出库数量必须大于 0")
    occurred = datetime.now(UTC)
    await get_warehouse(db, organization_id=organization_id, warehouse_id=warehouse_id)
    balance = await get_balance_locked(
        db, organization_id=organization_id, product_id=product_id, warehouse_id=warehouse_id
    )
    expired = await expired_lot_quantity(
        db, organization_id=organization_id, product_id=product_id,
        warehouse_id=warehouse_id,
    )
    sellable = balance.on_hand - balance.reserved - expired
    if sellable < quantity:
        raise InsufficientStockError(
            "可用库存不足，无法出库（已预留与过期批次不可挪用）",
            details={
                "on_hand": str(balance.on_hand),
                "reserved": str(balance.reserved),
                "expired": str(expired),
                "available": str(sellable),
                "requested": str(quantity),
            },
        )
    lots = (
        await db.execute(
            select(InventoryLot)
            .where(
                InventoryLot.organization_id == uuid.UUID(organization_id),
                InventoryLot.product_id == uuid.UUID(product_id),
                InventoryLot.warehouse_id == uuid.UUID(warehouse_id),
                InventoryLot.quantity_remaining > 0,
                (InventoryLot.expires_at.is_(None)) | (InventoryLot.expires_at >= occurred),
            )
            .order_by(InventoryLot.received_at, InventoryLot.expires_at)
            .with_for_update()
        )
    ).scalars().all()
    to_consume = quantity
    movements: list[StockMovement] = []
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
            reference_type=reference_type,
            reference_id=reference_id,
            reason=reason,
            occurred_at=occurred,
            created_by=uuid.UUID(actor_id) if actor_id else None,
        )
        db.add(movement)
        movements.append(movement)
    if to_consume > 0:
        # 批次不足时，剩余部分从未批次余额出库（余额已在上方校验足够）。
        movement = StockMovement(
            organization_id=uuid.UUID(organization_id),
            product_id=uuid.UUID(product_id),
            warehouse_id=uuid.UUID(warehouse_id),
            movement_type="SHIPMENT",
            quantity=-to_consume,
            reference_type=reference_type,
            reference_id=reference_id,
            reason=reason,
            occurred_at=occurred,
            created_by=uuid.UUID(actor_id) if actor_id else None,
        )
        db.add(movement)
        movements.append(movement)
    balance.on_hand -= quantity
    balance.version += 1
    await db.flush()
    record_event(
        db,
        organization_id=organization_id,
        event_type="inventory.issued",
        aggregate_type="product",
        aggregate_id=product_id,
        payload={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity": str(quantity),
            "on_hand": str(balance.on_hand),
            "reason": reason,
        },
        occurred_at=occurred,
    )
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER" if actor_id else "SYSTEM",
        actor_id=actor_id,
        action="inventory.issue",
        entity_type="product",
        entity_id=product_id,
        after_json={
            "warehouse_id": warehouse_id,
            "quantity": str(quantity),
            "on_hand_after": str(balance.on_hand),
            "reason": reason,
        },
    )
    return balance, movements
