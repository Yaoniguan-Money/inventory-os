from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_scope
from app.core.security import CurrentUser
from app.domains.health.models import InventoryAlert
from app.domains.health.schemas import AlertOut, HealthOverviewOut, ProductHealthOut
from app.domains.health.service import health_overview, product_health, recalculate_org

router = APIRouter(tags=["health"])


@router.post("/health/recalculate")
async def recalculate(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("health:read")),
) -> dict:
    count = await recalculate_org(db, organization_id=user.organization_id)
    await db.commit()
    return {"recalculated": count}


@router.get("/health/overview", response_model=HealthOverviewOut)
async def overview(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("health:read")),
) -> HealthOverviewOut:
    data = await health_overview(db, organization_id=user.organization_id)
    await db.commit()
    return HealthOverviewOut.model_validate(data)


@router.get("/health/alerts", response_model=list[AlertOut])
async def alerts(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("health:read")),
) -> list[AlertOut]:
    stmt = select(InventoryAlert).where(
        InventoryAlert.organization_id == uuid.UUID(user.organization_id)
    )
    if status:
        stmt = stmt.where(InventoryAlert.status == status)
    rows = (await db.execute(stmt.order_by(InventoryAlert.opened_at.desc()))).scalars().all()
    return [AlertOut.model_validate(row) for row in rows]


@router.get("/products/{product_id}/health", response_model=ProductHealthOut)
async def product_health_route(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("health:read")),
) -> ProductHealthOut:
    data = await product_health(db, organization_id=user.organization_id, product_id=product_id)
    await db.commit()
    return ProductHealthOut.model_validate(data)
