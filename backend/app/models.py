"""Central model registry so Alembic autogenerate sees every table."""

from app.domains.catalog.models import Product, ProductAsset
from app.domains.equipment.models import (
    EquipmentAsset,
    EquipmentDocumentLink,
    FaultRecord,
    InspectionRecord,
    MaintenancePartUsage,
    MaintenanceRecord,
)
from app.domains.health.models import InventoryAlert
from app.domains.identity.models import ApiKey, Membership, Organization, User
from app.domains.integrations.models import AuditLog, EventLog, InboundEvent
from app.domains.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeEntityLink,
)
from app.domains.market.models import (
    MarketEvent,
    MarketQuote,
    ProductMarketMapping,
)
from app.domains.orders.models import (
    Customer,
    Delivery,
    DeliveryLine,
    InventoryReservation,
    SalesOrder,
    SalesOrderLine,
)
from app.domains.pricing.models import InternalPriceSnapshot
from app.domains.purchasing.models import PurchaseOrder, PurchaseOrderLine, Supplier
from app.domains.warehouse.models import (
    InventoryBalance,
    InventoryLot,
    Location,
    StockMovement,
    Warehouse,
)

__all__ = [
    "ApiKey",
    "AuditLog",
    "Customer",
    "Delivery",
    "DeliveryLine",
    "EquipmentAsset",
    "EquipmentDocumentLink",
    "EventLog",
    "FaultRecord",
    "InboundEvent",
    "InspectionRecord",
    "InternalPriceSnapshot",
    "InventoryAlert",
    "InventoryBalance",
    "InventoryLot",
    "InventoryReservation",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeDocumentVersion",
    "KnowledgeEntityLink",
    "Location",
    "MaintenancePartUsage",
    "MaintenanceRecord",
    "MarketEvent",
    "MarketQuote",
    "Membership",
    "Organization",
    "Product",
    "ProductAsset",
    "ProductMarketMapping",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "SalesOrder",
    "SalesOrderLine",
    "StockMovement",
    "Supplier",
    "User",
    "Warehouse",
]
