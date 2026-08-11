from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ConflictError
from app.core.permissions import require_scope
from app.core.security import CurrentUser
from app.domains.orders.models import Customer, SalesOrder, SalesOrderLine
from app.domains.orders.schemas import (
    CustomerCreate,
    CustomerOut,
    FulfillRequest,
    SalesOrderCreate,
    SalesOrderOut,
)
from app.domains.orders.service import (
    build_order_out,
    cancel_order,
    confirm_order,
    create_sales_order,
    fulfill_order,
    get_order,
)

router = APIRouter(tags=["orders"])


@router.get("/customers", response_model=list[CustomerOut])
async def list_customers(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("orders:read")),
) -> list[CustomerOut]:
    rows = (
        await db.execute(
            select(Customer).where(Customer.organization_id == uuid.UUID(user.organization_id))
            .order_by(Customer.code)
        )
    ).scalars().all()
    return [CustomerOut.model_validate(row) for row in rows]


@router.post("/customers", response_model=CustomerOut, status_code=201)
async def create_customer(
    payload: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("orders:write")),
) -> CustomerOut:
    existing = (
        await db.execute(
            select(Customer).where(
                Customer.organization_id == uuid.UUID(user.organization_id),
                Customer.code == payload.code,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"客户编码已存在: {payload.code}")
    customer = Customer(organization_id=uuid.UUID(user.organization_id), **payload.model_dump())
    db.add(customer)
    await db.commit()
    return CustomerOut.model_validate(customer)


@router.get("/orders", response_model=list[SalesOrderOut])
async def list_orders(
    status: str | None = Query(default=None, max_length=24),
    customer_id: str | None = Query(default=None),
    product_id: str | None = Query(default=None),
    overdue: bool = Query(default=False),
    due_from: datetime | None = Query(default=None),
    due_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("orders:read")),
) -> list[SalesOrderOut]:
    stmt = select(SalesOrder).where(
        SalesOrder.organization_id == uuid.UUID(user.organization_id)
    )
    if status:
        stmt = stmt.where(SalesOrder.status == status)
    if customer_id:
        stmt = stmt.where(SalesOrder.customer_id == uuid.UUID(customer_id))
    if product_id:
        stmt = stmt.join(
            SalesOrderLine, SalesOrderLine.sales_order_id == SalesOrder.id
        ).where(SalesOrderLine.product_id == uuid.UUID(product_id))
    line_due = func.coalesce(SalesOrderLine.required_at, SalesOrder.required_at)
    has_line_due_before = lambda cutoff: exists(  # noqa: E731
        select(1).where(
            SalesOrderLine.sales_order_id == SalesOrder.id,
            line_due <= cutoff,
        )
    )
    has_line_due_after = lambda cutoff: exists(  # noqa: E731
        select(1).where(
            SalesOrderLine.sales_order_id == SalesOrder.id,
            line_due >= cutoff,
        )
    )
    if overdue:
        stmt = stmt.where(
            SalesOrder.status.in_(["CONFIRMED", "PARTIAL"]),
            has_line_due_before(datetime.now(UTC)),
        )
    if due_from:
        stmt = stmt.where(has_line_due_after(due_from))
    if due_to:
        stmt = stmt.where(has_line_due_before(due_to))
    orders = (
        await db.execute(stmt.order_by(SalesOrder.required_at, SalesOrder.ordered_at.desc()))
    ).scalars().all()
    return [SalesOrderOut.model_validate(await build_order_out(db, user.organization_id, o)) for o in orders]


@router.post("/orders", response_model=SalesOrderOut, status_code=201)
async def create_order_route(
    payload: SalesOrderCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("orders:write")),
) -> SalesOrderOut:
    order = await create_sales_order(
        db, organization_id=user.organization_id, actor_id=user.user_id, payload=payload
    )
    await db.commit()
    return SalesOrderOut.model_validate(await build_order_out(db, user.organization_id, order))


@router.get("/orders/{order_id}", response_model=SalesOrderOut)
async def get_order_route(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("orders:read")),
) -> SalesOrderOut:
    order = await get_order(db, organization_id=user.organization_id, order_id=order_id)
    return SalesOrderOut.model_validate(await build_order_out(db, user.organization_id, order))


@router.post("/orders/{order_id}/confirm", response_model=SalesOrderOut)
async def confirm_order_route(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("orders:confirm")),
) -> SalesOrderOut:
    order, _ = await confirm_order(
        db, organization_id=user.organization_id, actor_id=user.user_id, order_id=order_id
    )
    await db.commit()
    return SalesOrderOut.model_validate(await build_order_out(db, user.organization_id, order))


@router.post("/orders/{order_id}/fulfill", response_model=SalesOrderOut)
async def fulfill_order_route(
    order_id: str,
    payload: FulfillRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("orders:fulfill")),
) -> SalesOrderOut:
    order = await fulfill_order(
        db,
        organization_id=user.organization_id,
        actor_id=user.user_id,
        order_id=order_id,
        fulfill_lines=[item.model_dump() for item in payload.lines],
    )
    await db.commit()
    return SalesOrderOut.model_validate(await build_order_out(db, user.organization_id, order))


@router.post("/orders/{order_id}/cancel", response_model=SalesOrderOut)
async def cancel_order_route(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("orders:write")),
) -> SalesOrderOut:
    order = await cancel_order(
        db, organization_id=user.organization_id, actor_id=user.user_id, order_id=order_id
    )
    await db.commit()
    return SalesOrderOut.model_validate(await build_order_out(db, user.organization_id, order))
