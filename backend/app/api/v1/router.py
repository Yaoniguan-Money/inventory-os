from fastapi import APIRouter

from app.domains.catalog.routes import router as catalog_router
from app.domains.equipment.routes import router as equipment_router
from app.domains.health.routes import router as health_router
from app.domains.identity.routes import router as identity_router
from app.domains.integrations.routes import router as integrations_router
from app.domains.intelligence.routes import router as intelligence_router
from app.domains.knowledge.routes import router as knowledge_router
from app.domains.market.routes import router as market_router
from app.domains.orders.routes import router as orders_router
from app.domains.pricing.routes import router as pricing_router
from app.domains.purchasing.routes import router as purchasing_router
from app.domains.warehouse.routes import router as warehouse_router

api_router = APIRouter()
api_router.include_router(identity_router, prefix="/api/v1")
api_router.include_router(catalog_router, prefix="/api/v1")
api_router.include_router(warehouse_router, prefix="/api/v1")
api_router.include_router(orders_router, prefix="/api/v1")
api_router.include_router(pricing_router, prefix="/api/v1")
api_router.include_router(purchasing_router, prefix="/api/v1")
api_router.include_router(integrations_router, prefix="/api/v1")
api_router.include_router(health_router, prefix="/api/v1")
api_router.include_router(market_router, prefix="/api/v1")
api_router.include_router(equipment_router, prefix="/api/v1")
api_router.include_router(knowledge_router, prefix="/api/v1")
api_router.include_router(intelligence_router, prefix="/api/v1")
