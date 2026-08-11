from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ConflictError, NotFoundError
from app.core.permissions import require_scope
from app.core.security import CurrentUser
from app.domains.catalog.models import Product
from app.domains.warehouse.models import InventoryBalance, InventoryLot, Location, StockMovement, Warehouse
from app.domains.warehouse.schemas import (
    AdjustRequest,
    AdjustResult,
    InventoryBalanceOut,
    InventoryLotOut,
    LocationCreate,
    LocationOut,
    ReceiveRequest,
    ReceiveResult,
    StockMovementOut,
    WarehouseCreate,
    WarehouseOut,
)
from app.domains.warehouse.service import adjust_stock, get_warehouse, receive_stock

router = APIRouter(tags=["warehouse"])


@router.get("/warehouses", response_model=list[WarehouseOut])
async def list_warehouses(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("products:read")),
) -> list[WarehouseOut]:
    rows = (
        await db.execute(
            select(Warehouse).where(Warehouse.organization_id == uuid.UUID(user.organization_id))
        )
    ).scalars().all()
    return [WarehouseOut.model_validate(row) for row in rows]


@router.post("/warehouses", response_model=WarehouseOut, status_code=201)
async def create_warehouse(
    payload: WarehouseCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("products:write")),
) -> WarehouseOut:
    existing = (
        await db.execute(
            select(Warehouse).where(
                Warehouse.organization_id == uuid.UUID(user.organization_id),
                Warehouse.code == payload.code,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"仓库编码已存在: {payload.code}")
    warehouse = Warehouse(organization_id=uuid.UUID(user.organization_id), **payload.model_dump())
    db.add(warehouse)
    await db.commit()
    return WarehouseOut.model_validate(warehouse)


@router.get("/warehouses/{warehouse_id}/locations", response_model=list[LocationOut])
async def list_locations(
    warehouse_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("products:read")),
) -> list[LocationOut]:
    warehouse = await get_warehouse(db, organization_id=user.organization_id, warehouse_id=warehouse_id)
    rows = (
        await db.execute(select(Location).where(Location.warehouse_id == warehouse.id))
    ).scalars().all()
    return [LocationOut.model_validate(row) for row in rows]


@router.post("/warehouses/{warehouse_id}/locations", response_model=LocationOut, status_code=201)
async def create_location(
    warehouse_id: str,
    payload: LocationCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("products:write")),
) -> LocationOut:
    warehouse = await get_warehouse(db, organization_id=user.organization_id, warehouse_id=warehouse_id)
    existing = (
        await db.execute(
            select(Location).where(
                Location.warehouse_id == warehouse.id,
                Location.code == payload.code,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"库位编码已存在: {payload.code}")
    location = Location(warehouse_id=warehouse.id, **payload.model_dump())
    db.add(location)
    await db.commit()
    return LocationOut.model_validate(location)


def _balance_out(balance: InventoryBalance, product: Product, warehouse: Warehouse) -> InventoryBalanceOut:
    return InventoryBalanceOut(
        product_id=balance.product_id,
        sku=product.sku,
        name=product.name,
        warehouse_id=balance.warehouse_id,
        warehouse_code=warehouse.code,
        on_hand=balance.on_hand,
        reserved=balance.reserved,
        available=balance.on_hand - balance.reserved,
        version=balance.version,
    )


@router.get("/inventory", response_model=list[InventoryBalanceOut])
async def list_inventory(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("inventory:read")),
) -> list[InventoryBalanceOut]:
    rows = (
        await db.execute(
            select(InventoryBalance, Product, Warehouse)
            .join(Product, Product.id == InventoryBalance.product_id)
            .join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
            .where(InventoryBalance.organization_id == uuid.UUID(user.organization_id))
            .order_by(Product.sku, Warehouse.code)
        )
    ).all()
    return [_balance_out(balance, product, warehouse) for balance, product, warehouse in rows]


@router.get("/inventory/{product_id}", response_model=InventoryBalanceOut)
async def get_inventory(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("inventory:read")),
) -> InventoryBalanceOut:
    row = (
        await db.execute(
            select(InventoryBalance, Product, Warehouse)
            .join(Product, Product.id == InventoryBalance.product_id)
            .join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
            .where(
                InventoryBalance.organization_id == uuid.UUID(user.organization_id),
                InventoryBalance.product_id == uuid.UUID(product_id),
            )
        )
    ).first()
    if row is None:
        raise NotFoundError("该商品暂无库存记录")
    balance, product, warehouse = row
    return _balance_out(balance, product, warehouse)


@router.get("/inventory/{product_id}/lots", response_model=list[InventoryLotOut])
async def list_lots(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("inventory:read")),
) -> list[InventoryLotOut]:
    rows = (
        await db.execute(
            select(InventoryLot).where(
                InventoryLot.organization_id == uuid.UUID(user.organization_id),
                InventoryLot.product_id == uuid.UUID(product_id),
            )
            .order_by(InventoryLot.received_at)
        )
    ).scalars().all()
    return [InventoryLotOut.model_validate(row) for row in rows]


@router.get("/inventory/{product_id}/movements", response_model=list[StockMovementOut])
async def list_movements(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("inventory:read")),
) -> list[StockMovementOut]:
    rows = (
        await db.execute(
            select(StockMovement).where(
                StockMovement.organization_id == uuid.UUID(user.organization_id),
                StockMovement.product_id == uuid.UUID(product_id),
            )
            .order_by(StockMovement.occurred_at.desc())
            .limit(200)
        )
    ).scalars().all()
    return [StockMovementOut.model_validate(row) for row in rows]


@router.post("/inventory/receive", response_model=ReceiveResult, status_code=201)
async def receive_route(
    payload: ReceiveRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("inventory:receive")),
) -> ReceiveResult:
    balance, lot, movement = await receive_stock(
        db,
        organization_id=user.organization_id,
        actor_id=user.user_id,
        product_id=str(payload.product_id),
        warehouse_id=str(payload.warehouse_id),
        location_id=str(payload.location_id) if payload.location_id else None,
        quantity=payload.quantity,
        unit_cost=payload.unit_cost,
        lot_code=payload.lot_code,
        expires_at=payload.expires_at,
        supplier_id=str(payload.supplier_id) if payload.supplier_id else None,
        purchase_order_line_id=str(payload.purchase_order_line_id) if payload.purchase_order_line_id else None,
        reason=payload.reason,
    )
    await db.commit()
    product = await db.get(Product, balance.product_id)
    warehouse = await db.get(Warehouse, balance.warehouse_id)
    if product is None or warehouse is None:
        raise NotFoundError("商品或仓库不存在")
    snapshot = await _latest_cost(db, user.organization_id, str(product.id))
    return ReceiveResult(
        balance=_balance_out(balance, product, warehouse),
        lot_id=lot.id if lot else None,
        movement_id=movement.id,
        weighted_avg_cost=snapshot,
    )


async def _latest_cost(db: AsyncSession, organization_id: str, product_id: str) -> Decimal | None:
    from app.domains.pricing.models import InternalPriceSnapshot

    snapshot = (
        await db.execute(
            select(InternalPriceSnapshot)
            .where(
                InternalPriceSnapshot.organization_id == uuid.UUID(organization_id),
                InternalPriceSnapshot.product_id == uuid.UUID(product_id),
                InternalPriceSnapshot.price_type == "WEIGHTED_AVG_COST",
            )
            .order_by(InternalPriceSnapshot.effective_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return snapshot.price if snapshot else None


@router.post("/inventory/adjust", response_model=AdjustResult)
async def adjust_route(
    payload: AdjustRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("inventory:adjust")),
) -> AdjustResult:
    balance, movement = await adjust_stock(
        db,
        organization_id=user.organization_id,
        actor_id=user.user_id,
        product_id=str(payload.product_id),
        warehouse_id=str(payload.warehouse_id),
        quantity=payload.quantity,
        reason=payload.reason,
    )
    await db.commit()
    product = await db.get(Product, balance.product_id)
    warehouse = await db.get(Warehouse, balance.warehouse_id)
    if product is None or warehouse is None:
        raise NotFoundError("商品或仓库不存在")
    return AdjustResult(balance=_balance_out(balance, product, warehouse), movement_id=movement.id)
