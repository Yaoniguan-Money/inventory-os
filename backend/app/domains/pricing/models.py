from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.mixins import OrgScopedMixin, UUIDPrimaryKeyMixin


class InternalPriceSnapshot(UUIDPrimaryKeyMixin, OrgScopedMixin, Base):
    __tablename__ = "internal_price_snapshots"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    price_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    source_reference_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
