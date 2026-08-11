from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.events import record_event
from app.domains.catalog.models import Product
from app.domains.equipment.models import EquipmentAsset
from app.domains.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeEntityLink,
)
from app.domains.knowledge.schemas import KnowledgeDocumentOut
from app.domains.purchasing.models import Supplier
from app.domains.warehouse.models import Warehouse


async def _validate_entity(
    db: AsyncSession,
    *,
    organization_id: str,
    entity_type: str,
    entity_id: uuid.UUID,
) -> None:
    from app.core.errors import ValidationFailureError

    model_map = {
        "PRODUCT": Product,
        "EQUIPMENT": EquipmentAsset,
        "WAREHOUSE": Warehouse,
        "SUPPLIER": Supplier,
    }
    model = model_map.get(entity_type)
    if model is None:
        raise ValidationFailureError(f"不支持的实体类型: {entity_type}")
    stmt = select(model).where(model.id == entity_id)  # type: ignore[attr-defined]
    if hasattr(model, "organization_id"):
        stmt = stmt.where(model.organization_id == uuid.UUID(organization_id))
    if (await db.execute(stmt)).scalar_one_or_none() is None:
        raise NotFoundError(f"{entity_type} 实体不存在或不属于当前组织")


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _chunk_content(content: str, size: int = 500) -> list[str]:
    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 1 <= size:
            current = f"{current}\n{paragraph}" if current else paragraph
        else:
            if current:
                chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks or [content]


async def create_document(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    payload,
) -> KnowledgeDocument:
    doc = KnowledgeDocument(
        organization_id=uuid.UUID(organization_id),
        title=payload.title,
        document_type=payload.document_type,
        status=payload.status,
        access_scope=payload.access_scope,
        source_type=payload.source_type,
        source_uri=payload.source_uri,
        checksum=_checksum(payload.content),
        created_by=uuid.UUID(actor_id),
    )
    db.add(doc)
    await db.flush()
    version = KnowledgeDocumentVersion(
        document_id=doc.id,
        version=1,
        content_hash=_checksum(payload.content),
    )
    db.add(version)
    await db.flush()
    for index, content in enumerate(_chunk_content(payload.content)):
        db.add(
            KnowledgeChunk(
                document_version_id=version.id,
                chunk_index=index,
                content=content,
                metadata_json={"title": payload.title, "document_type": payload.document_type},
            )
        )
    for link in payload.entity_links:
        await _validate_entity(
            db,
            organization_id=organization_id,
            entity_type=link.entity_type,
            entity_id=link.entity_id,
        )
        db.add(
            KnowledgeEntityLink(
                organization_id=uuid.UUID(organization_id),
                document_id=doc.id,
                entity_type=link.entity_type,
                entity_id=link.entity_id,
                relation_type=link.relation_type,
            )
        )
    await db.flush()
    record_event(
        db,
        organization_id=organization_id,
        event_type="knowledge.document.created",
        aggregate_type="knowledge_document",
        aggregate_id=str(doc.id),
        payload={"title": doc.title, "document_type": doc.document_type},
    )
    return doc


async def get_document(
    db: AsyncSession, *, organization_id: str, document_id: str
) -> KnowledgeDocument:
    doc = (
        await db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == uuid.UUID(document_id),
                KnowledgeDocument.organization_id == uuid.UUID(organization_id),
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise NotFoundError("知识文档不存在")
    return doc


async def document_detail(
    db: AsyncSession, *, organization_id: str, document_id: str, user_role: str
) -> dict:
    doc = await get_document(db, organization_id=organization_id, document_id=document_id)
    if doc.access_scope == "OWNER" and user_role not in ("OWNER", "ADMIN"):
        raise NotFoundError("知识文档不存在")
    latest_version = (
        await db.execute(
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == doc.id)
            .order_by(KnowledgeDocumentVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    chunk_count = 0
    if latest_version is not None:
        chunk_count = len(
            (
                await db.execute(
                    select(KnowledgeChunk).where(
                        KnowledgeChunk.document_version_id == latest_version.id
                    )
                )
            ).scalars().all()
        )
    return {
        **KnowledgeDocumentOut.model_validate(doc).model_dump(),
        "version": latest_version.version if latest_version else 1,
        "chunk_count": chunk_count,
    }


async def search_knowledge(
    db: AsyncSession,
    *,
    organization_id: str,
    user_role: str,
    query: str,
    entity_type: str | None,
    entity_id: str | None,
    limit: int,
) -> dict:
    org_uuid = uuid.UUID(organization_id)
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.organization_id == org_uuid)
    if user_role not in ("OWNER", "ADMIN"):
        stmt = stmt.where(KnowledgeDocument.access_scope != "OWNER")
    docs = (await db.execute(stmt)).scalars().all()
    if entity_type and entity_id:
        linked_doc_ids = set(
            (
                await db.execute(
                    select(KnowledgeEntityLink.document_id).where(
                        KnowledgeEntityLink.organization_id == org_uuid,
                        KnowledgeEntityLink.entity_type == entity_type,
                        KnowledgeEntityLink.entity_id == uuid.UUID(entity_id),
                    )
                )
            ).scalars()
        )
        docs = [d for d in docs if d.id in linked_doc_ids]

    q = query.lower()
    version_ids = set()
    doc_by_version: dict[uuid.UUID, KnowledgeDocument] = {}
    if docs:
        doc_ids = [d.id for d in docs]
        versions = (
            await db.execute(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.document_id.in_(doc_ids)
                )
            )
        ).scalars().all()
        latest: dict[uuid.UUID, KnowledgeDocumentVersion] = {}
        for version in versions:
            current_version = latest.get(version.document_id)
            if current_version is None or version.version > current_version.version:
                latest[version.document_id] = version
        for doc in docs:
            doc_version = latest.get(doc.id)
            if doc_version is not None:
                version_ids.add(doc_version.id)
                doc_by_version[doc_version.id] = doc

    hits: list[dict] = []
    if version_ids:
        chunks = (
            await db.execute(
                select(KnowledgeChunk).where(KnowledgeChunk.document_version_id.in_(version_ids))
            )
        ).scalars().all()
        for chunk in chunks:
            content = chunk.content
            score = 0
            if q in content.lower():
                score += 10
            for token in q.split():
                if token and token in content.lower():
                    score += 3
            hit_doc = doc_by_version.get(chunk.document_version_id)
            if hit_doc is None:
                continue
            if q in hit_doc.title.lower():
                score += 5
            if score > 0:
                hits.append(
                    {
                        "document_id": hit_doc.id,
                        "document_title": hit_doc.title,
                        "document_type": hit_doc.document_type,
                        "access_scope": hit_doc.access_scope,
                        "chunk_index": chunk.chunk_index,
                        "content": content,
                        "excerpt": content[:200],
                        "score": score,
                    }
                )
    hits.sort(key=lambda h: h["score"], reverse=True)
    return {"query": query, "hits": hits[:limit]}


async def link_document(
    db: AsyncSession,
    *,
    organization_id: str,
    document_id: str,
    entity_type: str,
    entity_id: str,
    relation_type: str,
) -> KnowledgeEntityLink:
    doc = await get_document(db, organization_id=organization_id, document_id=document_id)
    await _validate_entity(
        db,
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id=uuid.UUID(entity_id),
    )
    link = KnowledgeEntityLink(
        organization_id=uuid.UUID(organization_id),
        document_id=doc.id,
        entity_type=entity_type,
        entity_id=uuid.UUID(entity_id),
        relation_type=relation_type,
    )
    db.add(link)
    await db.flush()
    return link
