from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeEntityLinkCreate(BaseModel):
    entity_type: str = Field(max_length=32)  # PRODUCT/EQUIPMENT/WAREHOUSE/SUPPLIER
    entity_id: uuid.UUID
    relation_type: str = Field(default="GUIDE", max_length=32)


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    document_type: str = Field(default="SOP", max_length=40)
    status: str = Field(default="PUBLISHED", max_length=24)
    access_scope: str = Field(default="ORG", max_length=24)  # ORG / OWNER
    source_type: str = Field(default="MANUAL", max_length=40)
    source_uri: str | None = None
    content: str = Field(min_length=1)
    entity_links: list[KnowledgeEntityLinkCreate] = Field(default_factory=list)


class KnowledgeDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    document_type: str
    status: str
    access_scope: str
    source_type: str
    source_uri: str | None
    checksum: str | None
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentDetail(KnowledgeDocumentOut):
    version: int
    chunk_count: int


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    entity_type: str | None = Field(default=None, max_length=32)
    entity_id: uuid.UUID | None = None
    limit: int = Field(default=10, ge=1, le=50)


class KnowledgeSearchHit(BaseModel):
    document_id: uuid.UUID
    document_title: str
    document_type: str
    access_scope: str
    chunk_index: int
    content: str
    excerpt: str
    score: int


class KnowledgeSearchResponse(BaseModel):
    query: str
    hits: list[KnowledgeSearchHit]


class KnowledgeLinkRequest(BaseModel):
    entity_type: str = Field(max_length=32)
    entity_id: uuid.UUID
    relation_type: str = Field(default="GUIDE", max_length=32)
