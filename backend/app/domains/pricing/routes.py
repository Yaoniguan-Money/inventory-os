from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_scope
from app.core.security import CurrentUser
from app.domains.pricing.schemas import ProductPricesOut, TargetPriceRequest
from app.domains.pricing.service import get_prices, set_target_price

router = APIRouter(tags=["pricing"])


@router.get("/products/{product_id}/prices", response_model=ProductPricesOut)
async def get_product_prices(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("pricing:internal:read")),
) -> ProductPricesOut:
    data = await get_prices(db, organization_id=user.organization_id, product_id=product_id)
    return ProductPricesOut.model_validate(data)


@router.post("/products/{product_id}/target-price", response_model=ProductPricesOut)
async def set_target_price_route(
    product_id: str,
    payload: TargetPriceRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("pricing:internal:write")),
) -> ProductPricesOut:
    await set_target_price(
        db,
        organization_id=user.organization_id,
        actor_id=user.user_id,
        product_id=product_id,
        price=payload.price,
        currency=payload.currency,
    )
    await db.commit()
    data = await get_prices(db, organization_id=user.organization_id, product_id=product_id)
    return ProductPricesOut.model_validate(data)
