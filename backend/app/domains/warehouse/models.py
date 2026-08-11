from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.mixins import OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Warehouse(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_warehouses_org_code"),)

    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")


class Location(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("warehouse_id", "code", name="uq_locations_warehouse_code"),)

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InventoryLot(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    __tablename__ = "inventory_lots"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "product_id",
            "warehouse_id",
            "lot_code",
            name="uq_inventory_lots_org_product_wh_lot",
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), index=True
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("locations.id", ondelete="SET NULL"), nullable=True
    )
    lot_code: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity_remaining: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    purchase_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_order_lines.id", ondelete="SET NULL"), nullable=True
    )


class StockMovement(UUIDPrimaryKeyMixin, OrgScopedMixin, Base):
    __tablename__ = "stock_movements"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), index=True
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("locations.id", ondelete="SET NULL"), nullable=True
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("inventory_lots.id", ondelete="SET NULL"), nullable=True
    )
    movement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventoryBalance(UUIDPrimaryKeyMixin, OrgScopedMixin, Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "product_id", "warehouse_id", name="uq_inventory_balance_org_product_wh"
        ),
        CheckConstraint("on_hand >= 0", name="ck_inventory_balance_on_hand_non_negative"),
        CheckConstraint("reserved >= 0", name="ck_inventory_balance_reserved_non_negative"),
        CheckConstraint("reserved <= on_hand", name="ck_inventory_balance_reserved_lte_on_hand"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("warehouses.id", ondelete="RESTRICT"), index=True
    )
    on_hand: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    reserved: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
