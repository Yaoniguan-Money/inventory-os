from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_scope
from app.core.security import CurrentUser
from app.domains.intelligence.schemas import (
    ChatRequest,
    ChatResponse,
    ExplainAlertResponse,
    ForecastRequest,
    ResolveProductRequest,
    ResolveProductResponse,
)
from app.domains.intelligence.service import (
    employee_assistant,
    explain_alert,
    resolve_product,
)
from app.providers.ai import get_ai_provider
from app.providers.forecast import DisabledForecastProvider

router = APIRouter(tags=["intelligence"])


@router.get("/ai/capabilities")
async def ai_capabilities(
    user: CurrentUser = Depends(require_scope("ai:read")),
) -> dict:
    provider = get_ai_provider()
    return {
        "provider": provider.name,
        "enabled": provider.capability.supports_text,
        "capability": provider.capability.__dict__,
    }


@router.post("/ai/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("ai:read")),
) -> ChatResponse:
    result = await employee_assistant(
        db,
        organization_id=user.organization_id,
        user_role=user.role,
        scopes=user.scopes,
        query=payload.query,
    )
    return ChatResponse.model_validate(result)


@router.post("/ai/employee-assistant", response_model=ChatResponse)
async def employee_assistant_route(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("ai:read")),
) -> ChatResponse:
    result = await employee_assistant(
        db,
        organization_id=user.organization_id,
        user_role=user.role,
        scopes=user.scopes,
        query=payload.query,
    )
    return ChatResponse.model_validate(result)


@router.post("/ai/resolve-product", response_model=ResolveProductResponse)
async def resolve_product_route(
    payload: ResolveProductRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("ai:read")),
) -> ResolveProductResponse:
    result = await resolve_product(
        db,
        organization_id=user.organization_id,
        barcode=payload.barcode,
        text=payload.text,
        image_data_url=payload.image_data_url,
    )
    return ResolveProductResponse.model_validate(result)


@router.post("/ai/explain-alert/{alert_id}", response_model=ExplainAlertResponse)
async def explain_alert_route(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("ai:read")),
) -> ExplainAlertResponse:
    result = await explain_alert(
        db, organization_id=user.organization_id, alert_id=alert_id
    )
    return ExplainAlertResponse.model_validate(result)


@router.get("/forecast/capabilities")
async def forecast_capabilities() -> dict:
    capability = await DisabledForecastProvider().capability()
    return {
        "enabled": capability.enabled,
        "provider": capability.provider,
        "types": capability.types,
    }


@router.post("/forecast/price")
async def forecast_price(payload: ForecastRequest) -> dict:
    return await DisabledForecastProvider().forecast_price(
        payload.subject_id, payload.horizon, **payload.params
    )


@router.post("/forecast/demand")
async def forecast_demand(payload: ForecastRequest) -> dict:
    return await DisabledForecastProvider().forecast_demand(
        payload.subject_id, payload.horizon, **payload.params
    )


@router.post("/forecast/supply-risk")
async def forecast_supply_risk(payload: ForecastRequest) -> dict:
    return await DisabledForecastProvider().forecast_supply_risk(
        payload.subject_id, payload.horizon, **payload.params
    )
