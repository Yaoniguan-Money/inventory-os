from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


class ForecastRequest(BaseModel):
    subject_id: str = Field(default="", max_length=64)
    horizon: str = Field(default="30d", pattern="^[0-9]+[dwm]$")
    params: dict[str, Any] = Field(default_factory=dict)


class CitationOut(BaseModel):
    document_id: uuid.UUID
    document_title: str
    excerpt: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[CitationOut] = Field(default_factory=list)
    tools: dict[str, Any] = Field(default_factory=dict)
    provider: str
    disclaimer: str = "回答基于系统内数据与权限过滤后的知识库，请以实际业务单据为准。"


class ResolveProductRequest(BaseModel):
    barcode: str | None = Field(default=None, max_length=128)
    text: str | None = Field(default=None, max_length=500)
    image_data_url: str | None = Field(default=None, max_length=8_000_000)


class ResolveCandidate(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    confidence: float
    reason: str


class ResolveProductResponse(BaseModel):
    candidates: list[ResolveCandidate]
    requires_confirmation: bool


class ExplainAlertResponse(BaseModel):
    alert_id: uuid.UUID
    product_id: uuid.UUID
    alert_type: str
    severity: str
    title: str
    explanation: str
    evidence: dict[str, Any]
    provider: str
