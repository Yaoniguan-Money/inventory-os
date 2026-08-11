from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.core.database import new_session
from app.core.security import create_access_token
from app.domains.identity.models import User


async def _setup_two_warehouses(
    client: httpx.AsyncClient, headers: dict[str, str], *, sku: str = "MW01"
) -> dict[str, str]:
    wh1 = await client.post(
        "/api/v1/warehouses", headers=headers, json={"code": "WH01", "name": "一号仓"}
    )
    wh2 = await client.post(
        "/api/v1/warehouses", headers=headers, json={"code": "WH02", "name": "二号仓"}
    )
    product = await client.post(
        "/api/v1/products",
        headers=headers,
        json={"sku": sku, "name": "多仓商品", "default_warehouse_id": wh1.json()["id"]},
    )
    assert product.status_code == 201
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
    *,
    cost: str = "80.00",
    lot: str | None = None,
    location: str | None = None,
) -> None:
    payload = {
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "quantity": qty,
        "unit_cost": cost,
    }
    if lot:
        payload["lot_code"] = lot
    if location:
        payload["location_id"] = location
    resp = await client.post("/api/v1/inventory/receive", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text


async def test_multi_warehouse_aggregation(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_two_warehouses(client, org_owner_headers)
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100", lot="L1")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh2"], "50", lot="L2")

    single = await client.get(
        f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers
    )
    assert single.status_code == 200
    assert single.json()["warehouse_code"] == "ALL"
    assert Decimal(single.json()["on_hand"]) == Decimal("150")
    assert Decimal(single.json()["available"]) == Decimal("150")

    health = await client.get("/api/v1/health/overview", headers=org_owner_headers)
    assert health.status_code == 200
    item = next(
        p for p in health.json()["products"] if p["product_id"] == ids["product_id"]
    )
    assert item["score"] >= 0

    wb = await client.get("/api/v1/purchase-workbench", headers=org_owner_headers)
    assert wb.status_code == 200
    wb_item = next(i for i in wb.json() if i["product_id"] == ids["product_id"])
    assert Decimal(wb_item["on_hand"]) == Decimal("150")
    assert Decimal(wb_item["available"]) == Decimal("150")

    # 聚合后可用 150（默认仓库可用 100），订单 80 可正常确认
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": "C-MW", "name": "多仓客户"},
    )
    order = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": ids["product_id"], "ordered_qty": "80"}],
        },
    )
    confirmed = await client.post(
        f"/api/v1/orders/{order.json()['id']}/confirm", headers=org_owner_headers
    )
    assert confirmed.status_code == 200, confirmed.text
    after = await client.get(
        f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers
    )
    assert Decimal(after.json()["reserved"]) == Decimal("80")
    assert Decimal(after.json()["available"]) == Decimal("70")


async def test_workbench_demand_uses_order_required_at(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_two_warehouses(client, org_owner_headers, sku="DEM-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100")
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": "C-DEM", "name": "需求客户"},
    )
    order = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": ids["product_id"], "ordered_qty": "60"}],
            "required_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
        },
    )
    await client.post(f"/api/v1/orders/{order.json()['id']}/confirm", headers=org_owner_headers)
    wb = await client.get("/api/v1/purchase-workbench", headers=org_owner_headers)
    item = next(i for i in wb.json() if i["product_id"] == ids["product_id"])
    assert Decimal(item["demand_7d"]) == Decimal("60")


async def _sales_token(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    created = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": "sales@example.com",
            "password": "Sales@12345",
            "display_name": "销售",
            "role": "SALES",
        },
    )
    assert created.status_code == 201
    async with new_session() as db:
        user = (
            await db.execute(select(User).where(User.email == "sales@example.com"))
        ).scalar_one()
        return create_access_token(str(user.id))


async def test_assistant_respects_cost_scope(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_two_warehouses(client, org_owner_headers, sku="SEC-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100", cost="80.00")
    await client.post(
        f"/api/v1/products/{ids['product_id']}/target-price",
        headers=org_owner_headers,
        json={"price": "120.00"},
    )
    token = await _sales_token(client, org_owner_headers)
    resp = await client.post(
        "/api/v1/ai/employee-assistant",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "SEC-01 的成本是多少？"},
    )
    assert resp.status_code == 200
    data = resp.json()
    price_tool = next((v for k, v in data["tools"].items() if "价格" in k), None)
    # SALES 有 pricing:internal:read（目标/成交价），但没有 pricing:cost:read
    if price_tool is not None:
        values = price_tool if isinstance(price_tool, dict) else {}
        serialized = str(values)
        assert "weighted_avg_cost" not in serialized
        assert "last_purchase_price" not in serialized
    assert "weighted_avg_cost" not in data["answer"]
    assert "last_purchase_price" not in data["answer"]


async def test_api_key_scopes_enforced(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    await _setup_two_warehouses(client, org_owner_headers, sku="KEY-01")
    key = await client.post(
        "/api/v1/integrations/api-keys",
        headers=org_owner_headers,
        json={"name": "receive-only", "scopes": ["inventory:receive"]},
    )
    assert key.status_code == 201
    api_key = key.json()["api_key"]
    receive_envelope = {
        "schema_version": "1.0",
        "event_id": "key-001",
        "type": "inventory.received",
        "source": "erp",
        "data": {"sku": "KEY-01", "warehouse": "WH01", "quantity": "10"},
    }
    ok = await client.post(
        "/api/v1/integrations/events",
        headers={"X-API-Key": api_key},
        json=receive_envelope,
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "accepted"

    adjust_envelope = {
        "schema_version": "1.0",
        "event_id": "key-002",
        "type": "inventory.adjusted",
        "source": "erp",
        "data": {"sku": "KEY-01", "warehouse": "WH01", "quantity": "-1"},
    }
    denied = await client.post(
        "/api/v1/integrations/events",
        headers={"X-API-Key": api_key},
        json=adjust_envelope,
    )
    assert denied.status_code == 403
    assert "inventory:adjust" in denied.json()["error"]["message"]

    readonly_key = await client.post(
        "/api/v1/integrations/api-keys",
        headers=org_owner_headers,
        json={"name": "readonly", "scopes": []},
    )
    readonly = readonly_key.json()["api_key"]
    denied2 = await client.post(
        "/api/v1/integrations/events",
        headers={"X-API-Key": readonly},
        json=receive_envelope,
    )
    assert denied2.status_code == 403


async def test_workbench_includes_reserved_history_and_market_events(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_two_warehouses(client, org_owner_headers, sku="WB-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100", cost="82.00")
    await client.post(
        f"/api/v1/products/{ids['product_id']}/market-mappings",
        headers=org_owner_headers,
        json={"provider": "mock", "external_symbol": "WB-SYM", "region": "DOMESTIC"},
    )
    await client.post("/api/v1/market/refresh", headers=org_owner_headers)
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": "C-WB", "name": "工作台客户"},
    )
    order = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": ids["product_id"], "ordered_qty": "40"}],
        },
    )
    await client.post(f"/api/v1/orders/{order.json()['id']}/confirm", headers=org_owner_headers)
    wb = await client.get("/api/v1/purchase-workbench", headers=org_owner_headers)
    item = next(i for i in wb.json() if i["product_id"] == ids["product_id"])
    assert Decimal(item["reserved"]) == Decimal("40")
    assert len(item["purchase_history"]) >= 1
    assert Decimal(item["purchase_history"][0]["quantity"]) == Decimal("100")
    assert Decimal(item["purchase_history"][0]["unit_cost"]) == Decimal("82")
    assert len(item["market_events"]) >= 1
    assert item["market_events"][0]["source"] == "MockMarketProvider (Demo)"
    assert item["market_quotes"]["DOMESTIC"]["MARKET_BUY"]["observed_at"]


async def test_overview_and_lots_flagship_fields(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    wh = await client.post(
        "/api/v1/warehouses", headers=org_owner_headers, json={"code": "WH01", "name": "一号仓"}
    )
    loc = await client.post(
        f"/api/v1/warehouses/{wh.json()['id']}/locations",
        headers=org_owner_headers,
        json={"code": "A-01", "name": "A区01"},
    )
    product = await client.post(
        "/api/v1/products",
        headers=org_owner_headers,
        json={
            "sku": "FLAG-01",
            "name": "旗舰商品",
            "barcode": "6901112223334",
            "status": "ACTIVE",
            "default_warehouse_id": wh.json()["id"],
            "default_location_id": loc.json()["id"],
        },
    )
    product_id = product.json()["id"]
    await _receive(
        client,
        org_owner_headers,
        product_id,
        wh.json()["id"],
        "100",
        lot="LOT-FLAG",
        location=loc.json()["id"],
    )
    overview = await client.get(f"/api/v1/products/{product_id}/overview", headers=org_owner_headers)
    assert overview.status_code == 200
    data = overview.json()
    assert data["default_warehouse_code"] == "WH01"
    assert data["default_location_code"] == "A-01"
    assert data["health"]["score"] >= 0
    assert data["health"]["status"] in ("健康", "关注", "高风险")
    assert data["product"]["barcode"] == "6901112223334"
    lots = await client.get(f"/api/v1/inventory/{product_id}/lots", headers=org_owner_headers)
    assert lots.status_code == 200
    assert lots.json()[0]["location_code"] == "A-01"
    assert lots.json()[0]["received_at"]


async def test_inventory_list_has_spec_columns(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_two_warehouses(client, org_owner_headers, sku="INV-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100", lot="L-I1")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh2"], "50")
    listing = await client.get("/api/v1/inventory", headers=org_owner_headers)
    assert listing.status_code == 200
    rows = [r for r in listing.json() if r["product_id"] == ids["product_id"]]
    assert len(rows) == 2
    for row in rows:
        assert "incoming" in row
        assert row["health_status"] in ("NORMAL", "WARN", "HIGH")
        assert "last_receipt_at" in row
        assert "last_shipment_at" in row
        assert "default_location_code" in row
    assert any(row["last_receipt_at"] for row in rows)


async def test_order_filters_and_detail_risk_fields(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_two_warehouses(client, org_owner_headers, sku="ORD-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100")
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": "C-ORD", "name": "订单客户"},
    )
    due_order = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": ids["product_id"], "ordered_qty": "80"}],
            "required_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        },
    )
    await client.post(
        f"/api/v1/orders/{due_order.json()['id']}/confirm", headers=org_owner_headers
    )
    future_order = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": ids["product_id"], "ordered_qty": "10"}],
            "required_at": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
        },
    )
    await client.post(
        f"/api/v1/orders/{future_order.json()['id']}/confirm", headers=org_owner_headers
    )

    overdue = await client.get(
        "/api/v1/orders?overdue=true", headers=org_owner_headers
    )
    assert len(overdue.json()) == 1
    assert overdue.json()[0]["id"] == due_order.json()["id"]

    by_customer = await client.get(
        f"/api/v1/orders?customer_id={customer.json()['id']}", headers=org_owner_headers
    )
    assert len(by_customer.json()) == 2
    by_product = await client.get(
        f"/api/v1/orders?product_id={ids['product_id']}", headers=org_owner_headers
    )
    assert len(by_product.json()) == 2

    detail = await client.get(
        f"/api/v1/orders/{due_order.json()['id']}", headers=org_owner_headers
    )
    line = detail.json()["lines"][0]
    assert Decimal(line["available"]) == Decimal("10")
    assert "incoming" in line
    assert line["fulfillment_risk"] is True


async def test_dashboard_aggregation(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_two_warehouses(client, org_owner_headers, sku="DASH-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "1000", cost="200.00")
    await client.post(
        f"/api/v1/products/{ids['product_id']}/market-mappings",
        headers=org_owner_headers,
        json={"provider": "mock", "external_symbol": "DASH-SYM", "region": "DOMESTIC"},
    )
    await client.post("/api/v1/market/refresh", headers=org_owner_headers)
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": "C-DASH", "name": "驾驶舱客户"},
    )
    order = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": ids["product_id"], "ordered_qty": "850"}],
            "required_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
        },
    )
    await client.post(f"/api/v1/orders/{order.json()['id']}/confirm", headers=org_owner_headers)

    resp = await client.get("/api/v1/dashboard", headers=org_owner_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert Decimal(data["inventory_value"]) > 0
    assert data["orders_due"] >= 1
    assert data["at_risk_orders"] >= 1
    assert data["health_score"] >= 0
    assert data["pressure_7d"]
    assert any(p["sku"] == "DASH-01" for p in data["pressure_7d"])
    assert data["upcoming_orders"]
    assert any(o["order_no"] == order.json()["order_no"] for o in data["upcoming_orders"])
    assert data["recent_events"]
    assert data["market_anomalies"]
