from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.errors import ConflictError, NotFoundError
from app.core.events import record_event
from app.domains.catalog.models import Product
from app.domains.catalog.schemas import ProductCreate, ProductUpdate
from app.domains.pricing.service import record_price_snapshot
from app.domains.warehouse.models import Location, Warehouse


async def _validate_default_locations(
    db: AsyncSession,
    *,
    organization_id: str,
    warehouse_id: str | None,
    location_id: str | None,
) -> None:
    """默认仓库/库位必须属于当前组织，禁止跨租户脏引用。"""

    org_uuid = uuid.UUID(organization_id)
    if warehouse_id:
        warehouse = (
            await db.execute(
                select(Warehouse).where(
                    Warehouse.id == uuid.UUID(str(warehouse_id)),
                    Warehouse.organization_id == org_uuid,
                )
            )
        ).scalar_one_or_none()
        if warehouse is None:
            raise NotFoundError("默认仓库不存在或不属于当前组织")
    if location_id:
        location = (
            await db.execute(
                select(Location)
                .join(Warehouse, Warehouse.id == Location.warehouse_id)
                .where(
                    Location.id == uuid.UUID(str(location_id)),
                    Warehouse.organization_id == org_uuid,
                )
            )
        ).scalar_one_or_none()
        if location is None:
            raise NotFoundError("默认库位不存在或不属于当前组织")


async def get_product(db: AsyncSession, *, organization_id: str, product_id: str) -> Product:
    product = (
        await db.execute(
            select(Product).where(
                Product.id == uuid.UUID(product_id),
                Product.organization_id == uuid.UUID(organization_id),
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise NotFoundError("商品不存在")
    return product


async def create_product(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    payload: ProductCreate,
) -> Product:
    existing = (
        await db.execute(
            select(Product).where(
                Product.organization_id == uuid.UUID(organization_id),
                or_(Product.sku == payload.sku, Product.barcode == payload.barcode),
            )
        )
    ).scalars().all()
    if any(p.sku == payload.sku for p in existing):
        raise ConflictError(f"SKU 已存在: {payload.sku}")
    if payload.barcode and any(p.barcode == payload.barcode for p in existing):
        raise ConflictError(f"条码已存在: {payload.barcode}")

    await _validate_default_locations(
        db,
        organization_id=organization_id,
        warehouse_id=str(payload.default_warehouse_id) if payload.default_warehouse_id else None,
        location_id=str(payload.default_location_id) if payload.default_location_id else None,
    )

    product = Product(
        organization_id=uuid.UUID(organization_id),
        **payload.model_dump(),
    )
    db.add(product)
    await db.flush()
    if payload.target_sell_price is not None:
        record_price_snapshot(
            db,
            organization_id=organization_id,
            product_id=str(product.id),
            price_type="TARGET_SELL_PRICE",
            price=payload.target_sell_price,
            currency=product.currency,
            source_reference_type="PRODUCT",
            source_reference_id=str(product.id),
            effective_at=datetime.now(UTC),
        )
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="product.create",
        entity_type="product",
        entity_id=str(product.id),
        after_json={"sku": product.sku, "name": product.name},
    )
    record_event(
        db,
        organization_id=organization_id,
        event_type="catalog.product.created",
        aggregate_type="product",
        aggregate_id=str(product.id),
        payload={"sku": product.sku, "name": product.name},
    )
    return product


async def update_product(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    product_id: str,
    payload: ProductUpdate,
) -> Product:
    product = await get_product(db, organization_id=organization_id, product_id=product_id)
    before = {"name": product.name, "status": product.status, "target_sell_price": str(product.target_sell_price)}
    changes = payload.model_dump(exclude_unset=True)
    await _validate_default_locations(
        db,
        organization_id=organization_id,
        warehouse_id=(
            str(changes["default_warehouse_id"])
            if changes.get("default_warehouse_id") is not None
            else None
        ),
        location_id=(
            str(changes["default_location_id"])
            if changes.get("default_location_id") is not None
            else None
        ),
    )
    if "barcode" in changes and changes["barcode"]:
        dup = (
            await db.execute(
                select(Product).where(
                    Product.organization_id == uuid.UUID(organization_id),
                    Product.barcode == changes["barcode"],
                    Product.id != product.id,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise ConflictError(f"条码已存在: {changes['barcode']}")
    for field, value in changes.items():
        setattr(product, field, value)
    await db.flush()
    if changes.get("target_sell_price") is not None:
        record_price_snapshot(
            db,
            organization_id=organization_id,
            product_id=str(product.id),
            price_type="TARGET_SELL_PRICE",
            price=changes["target_sell_price"],
            currency=product.currency,
            source_reference_type="PRODUCT",
            source_reference_id=str(product.id),
            effective_at=datetime.now(UTC),
        )
    after = {"name": product.name, "status": product.status, "target_sell_price": str(product.target_sell_price)}
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="product.update",
        entity_type="product",
        entity_id=str(product.id),
        before_json=before,
        after_json=after,
    )
    record_event(
        db,
        organization_id=organization_id,
        event_type="catalog.product.updated",
        aggregate_type="product",
        aggregate_id=str(product.id),
        payload={
            key: (str(value) if isinstance(value, Decimal) else value)
            for key, value in changes.items()
        },
    )
    return product
