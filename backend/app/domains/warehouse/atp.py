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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.purchasing.models import PurchaseOrder, PurchaseOrderLine

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
