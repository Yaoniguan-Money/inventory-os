from __future__ import annotations

import httpx

from app.core.database import new_session


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

    from decimal import Decimal

    from sqlalchemy import select

    from app.domains.orders.models import InventoryReservation, SalesOrderLine
    from app.domains.warehouse.models import InventoryBalance

    async with new_session() as db:
        line = (
            await db.execute(
                select(SalesOrderLine).where(SalesOrderLine.sales_order_id == order["id"])
            )
        ).scalar_one()
        line.reserved_qty = Decimal("0")
        balance = (
            await db.execute(
                select(InventoryBalance).where(
                    InventoryBalance.product_id == ids["product_id"]
                )
            )
        ).scalar_one()
        balance.reserved = Decimal("0")
        balance.on_hand = Decimal("400")
        for reservation in (
            await db.execute(
                select(InventoryReservation).where(
                    InventoryReservation.sales_order_line_id == line.id,
                    InventoryReservation.status == "ACTIVE",
                )
            )
        ).scalars():
            reservation.status = "RELEASED"
            reservation.quantity = Decimal("0")
        await db.commit()

    health = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    alert = next(a for a in health.json()["alerts"] if a["alert_type"] == "STOCKOUT_RISK")
    explanation = await client.post(
        f"/api/v1/ai/explain-alert/{alert['id']}", headers=org_owner_headers, json={}
    )
    assert explanation.status_code == 200
    data = explanation.json()
    assert Decimal(data["evidence"]["shortage"]) == Decimal("450")
    assert data["provider"] == "demo"
    assert "证据" in data["explanation"] or data["explanation"]


async def test_forecast_disabled_by_default(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    capabilities = await client.get("/api/v1/forecast/capabilities", headers=org_owner_headers)
    assert capabilities.status_code == 200
    assert capabilities.json()["enabled"] is False
    price = await client.post(
        "/api/v1/forecast/price",
        headers=org_owner_headers,
        json={"subject_id": "A001", "horizon": "14d", "params": {"window": 30}},
    )
    assert price.status_code == 200
    assert price.json()["enabled"] is False
    assert price.json()["points"] == []
    assert price.json()["subject_id"] == "A001"
    assert price.json()["horizon"] == "14d"


async def test_forecast_requires_market_scope(client: httpx.AsyncClient) -> None:
    capabilities = await client.get("/api/v1/forecast/capabilities")
    assert capabilities.status_code == 401
    price = await client.post(
        "/api/v1/forecast/price", json={"subject_id": "A001", "horizon": "30d"}
    )
    assert price.status_code == 401


async def test_ai_capabilities_exposed(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/ai/capabilities", headers=org_owner_headers)
    assert resp.status_code == 200
    assert resp.json()["provider"] == "demo"
    assert resp.json()["capability"]["supports_text"] is True
