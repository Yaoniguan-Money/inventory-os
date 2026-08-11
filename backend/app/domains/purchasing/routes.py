from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ConflictError
from app.core.permissions import require_scope
from app.core.security import CurrentUser
from app.domains.purchasing.models import PurchaseOrder, Supplier
from app.domains.purchasing.schemas import (
    PurchaseOrderCreate,
    PurchaseOrderOut,
    PurchaseReceiveRequest,
    SupplierCreate,
    SupplierOut,
    WorkbenchItem,
)
from app.domains.purchasing.service import (
    build_po_out,
    confirm_purchase_order,
    create_purchase_order,
    get_purchase_order,
    receive_purchase_order,
    workbench,
)

router = APIRouter(tags=["purchasing"])


@router.get("/suppliers", response_model=list[SupplierOut])
async def list_suppliers(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("purchases:read")),
) -> list[SupplierOut]:
    rows = (
        await db.execute(
            select(Supplier).where(Supplier.organization_id == uuid.UUID(user.organization_id))
            .order_by(Supplier.code)
        )
    ).scalars().all()
    return [SupplierOut.model_validate(row) for row in rows]


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
async def create_supplier(
    payload: SupplierCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("purchases:write")),
) -> SupplierOut:
    existing = (
        await db.execute(
            select(Supplier).where(
                Supplier.organization_id == uuid.UUID(user.organization_id),
                Supplier.code == payload.code,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"供应商编码已存在: {payload.code}")
    supplier = Supplier(organization_id=uuid.UUID(user.organization_id), **payload.model_dump())
    db.add(supplier)
    await db.commit()
    return SupplierOut.model_validate(supplier)


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
async def list_purchase_orders(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("purchases:read")),
) -> list[PurchaseOrderOut]:
    rows = (
        await db.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.organization_id == uuid.UUID(user.organization_id))
            .order_by(PurchaseOrder.ordered_at.desc())
        )
    ).scalars().all()
    return [
        PurchaseOrderOut.model_validate(await build_po_out(db, user.organization_id, po))
        for po in rows
    ]


@router.post("/purchase-orders", response_model=PurchaseOrderOut, status_code=201)
async def create_po_route(
    payload: PurchaseOrderCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("purchases:write")),
) -> PurchaseOrderOut:
    po = await create_purchase_order(
        db, organization_id=user.organization_id, actor_id=user.user_id, payload=payload
    )
    await db.commit()
    return PurchaseOrderOut.model_validate(await build_po_out(db, user.organization_id, po))


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderOut)
async def get_po_route(
    po_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("purchases:read")),
) -> PurchaseOrderOut:
    po = await get_purchase_order(db, organization_id=user.organization_id, po_id=po_id)
    return PurchaseOrderOut.model_validate(await build_po_out(db, user.organization_id, po))


@router.post("/purchase-orders/{po_id}/confirm", response_model=PurchaseOrderOut)
async def confirm_po_route(
    po_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("purchases:write")),
) -> PurchaseOrderOut:
    po = await confirm_purchase_order(
        db, organization_id=user.organization_id, actor_id=user.user_id, po_id=po_id
    )
    await db.commit()
    return PurchaseOrderOut.model_validate(await build_po_out(db, user.organization_id, po))


@router.post("/purchase-orders/{po_id}/receive", response_model=PurchaseOrderOut)
async def receive_po_route(
    po_id: str,
    payload: PurchaseReceiveRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("purchases:write")),
) -> PurchaseOrderOut:
    po = await receive_purchase_order(
        db,
        organization_id=user.organization_id,
        actor_id=user.user_id,
        po_id=po_id,
        receive_lines=[item.model_dump() for item in payload.lines],
    )
    await db.commit()
    return PurchaseOrderOut.model_validate(await build_po_out(db, user.organization_id, po))


@router.get("/purchase-workbench", response_model=list[WorkbenchItem])
async def purchase_workbench(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("purchases:read")),
) -> list[WorkbenchItem]:
    items = await workbench(db, organization_id=user.organization_id)
    return [WorkbenchItem(**item) for item in items]
