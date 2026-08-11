from __future__ import annotations

import httpx


async def _setup_ai(client: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    product = await client.post(
        "/api/v1/products",
        headers=headers,
        json={"sku": "A001", "name": "铝合金板材", "barcode": "6901234567890", "unit": "pcs"},
    )
    assert product.status_code == 201
    return {"product_id": product.json()["id"]}


async def test_product_resolver_barcode_exact(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_ai(client, org_owner_headers)
    resp = await client.post(
        "/api/v1/ai/resolve-product",
        headers=org_owner_headers,
        json={"barcode": "6901234567890"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["product_id"] == ids["product_id"]
    assert data["candidates"][0]["confidence"] == 1.0
    assert data["requires_confirmation"] is False


async def test_product_resolver_text_needs_confirmation(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    await _setup_ai(client, org_owner_headers)
    resp = await client.post(
        "/api/v1/ai/resolve-product",
        headers=org_owner_headers,
        json={"text": "铝合金"},
    )
    data = resp.json()
    assert data["candidates"]
    assert data["requires_confirmation"] is True


async def test_employee_assistant_uses_knowledge_and_tools(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_ai(client, org_owner_headers)
    await client.post(
        "/api/v1/knowledge/documents",
        headers=org_owner_headers,
        json={
            "title": "A001 出库检查 SOP",
            "document_type": "SOP",
            "access_scope": "ORG",
            "content": "A001 出库前必须检查外观、数量与批次信息。",
            "entity_links": [
                {"entity_type": "PRODUCT", "entity_id": ids["product_id"], "relation_type": "SOP"}
            ],
        },
    )
    resp = await client.post(
        "/api/v1/ai/employee-assistant",
        headers=org_owner_headers,
        json={"query": "A001 出库前要检查什么？"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["provider"] == "demo"
    assert data["citations"]
    assert data["citations"][0]["document_title"] == "A001 出库检查 SOP"
    assert data["disclaimer"]


async def test_explain_alert_uses_evidence(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_ai(client, org_owner_headers)
    wh = await client.post(
        "/api/v1/warehouses", headers=org_owner_headers, json={"code": "WH01", "name": "WH"}
    )
    await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": wh.json()["id"],
            "quantity": "1000",
            "unit_cost": "80.00",
        },
    )
    customer = (
        await client.post(
            "/api/v1/customers",
            headers=org_owner_headers,
            json={"code": "C001", "name": "客户"},
        )
    ).json()
    order = (
        await client.post(
            "/api/v1/orders",
            headers=org_owner_headers,
            json={
                "customer_id": customer["id"],
                "lines": [{"product_id": ids["product_id"], "ordered_qty": "850"}],
                "required_at": "2026-08-14T00:00:00Z",
            },
        )
    ).json()
    await client.post(f"/api/v1/orders/{order['id']}/confirm", headers=org_owner_headers)
    health = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    alert = next(a for a in health.json()["alerts"] if a["alert_type"] == "STOCKOUT_RISK")
    explanation = await client.post(
        f"/api/v1/ai/explain-alert/{alert['id']}", headers=org_owner_headers, json={}
    )
    assert explanation.status_code == 200
    data = explanation.json()
    from decimal import Decimal

    assert Decimal(data["evidence"]["shortage"]) == Decimal("700")
    assert data["provider"] == "demo"
    assert "证据" in data["explanation"] or data["explanation"]


async def test_forecast_disabled_by_default(client: httpx.AsyncClient) -> None:
    capabilities = await client.get("/api/v1/forecast/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["enabled"] is False
    price = await client.post(
        "/api/v1/forecast/price",
        json={"subject_id": "A001", "horizon": "14d", "params": {"window": 30}},
    )
    assert price.status_code == 200
    assert price.json()["enabled"] is False
    assert price.json()["points"] == []
    assert price.json()["subject_id"] == "A001"
    assert price.json()["horizon"] == "14d"


async def test_ai_capabilities_exposed(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/ai/capabilities", headers=org_owner_headers)
    assert resp.status_code == 200
    assert resp.json()["provider"] == "demo"
    assert resp.json()["capability"]["supports_text"] is True
