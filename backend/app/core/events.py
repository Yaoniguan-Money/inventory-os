from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EventLog


def record_event(
    db: AsyncSession,
    *,
    organization_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any] | None = None,
    event_id: str | None = None,
    occurred_at: datetime | None = None,
) -> EventLog:
    """Append an event to the durable event log inside the caller's transaction."""

    event = EventLog(
        event_id=uuid.UUID(event_id) if event_id else uuid.uuid4(),
        organization_id=organization_id,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload or {},
        occurred_at=occurred_at or datetime.now(UTC),
    )
    db.add(event)
    return event
