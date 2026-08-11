from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import AppError, PermissionDeniedError
from app.core.permissions import require_scope
from app.core.security import CurrentUser, authenticate_api_key
from app.domains.integrations.models import EventLog
from app.domains.integrations.schemas import IntegrationEventEnvelope, IntegrationEventResult
from app.domains.integrations.service import process_integration_event

router = APIRouter(tags=["integrations"])

EVENT_SCOPE = {
    "inventory.received": "inventory:receive",
    "inventory.adjusted": "inventory:adjust",
}


@router.post("/integrations/events", response_model=IntegrationEventResult)
async def receive_external_event(
    payload: IntegrationEventEnvelope,
    request: Request,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(authenticate_api_key),
) -> IntegrationEventResult:
    required_scope = EVENT_SCOPE.get(payload.type)
    if required_scope is not None and required_scope not in (api_key.scopes or []):
        raise PermissionDeniedError(f"API Key 缺少权限: {required_scope}")
    try:
        status = await process_integration_event(
            db,
            organization_id=str(api_key.organization_id),
            source=payload.source,
            event_id=payload.event_id,
            event_type=payload.type,
            occurred_at=payload.occurred_at,
            data=payload.data,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        return IntegrationEventResult(
            status="rejected",
            event_id=payload.event_id,
            message=str(exc),
        )
    except IntegrityError:
        await db.rollback()
        return IntegrationEventResult(
            status="duplicate",
            event_id=payload.event_id,
            message="重复事件（并发）",
        )
    except AppError as exc:
        await db.rollback()
        return IntegrationEventResult(
            status="rejected",
            event_id=payload.event_id,
            message=exc.message,
        )
    return IntegrationEventResult(status=status, event_id=payload.event_id)


@router.get("/events/stream")
async def event_stream(
    request: Request,
    after: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("health:read")),
) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        cursor = after
        heartbeat_counter = 0
        emitted = 0
        while True:
            if await request.is_disconnected():
                break
            rows = (
                await db.execute(
                    select(EventLog)
                    .where(
                        EventLog.organization_id == user.organization_id,
                        EventLog.sequence_id > cursor,
                    )
                    .order_by(EventLog.sequence_id)
                    .limit(200)
                )
            ).scalars().all()
            for row in rows:
                payload = {
                    "sequence_id": row.sequence_id,
                    "event_id": str(row.event_id),
                    "event_type": row.event_type,
                    "aggregate_type": row.aggregate_type,
                    "aggregate_id": row.aggregate_id,
                    "payload": row.payload,
                    "occurred_at": row.occurred_at.isoformat(),
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                cursor = row.sequence_id
                emitted += 1
                if limit is not None and emitted >= limit:
                    return
            heartbeat_counter += 1
            heartbeat_every = max(
                1,
                int(settings.sse_heartbeat_seconds / max(settings.sse_poll_interval_seconds, 0.1)),
            )
            if heartbeat_counter >= heartbeat_every:
                yield ": heartbeat\n\n"
                heartbeat_counter = 0
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.sleep(settings.sse_poll_interval_seconds),
                    timeout=settings.sse_poll_interval_seconds + 0.5,
                )

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/events")
async def list_events(
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("health:read")),
) -> list[dict]:
    rows = (
        await db.execute(
            select(EventLog)
            .where(EventLog.organization_id == user.organization_id)
            .order_by(EventLog.sequence_id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "sequence_id": row.sequence_id,
            "event_id": str(row.event_id),
            "event_type": row.event_type,
            "aggregate_type": row.aggregate_type,
            "aggregate_id": row.aggregate_id,
            "payload": row.payload,
            "occurred_at": row.occurred_at,
        }
        for row in rows
    ]
