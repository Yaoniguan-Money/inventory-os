from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_scope
from app.core.security import CurrentUser
from app.domains.market.schemas import (
    MarketMappingCreate,
    MarketMappingOut,
    MarketRefreshResult,
    ProductMarketOut,
)
from app.domains.market.service import create_mapping, get_product_market, refresh_market

router = APIRouter(tags=["market"])


@router.get("/products/{product_id}/market", response_model=ProductMarketOut)
async def product_market(
    product_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("market:read")),
) -> ProductMarketOut:
    data = await get_product_market(db, organization_id=user.organization_id, product_id=product_id)
    return ProductMarketOut.model_validate(data)


@router.post("/market/refresh", response_model=MarketRefreshResult)
async def refresh(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("market:write")),
) -> MarketRefreshResult:
    result = await refresh_market(db, organization_id=user.organization_id)
    await db.commit()
    return MarketRefreshResult(**result)


@router.post("/products/{product_id}/market-mappings", response_model=MarketMappingOut, status_code=201)
async def create_market_mapping(
    product_id: str,
    payload: MarketMappingCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("market:write")),
) -> MarketMappingOut:
    mapping = await create_mapping(
        db,
        organization_id=user.organization_id,
        product_id=product_id,
        provider=payload.provider,
        external_symbol=payload.external_symbol,
        region=payload.region,
        enabled=payload.enabled,
    )
    await db.commit()
    return MarketMappingOut.model_validate(mapping)
