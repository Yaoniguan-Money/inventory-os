from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_scope
from app.core.security import CurrentUser
from app.domains.dashboard.service import dashboard

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
async def dashboard_route(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("health:read")),
) -> dict:
    data = await dashboard(db, organization_id=user.organization_id)
    await db.commit()
    return data
