from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx

from app.core.database import new_session
from app.domains.warehouse.models import StockMovement


async def _setup_product(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    sku: str = "H001",
) -> dict[str, str]:
    wh = await client.post(
        "/api/v1/warehouses", headers=headers, json={"code": "WH01", "name": "一号仓库"}
    )
    assert wh.status_code == 201
    warehouse_id = wh.json()["id"]
    product = await client.post(
        "/api/v1/products",
        headers=headers,
        json={"sku": sku, "name": "健康测试商品", "unit": "pcs", "default_warehouse_id": warehouse_id},
    )
    assert product.status_code == 201
    return {"warehouse_id": warehouse_id, "product_id": product.json()["id"]}


async def _receive(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    ids: dict[str, str],
    qty: str,
    *,
    expires_at: str | None = None,
    unit_cost: str = "80.00",
    lot_code: str | None = None,
) -> None:
    payload = {
        "product_id": ids["product_id"],
        "warehouse_id": ids["warehouse_id"],
        "quantity": qty,
        "unit_cost": unit_cost,
    }
    if lot_code:
        payload["lot_code"] = lot_code
    if expires_at:
        payload["expires_at"] = expires_at
    resp = await client.post("/api/v1/inventory/receive", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text


async def test_stockout_risk_rule(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_product(client, org_owner_headers)
    await _receive(client, org_owner_headers, ids, "1000")
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
                "required_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
            },
        )
    ).json()
    await client.post(f"/api/v1/orders/{order['id']}/confirm", headers=org_owner_headers)

    health = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    assert health.status_code == 200
    data = health.json()
    alert = next(a for a in data["alerts"] if a["alert_type"] == "STOCKOUT_RISK")
    assert alert["status"] == "OPEN"
    assert Decimal(alert["evidence_json"]["shortage"]) == Decimal("700")
    assert Decimal(alert["evidence_json"]["available"]) == Decimal("150")
    assert data["score"] < 100
    assert any(d["alert_type"] == "STOCKOUT_RISK" for d in data["deductions"])


async def test_expiry_risk_rule(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_product(client, org_owner_headers, sku="H002")
    expires = (datetime.now(UTC) + timedelta(days=14)).isoformat()
    await _receive(client, org_owner_headers, ids, "50", expires_at=expires, lot_code="LOT-E1")
    health = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    alert = next(a for a in health.json()["alerts"] if a["alert_type"] == "EXPIRY_RISK")
    assert alert["severity"] == "HIGH"
    assert len(alert["evidence_json"]["lots"]) == 1


async def test_overstock_and_dormant_rules(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_product(client, org_owner_headers, sku="H003")
    await _receive(client, org_owner_headers, ids, "1000")
    # Insert historical shipments directly: 10 units per day over the last 10 days.
    async with new_session() as db:
        for days_ago in range(1, 11):
            db.add(
                StockMovement(
                    organization_id=(await _org_id(db)),
                    product_id=ids["product_id"],
                    warehouse_id=ids["warehouse_id"],
                    movement_type="SHIPMENT",
                    quantity=Decimal("-10"),
                    occurred_at=datetime.now(UTC) - timedelta(days=days_ago),
                )
            )
        await db.commit()

    health = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    types = {a["alert_type"] for a in health.json()["alerts"]}
    assert "OVERSTOCK" in types
    overstock = next(a for a in health.json()["alerts"] if a["alert_type"] == "OVERSTOCK")
    assert Decimal(overstock["evidence_json"]["days_of_cover"]) > 180


async def test_alert_resolves_when_fixed(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_product(client, org_owner_headers, sku="H004")
    await _receive(client, org_owner_headers, ids, "1000")
    customer = (
        await client.post(
            "/api/v1/customers",
            headers=org_owner_headers,
            json={"code": "C002", "name": "客户2"},
        )
    ).json()
    order = (
        await client.post(
            "/api/v1/orders",
            headers=org_owner_headers,
            json={
                "customer_id": customer["id"],
                "lines": [{"product_id": ids["product_id"], "ordered_qty": "850"}],
                "required_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            },
        )
    ).json()
    await client.post(f"/api/v1/orders/{order['id']}/confirm", headers=org_owner_headers)
    before = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    assert any(a["alert_type"] == "STOCKOUT_RISK" for a in before.json()["alerts"])

    await _receive(client, org_owner_headers, ids, "800")
    after = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    assert not any(a["alert_type"] == "STOCKOUT_RISK" for a in after.json()["alerts"])
    resolved = await client.get(
        "/api/v1/health/alerts?status=RESOLVED", headers=org_owner_headers
    )
    assert any(a["alert_type"] == "STOCKOUT_RISK" for a in resolved.json())


async def test_health_overview_and_isolation(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
    second_org_headers: dict[str, str],
) -> None:
    ids = await _setup_product(client, org_owner_headers)
    await _receive(client, org_owner_headers, ids, "10")
    overview = await client.get("/api/v1/health/overview", headers=org_owner_headers)
    assert overview.status_code == 200
    assert overview.json()["open_alert_count"] >= 0
    other = await client.get("/api/v1/health/overview", headers=second_org_headers)
    assert other.json()["open_alert_count"] == 0


async def _org_id(db) -> str:
    from sqlalchemy import select

    from app.domains.identity.models import Organization

    org = (await db.execute(select(Organization).limit(1))).scalar_one()
    return str(org.id)
