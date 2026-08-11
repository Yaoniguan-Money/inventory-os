from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.core.database import new_session
from app.core.security import create_access_token
from app.domains.identity.models import User


async def _setup(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    sku: str = "R3-01",
    wh_prefix: str = "WH0",
) -> dict[str, str]:
    wh1 = await client.post(
        "/api/v1/warehouses", headers=headers, json={"code": f"{wh_prefix}1", "name": "一号仓"}
    )
    wh2 = await client.post(
        "/api/v1/warehouses", headers=headers, json={"code": f"{wh_prefix}2", "name": "二号仓"}
    )
    product = await client.post(
        "/api/v1/products",
        headers=headers,
        json={"sku": sku, "name": "第三轮商品", "default_warehouse_id": wh1.json()["id"]},
    )
    return {
        "product_id": product.json()["id"],
        "wh1": wh1.json()["id"],
        "wh2": wh2.json()["id"],
    }


async def _receive(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    product_id: str,
    warehouse_id: str,
    qty: str,
    cost: str,
) -> None:
    resp = await client.post(
        "/api/v1/inventory/receive",
        headers=headers,
        json={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity": qty,
            "unit_cost": cost,
            "lot_code": f"LOT-{warehouse_id[-4:]}-{qty}",
        },
    )
    assert resp.status_code == 201, resp.text


async def test_global_weighted_avg_cost_across_warehouses(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="COST-G")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100", "80.00")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh2"], "100", "100.00")
    prices = await client.get(
        f"/api/v1/products/{ids['product_id']}/prices", headers=org_owner_headers
    )
    assert Decimal(prices.json()["weighted_avg_cost"]["price"]) == Decimal("90")


async def test_issue_and_adjust_respect_reserved(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="RSV-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100", "50.00")
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": "C-RSV", "name": "预留保护客户"},
    )
    order = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": ids["product_id"], "ordered_qty": "80"}],
        },
    )
    await client.post(f"/api/v1/orders/{order.json()['id']}/confirm", headers=org_owner_headers)
    equipment = await client.post(
        "/api/v1/equipment",
        headers=org_owner_headers,
        json={"asset_code": "E-RSV", "name": "预留保护设备"},
    )
    equipment_id = equipment.json()["id"]

    # 领 30：可用只有 20，应被拒绝。
    denied = await client.post(
        f"/api/v1/equipment/{equipment_id}/maintenance",
        headers=org_owner_headers,
        json={
            "maintenance_type": "REPLACE_PART",
            "parts": [{"product_id": ids["product_id"], "quantity": "30"}],
        },
    )
    assert denied.status_code == 409
    assert "已预留" in denied.json()["error"]["message"]

    # 手工负调整 -30：同样应被拒绝。
    adjust = await client.post(
        "/api/v1/inventory/adjust",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["wh1"],
            "quantity": "-30",
            "reason": "试图挪用预留",
        },
    )
    assert adjust.status_code == 409
    assert "已预留" in adjust.json()["error"]["message"]

    # 领 20（=可用）成功。
    ok = await client.post(
        f"/api/v1/equipment/{equipment_id}/maintenance",
        headers=org_owner_headers,
        json={
            "maintenance_type": "REPLACE_PART",
            "parts": [{"product_id": ids["product_id"], "quantity": "20"}],
        },
    )
    assert ok.status_code == 201, ok.text
    inv = await client.get(f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers)
    assert Decimal(inv.json()["on_hand"]) == Decimal("80")
    assert Decimal(inv.json()["available"]) == Decimal("0")


async def test_market_dedupe_is_per_product(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids_a = await _setup(client, org_owner_headers, sku="SHARE-A")
    ids_b = await _setup(client, org_owner_headers, sku="SHARE-B", wh_prefix="WH1")
    for product_id in (ids_a["product_id"], ids_b["product_id"]):
        resp = await client.post(
            f"/api/v1/products/{product_id}/market-mappings",
            headers=org_owner_headers,
            json={"provider": "mock", "external_symbol": "ALUMINUM", "region": "DOMESTIC"},
        )
        assert resp.status_code == 201
    await client.post("/api/v1/market/refresh", headers=org_owner_headers)
    market_a = await client.get(
        f"/api/v1/products/{ids_a['product_id']}/market", headers=org_owner_headers
    )
    market_b = await client.get(
        f"/api/v1/products/{ids_b['product_id']}/market", headers=org_owner_headers
    )
    assert len(market_a.json()["quotes"]) == 2
    assert len(market_b.json()["quotes"]) == 2
    assert len(market_a.json()["events"]) >= 1
    assert len(market_b.json()["events"]) >= 1


async def test_ai_provider_configuration_is_explicit(monkeypatch) -> None:
    from app.core.errors import AppError
    from app.providers.ai import get_ai_provider
    from app.providers.ai import settings as ai_settings

    monkeypatch.setattr(ai_settings, "ai_provider", "opneai")
    try:
        get_ai_provider()
        raise AssertionError("未知 Provider 应报错")
    except ValueError as exc:
        assert "未知 AI Provider" in str(exc)

    monkeypatch.setattr(ai_settings, "ai_provider", "openai")
    monkeypatch.setattr(ai_settings, "ai_api_key", "")
    provider = get_ai_provider()
    assert provider.name == "disabled"
    assert provider.capability.supports_text is False
    try:
        await provider.complete(system="s", user="u")
        raise AssertionError("禁用 Provider 应显式失败")
    except AppError as exc:
        assert "AI_API_KEY" in exc.message


async def test_knowledge_detail_hides_owner_doc(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    doc = await client.post(
        "/api/v1/knowledge/documents",
        headers=org_owner_headers,
        json={
            "title": "管理层文档详情",
            "document_type": "POLICY",
            "access_scope": "OWNER",
            "content": "仅管理层可见的正文。",
        },
    )
    assert doc.status_code == 201
    doc_id = doc.json()["id"]
    created = await client.post(
        "/api/v1/users",
        headers=org_owner_headers,
        json={
            "email": "detail-viewer@example.com",
            "password": "Detail@12345",
            "display_name": "详情查看员",
            "role": "WAREHOUSE",
        },
    )
    assert created.status_code == 201
    async with new_session() as db:
        viewer = (
            await db.execute(select(User).where(User.email == "detail-viewer@example.com"))
        ).scalar_one()
        token = create_access_token(str(viewer.id))
    denied = await client.get(
        f"/api/v1/knowledge/documents/{doc_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 404
    allowed = await client.get(f"/api/v1/knowledge/documents/{doc_id}", headers=org_owner_headers)
    assert allowed.status_code == 200


async def test_maintenance_fault_must_belong_to_equipment(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    e1 = await client.post(
        "/api/v1/equipment",
        headers=org_owner_headers,
        json={"asset_code": "E-OWN", "name": "故障设备"},
    )
    e2 = await client.post(
        "/api/v1/equipment",
        headers=org_owner_headers,
        json={"asset_code": "E-OTHER", "name": "无关设备"},
    )
    fault = await client.post(
        f"/api/v1/equipment/{e1.json()['id']}/faults",
        headers=org_owner_headers,
        json={"fault_code": "X1", "symptom": "故障", "severity": "HIGH"},
    )
    assert fault.status_code == 201
    denied = await client.post(
        f"/api/v1/equipment/{e2.json()['id']}/maintenance",
        headers=org_owner_headers,
        json={
            "fault_record_id": fault.json()["id"],
            "maintenance_type": "REPAIR",
            "result": "COMPLETED",
        },
    )
    assert denied.status_code == 404
    ok = await client.post(
        f"/api/v1/equipment/{e1.json()['id']}/maintenance",
        headers=org_owner_headers,
        json={
            "fault_record_id": fault.json()["id"],
            "maintenance_type": "REPAIR",
            "result": "COMPLETED",
        },
    )
    assert ok.status_code == 201


async def test_demand_uses_line_date_precedence(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="DATE-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100", "80.00")
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": "C-DATE", "name": "日期客户"},
    )
    # 订单头 3 天后，但行级明确 10 天后 → 行级优先，不属于 7 日窗口。
    order = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [
                {
                    "product_id": ids["product_id"],
                    "ordered_qty": "60",
                    "required_at": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
                }
            ],
            "required_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
        },
    )
    await client.post(f"/api/v1/orders/{order.json()['id']}/confirm", headers=org_owner_headers)
    wb = await client.get("/api/v1/purchase-workbench", headers=org_owner_headers)
    item = next(i for i in wb.json() if i["product_id"] == ids["product_id"])
    assert Decimal(item["demand_7d"]) == Decimal("0")
    health = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    assert not any(a["alert_type"] == "STOCKOUT_RISK" for a in health.json()["alerts"])


async def test_vision_resolver_uses_structured_output(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str], monkeypatch
) -> None:
    product = await client.post(
        "/api/v1/products",
        headers=org_owner_headers,
        json={"sku": "ABC-123", "name": "伺服电机", "barcode": "6909876543210"},
    )
    assert product.status_code == 201

    class FakeVisionProvider:
        name = "fake_vision"

        @property
        def capability(self):
            from app.providers.ai.base import ProviderCapability

            return ProviderCapability(
                supports_text=True,
                supports_vision=True,
                supports_tool_calling=False,
                supports_streaming=False,
            )

        async def complete(self, *, system, user, tools_result=None):
            return "fake"

        async def vision(self, *, system, prompt, image_data_url):
            return '{"sku_candidates": ["ABC-123"], "model": "SM-750", "barcode": "", "keywords": []}'

    monkeypatch.setattr(
        "app.domains.intelligence.service.get_ai_provider", lambda: FakeVisionProvider()
    )
    resp = await client.post(
        "/api/v1/ai/resolve-product",
        headers=org_owner_headers,
        json={"image_data_url": "data:image/png;base64,AAAA"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any(c["sku"] == "ABC-123" for c in data["candidates"])
    assert data["requires_confirmation"] is True
