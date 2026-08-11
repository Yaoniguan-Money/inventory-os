from __future__ import annotations

import json
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.domains.catalog.models import Product
from app.domains.health.models import InventoryAlert
from app.domains.knowledge.service import search_knowledge
from app.domains.market.service import get_product_market
from app.domains.pricing.service import get_prices
from app.domains.purchasing.service import incoming_for_product
from app.domains.warehouse.models import InventoryBalance
from app.domains.warehouse.service import expired_lot_quantity
from app.providers.ai import get_ai_provider


async def _query_product(db: AsyncSession, organization_id: str, product_id: str) -> dict:
    product = (
        await db.execute(
            select(Product).where(
                Product.id == uuid.UUID(product_id),
                Product.organization_id == uuid.UUID(organization_id),
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise NotFoundError("商品不存在")
    return {"sku": product.sku, "name": product.name, "status": product.status}


async def _query_inventory(db: AsyncSession, organization_id: str, product_id: str) -> dict:
    balances = (
        await db.execute(
            select(InventoryBalance).where(
                InventoryBalance.organization_id == uuid.UUID(organization_id),
                InventoryBalance.product_id == uuid.UUID(product_id),
            )
        )
    ).scalars().all()
    on_hand = sum((b.on_hand for b in balances), Decimal("0"))
    reserved = sum((b.reserved for b in balances), Decimal("0"))
    expired = await expired_lot_quantity(
        db, organization_id=organization_id, product_id=product_id
    )
    incoming = await incoming_for_product(
        db, organization_id=organization_id, product_id=product_id
    )
    return {
        "on_hand": str(on_hand),
        "reserved": str(reserved),
        "expired_qty": str(expired),
        "available": str(max(on_hand - reserved - expired, Decimal("0"))),
        "incoming": str(incoming),
    }


async def _query_prices(
    db: AsyncSession, organization_id: str, product_id: str, scopes: set[str]
) -> dict:
    prices = await get_prices(db, organization_id=organization_id, product_id=product_id)
    result: dict = {}
    if "pricing:cost:read" in scopes:
        result["last_purchase_price"] = (
            str(prices["last_purchase_price"].price) if prices["last_purchase_price"] else None
        )
        result["weighted_avg_cost"] = (
            str(prices["weighted_avg_cost"].price) if prices["weighted_avg_cost"] else None
        )
    if "pricing:internal:read" in scopes:
        result["target_sell_price"] = (
            str(prices["target_sell_price"].price) if prices["target_sell_price"] else None
        )
        result["actual_sell_price"] = (
            str(prices["actual_sell_price"].price) if prices["actual_sell_price"] else None
        )
    return result


async def _query_market(db: AsyncSession, organization_id: str, product_id: str) -> dict:
    market = await get_product_market(
        db, organization_id=organization_id, product_id=product_id
    )
    return {
        "quotes": [
            {
                "kind": q.quote_kind,
                "price": str(q.price),
                "currency": q.currency,
                "source": q.source,
                "unit": q.unit,
                "basis": q.basis,
                "observed_at": q.observed_at.isoformat(),
            }
            for q in market["quotes"]
        ],
        "events": [
            {"title": e.title, "source": e.source, "published_at": e.published_at.isoformat()}
            for e in market["events"]
        ],
    }


def _parse_vision_json(raw: str) -> dict:
    """解析视觉 Provider 的结构化输出，容忍 ```json 代码块。"""

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


async def employee_assistant(
    db: AsyncSession,
    *,
    organization_id: str,
    user_role: str,
    scopes: set[str],
    query: str,
) -> dict:
    kb = await search_knowledge(
        db,
        organization_id=organization_id,
        user_role=user_role,
        query=query,
        entity_type=None,
        entity_id=None,
        limit=5,
    )
    tools_result: list[dict] = []
    product_id: str | None = None
    # 尝试从提问中解析商品
    if "products:read" in scopes:
        for product in (
            await db.execute(
                select(Product)
                .where(Product.organization_id == uuid.UUID(organization_id))
                .limit(50)
            )
        ).scalars():
            if product.sku.lower() in query.lower() or product.name.lower() in query.lower():
                product_id = str(product.id)
                break

    if product_id:
        if "products:read" in scopes:
            tools_result.append(
                {
                    "label": f"商品 {product_id}",
                    "value": await _query_product(db, organization_id, product_id),
                }
            )
        if "inventory:read" in scopes:
            tools_result.append(
                {
                    "label": "库存",
                    "value": await _query_inventory(db, organization_id, product_id),
                }
            )
        if "pricing:cost:read" in scopes or "pricing:internal:read" in scopes:
            tools_result.append(
                {
                    "label": "价格",
                    "value": await _query_prices(db, organization_id, product_id, scopes),
                }
            )
        if "market:read" in scopes:
            tools_result.append(
                {"label": "市场", "value": await _query_market(db, organization_id, product_id)}
            )

    evidence_lines = [f"- {kb_hit['document_title']}: {kb_hit['excerpt']}" for kb_hit in kb["hits"]]
    if product_id:
        for item in tools_result:
            evidence_lines.append(f"- {item['label']}: {item['value']}")

    provider = get_ai_provider()
    answer = await provider.complete(
        system=(
            "你是 InventoryOS 内部员工助手。只能使用给定的证据回答；"
            "业务数字必须来自工具结果；知识引用必须标注文档标题；不得编造。"
        ),
        user=f"问题：{query}\n\n可用证据：\n" + "\n".join(evidence_lines or ["（无匹配证据）"]),
        tools_result=tools_result,
    )
    return {
        "answer": answer,
        "citations": [
            {
                "document_id": hit["document_id"],
                "document_title": hit["document_title"],
                "excerpt": hit["excerpt"],
            }
            for hit in kb["hits"]
        ],
        "tools": {item["label"]: item["value"] for item in tools_result},
        "provider": provider.name,
    }


async def resolve_product(
    db: AsyncSession,
    *,
    organization_id: str,
    barcode: str | None,
    text: str | None,
    image_data_url: str | None,
) -> dict:
    candidates: list[dict] = []
    if barcode:
        exact = (
            await db.execute(
                select(Product).where(
                    Product.organization_id == uuid.UUID(organization_id),
                    Product.barcode == barcode,
                )
            )
        ).scalars().all()
        for product in exact:
            candidates.append(
                {
                    "product_id": product.id,
                    "sku": product.sku,
                    "name": product.name,
                    "confidence": 1.0,
                    "reason": "barcode exact match",
                }
            )
    if text or (image_data_url and not candidates):
        search_text = text or ""
        search_terms: list[str] = []
        vision_barcode: str | None = None
        if image_data_url and not text:
            provider = get_ai_provider()
            if provider.capability.supports_vision:
                raw = await provider.vision(
                    system=(
                        "你是商品识别助手，只输出 JSON，不要输出其它文字。"
                        '格式: {"sku_candidates": [], "model": "", "barcode": "", "keywords": []}'
                    ),
                    prompt="识别图片中的商品，输出 SKU 候选、型号、条码与关键词。",
                    image_data_url=image_data_url,
                )
                parsed = _parse_vision_json(raw)
                vision_barcode = parsed.get("barcode")
                search_terms = [
                    *[str(x) for x in parsed.get("sku_candidates", [])],
                    *[str(x) for x in parsed.get("keywords", [])],
                ]
                if parsed.get("model"):
                    search_terms.append(str(parsed["model"]))
        if vision_barcode:
            rows = (
                await db.execute(
                    select(Product).where(
                        Product.organization_id == uuid.UUID(organization_id),
                        Product.barcode == vision_barcode,
                    )
                )
            ).scalars().all()
            for product in rows:
                candidates.append(
                    {
                        "product_id": product.id,
                        "sku": product.sku,
                        "name": product.name,
                        "confidence": 0.99,
                        "reason": "vision barcode match",
                    }
                )
        search_terms = [t for t in search_terms if t]
        if not search_terms and search_text:
            search_terms = [search_text]
        seen_ids = {str(c["product_id"]) for c in candidates}
        for term in search_terms:
            like = f"%{term.strip()}%"
            rows = (
                await db.execute(
                    select(Product).where(
                        Product.organization_id == uuid.UUID(organization_id),
                        (Product.sku.ilike(like))
                        | (Product.name.ilike(like))
                        | (Product.barcode.ilike(like)),
                    )
                )
            ).scalars().all()
            for product in rows[:5]:
                if str(product.id) in seen_ids:
                    continue
                seen_ids.add(str(product.id))
                candidates.append(
                    {
                        "product_id": product.id,
                        "sku": product.sku,
                        "name": product.name,
                        "confidence": (
                            0.9 if product.sku == term.strip() or product.barcode == term.strip() else 0.7
                        ),
                        "reason": "text/vision search match",
                    }
                )
    requires_confirmation = not (len(candidates) == 1 and candidates[0]["confidence"] >= 0.99)
    return {
        "candidates": candidates,
        "requires_confirmation": requires_confirmation,
    }


async def explain_alert(
    db: AsyncSession,
    *,
    organization_id: str,
    alert_id: str,
) -> dict:
    alert = (
        await db.execute(
            select(InventoryAlert).where(
                InventoryAlert.id == uuid.UUID(alert_id),
                InventoryAlert.organization_id == uuid.UUID(organization_id),
            )
        )
    ).scalar_one_or_none()
    if alert is None:
        raise NotFoundError("告警不存在")
    evidence = alert.evidence_json
    provider = get_ai_provider()
    explanation = await provider.complete(
        system=(
            "你是 InventoryOS 风险解释助手。只能基于告警的 evidence 解释，"
            "不得编造数字，输出简洁的中文解释。"
        ),
        user=f"告警类型 {alert.alert_type}（{alert.title}）\n证据：{evidence}",
        tools_result=[{"label": "evidence", "value": evidence}],
    )
    return {
        "alert_id": alert.id,
        "product_id": alert.product_id,
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "title": alert.title,
        "explanation": explanation,
        "evidence": evidence,
        "provider": provider.name,
    }
