"""共享供应分配（ATP）服务。

Health / Dashboard / 订单详情 / 采购工作台统一使用同一套时间桶规则：
- 按 PO ETA 建立时间桶并逐笔消费，同一批在途不会被不同订单重复借用；
- 有截止日期的需求只能使用 ETA 明确且不晚于截止日的在途（ETA=None 不参与）；
- 无截止日期的需求可用全部在途。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.orders.models import SalesOrder, SalesOrderLine
from app.domains.purchasing.models import PurchaseOrder, PurchaseOrderLine
from app.domains.warehouse.models import InventoryBalance
from app.domains.warehouse.service import expired_lot_quantity

_MAX = datetime.max.replace(tzinfo=UTC)


async def build_buckets(
    db: AsyncSession, *, organization_id: str, product_id: str
) -> list[list]:
    """返回按 ETA 升序的 [eta, remaining_qty] 时间桶；eta 可为 None（未知）。"""

    rows = (
        await db.execute(
            select(PurchaseOrderLine, PurchaseOrder)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
            .where(
                PurchaseOrder.organization_id == uuid.UUID(organization_id),
                PurchaseOrderLine.product_id == uuid.UUID(product_id),
                PurchaseOrder.status.in_(["CONFIRMED", "PARTIAL"]),
            )
        )
    ).all()
    buckets: list[list] = []
    for line, po in rows:
        qty = line.ordered_qty - line.received_qty
        if qty <= 0:
            continue
        buckets.append([line.expected_at or po.expected_at, qty])
    buckets.sort(key=lambda bucket: (bucket[0] is None, bucket[0] or _MAX))
    return buckets


def consume_buckets(
    buckets: list[list], *, deadline: datetime | None, need: Decimal
) -> Decimal:
    """按截止时间消费时间桶；返回实际可分配数量。"""

    allocated = Decimal("0")
    for bucket in buckets:
        if allocated >= need:
            break
        eta, qty = bucket
        if deadline is not None and (eta is None or eta > deadline):
            continue
        take = min(qty, need - allocated)
        bucket[1] -= take
        allocated += take
    return allocated


async def incoming_before(
    db: AsyncSession, *, organization_id: str, product_id: str, deadline: datetime | None
) -> Decimal:
    """截止日前可到货的在途总量（未知 ETA 不计入有截止日期的需求）。"""

    buckets = await build_buckets(db, organization_id=organization_id, product_id=product_id)
    if deadline is None:
        return sum((qty for _, qty in buckets), Decimal("0"))
    return sum(
        (qty for eta, qty in buckets if eta is not None and eta <= deadline),
        Decimal("0"),
    )


async def incoming_total(
    db: AsyncSession, *, organization_id: str, product_id: str
) -> Decimal:
    buckets = await build_buckets(db, organization_id=organization_id, product_id=product_id)
    return sum((qty for _, qty in buckets), Decimal("0"))


class IncomingAllocator:
    """跨订单共享的在途分配器：同一对象连续 allocate 会逐桶扣减。"""

    def __init__(self, buckets: list[list]) -> None:
        self.buckets = buckets

    @classmethod
    async def build(
        cls, db: AsyncSession, *, organization_id: str, product_id: str
    ) -> IncomingAllocator:
        return cls(
            await build_buckets(db, organization_id=organization_id, product_id=product_id)
        )

    def allocate(self, deadline: datetime | None, need: Decimal) -> Decimal:
        return consume_buckets(self.buckets, deadline=deadline, need=need)


async def simulate_product_allocation(
    db: AsyncSession,
    *,
    organization_id: str,
    product_id: str,
    horizon: datetime | None = None,
) -> list[dict]:
    """按全局订单优先序模拟同一商品的供应分配。

    排序与 Health / Dashboard 一致：有效截止时间（行级优先）升序，未设截止的最后；
    预留覆盖以可售（未过期）库存为上限，并按同一顺序消费；在途按 ETA 时间桶逐笔消费。
    返回每个订单行的 covered_reserved 与 allocated_incoming。
    horizon 传入时只模拟截止在该时间之前的订单（Health 履约风险口径）；
    不传时模拟全部 CONFIRMED/PARTIAL 剩余订单（Dashboard 与订单详情口径）。
    """

    stmt = (
        select(SalesOrderLine, SalesOrder)
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
        .where(
            SalesOrder.organization_id == uuid.UUID(organization_id),
            SalesOrderLine.product_id == uuid.UUID(product_id),
            SalesOrder.status.in_(["CONFIRMED", "PARTIAL"]),
        )
    )
    if horizon is not None:
        stmt = stmt.where(
            func.coalesce(SalesOrderLine.required_at, SalesOrder.required_at) <= horizon
        )
    rows = (await db.execute(stmt)).all()
    items: list[dict] = []
    for line, order in rows:
        remaining = line.ordered_qty - line.delivered_qty
        if remaining <= 0:
            continue
        items.append(
            {
                "line": line,
                "order": order,
                "remaining": remaining,
            }
        )
    items.sort(
        key=lambda item: (
            (item["line"].required_at or item["order"].required_at) is None,
            item["line"].required_at
            or item["order"].required_at
            or datetime.max.replace(tzinfo=UTC),
        )
    )

    balances = (
        await db.execute(
            select(InventoryBalance).where(
                InventoryBalance.organization_id == uuid.UUID(organization_id),
                InventoryBalance.product_id == uuid.UUID(product_id),
            )
        )
    ).scalars().all()
    on_hand = sum((b.on_hand for b in balances), Decimal("0"))
    expired = await expired_lot_quantity(
        db, organization_id=organization_id, product_id=product_id
    )
    sellable_pool = max(on_hand - expired, Decimal("0"))
    buckets = await build_buckets(db, organization_id=organization_id, product_id=product_id)
    buckets_snapshot = [list(bucket) for bucket in buckets]

    results: list[dict] = []
    for item in items:
        sales_line: SalesOrderLine = item["line"]
        sales_order: SalesOrder = item["order"]
        qty_remaining: Decimal = item["remaining"]
        covered = min(sales_line.reserved_qty, sellable_pool)
        sellable_pool -= covered
        deadline = sales_line.required_at or sales_order.required_at
        if deadline is None:
            incoming_before_deadline = sum(
                (qty for _, qty in buckets_snapshot), Decimal("0")
            )
        else:
            incoming_before_deadline = sum(
                (
                    qty
                    for eta, qty in buckets_snapshot
                    if eta is not None and eta <= deadline
                ),
                Decimal("0"),
            )
        allocated = consume_buckets(
            buckets,
            deadline=deadline,
            need=max(qty_remaining - covered, Decimal("0")),
        )
        results.append(
            {
                "line_id": str(sales_line.id),
                "order_id": str(sales_order.id),
                "order_no": sales_order.order_no,
                "remaining": qty_remaining,
                "covered_reserved": covered,
                "incoming_before_deadline": incoming_before_deadline,
                "allocated_incoming": allocated,
                "deadline": deadline,
            }
        )
    return results


async def allocation_for_line(
    db: AsyncSession,
    *,
    organization_id: str,
    product_id: str,
    sales_order_line_id: str,
) -> dict | None:
    """返回指定订单行在全局优先序中的实际分配结果（不在分配列表中时返回 None）。"""

    for item in await simulate_product_allocation(
        db, organization_id=organization_id, product_id=product_id
    ):
        if item["line_id"] == sales_order_line_id:
            return item
    return None
