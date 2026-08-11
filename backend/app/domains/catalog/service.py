from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.errors import ConflictError, NotFoundError
from app.core.events import record_event
from app.domains.catalog.models import Product
from app.domains.catalog.schemas import ProductCreate, ProductUpdate


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

    product = Product(
        organization_id=uuid.UUID(organization_id),
        **payload.model_dump(),
    )
    db.add(product)
    await db.flush()
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
        payload=changes,
    )
    return product
