from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_scope
from app.core.security import CurrentUser
from app.domains.knowledge.models import KnowledgeDocument
from app.domains.knowledge.schemas import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentDetail,
    KnowledgeDocumentOut,
    KnowledgeLinkRequest,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.domains.knowledge.service import (
    create_document,
    document_detail,
    link_document,
    search_knowledge,
)

router = APIRouter(tags=["knowledge"])


@router.get("/knowledge/documents", response_model=list[KnowledgeDocumentOut])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("knowledge:read")),
) -> list[KnowledgeDocumentOut]:
    stmt = select(KnowledgeDocument).where(
        KnowledgeDocument.organization_id == uuid.UUID(user.organization_id)
    )
    if user.role not in ("OWNER", "ADMIN"):
        stmt = stmt.where(KnowledgeDocument.access_scope != "OWNER")
    rows = (await db.execute(stmt.order_by(KnowledgeDocument.created_at.desc()))).scalars().all()
    return [KnowledgeDocumentOut.model_validate(row) for row in rows]


@router.post(
    "/knowledge/documents", response_model=KnowledgeDocumentOut, status_code=201
)
async def create_document_route(
    payload: KnowledgeDocumentCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("knowledge:write")),
) -> KnowledgeDocumentOut:
    doc = await create_document(
        db, organization_id=user.organization_id, actor_id=user.user_id, payload=payload
    )
    await db.commit()
    return KnowledgeDocumentOut.model_validate(doc)


@router.get("/knowledge/documents/{document_id}", response_model=KnowledgeDocumentDetail)
async def get_document_route(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("knowledge:read")),
) -> KnowledgeDocumentDetail:
    detail = await document_detail(
        db, organization_id=user.organization_id, document_id=document_id
    )
    return KnowledgeDocumentDetail.model_validate(detail)


@router.post("/knowledge/search", response_model=KnowledgeSearchResponse)
async def search(
    payload: KnowledgeSearchRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("knowledge:read")),
) -> KnowledgeSearchResponse:
    result = await search_knowledge(
        db,
        organization_id=user.organization_id,
        user_role=user.role,
        query=payload.query,
        entity_type=payload.entity_type,
        entity_id=str(payload.entity_id) if payload.entity_id else None,
        limit=payload.limit,
    )
    return KnowledgeSearchResponse.model_validate(result)


@router.post(
    "/knowledge/documents/{document_id}/links",
    response_model=dict,
    status_code=201,
)
async def link_document_route(
    document_id: str,
    payload: KnowledgeLinkRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("knowledge:write")),
) -> dict:
    link = await link_document(
        db,
        organization_id=user.organization_id,
        document_id=document_id,
        entity_type=payload.entity_type,
        entity_id=str(payload.entity_id),
        relation_type=payload.relation_type,
    )
    await db.commit()
    return {"id": str(link.id), "document_id": str(link.document_id)}
