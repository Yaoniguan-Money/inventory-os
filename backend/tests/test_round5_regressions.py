from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.core.database import new_session
from app.domains.orders.models import InventoryReservation, SalesOrderLine
from app.domains.warehouse.models import InventoryBalance, InventoryLot


async def _setup(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    sku: str = "R5-01",
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
        json={"sku": sku, "name": "第五轮商品", "unit": "件", "default_warehouse_id": wh1.json()["id"]},
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
    *,
    cost: str = "80.00",
    lot: str | None = None,
    expires_at: str | None = None,
) -> None:
    payload = {
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "quantity": qty,
        "unit_cost": cost,
    }
    if lot:
        payload["lot_code"] = lot
    if expires_at:
        payload["expires_at"] = expires_at
    resp = await client.post("/api/v1/inventory/receive", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text


async def _confirm_order(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    product_id: str,
    qty: str,
    *,
    required_at: str | None = None,
) -> dict:
    customer = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={"code": f"C-{uuid.uuid4().hex[:8]}", "name": "第五轮客户"},
    )
    payload = {
        "customer_id": customer.json()["id"],
        "lines": [{"product_id": product_id, "ordered_qty": qty}],
    }
    if required_at:
        payload["required_at"] = required_at
    order = await client.post("/api/v1/orders", headers=headers, json=payload)
    assert order.status_code == 201
    confirmed = await client.post(
        f"/api/v1/orders/{order.json()['id']}/confirm", headers=headers
    )
    return {"order": order.json(), "confirmed": confirmed}


async def test_health_overview_concurrent_no_500(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="CONC-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100")

    async def hit() -> int:
        resp = await client.get("/api/v1/health/overview", headers=org_owner_headers)
        return resp.status_code

    codes = await asyncio.gather(hit(), hit(), hit())
    assert codes == [200, 200, 200]


async def test_confirm_rejects_expired_stock(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="CEXP-01")
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"], "100",
        lot="LOT-PAST", expires_at=past,
    )
    result = await _confirm_order(client, org_owner_headers, ids["product_id"], "80")
    assert result["confirmed"].status_code == 409
    assert result["confirmed"].json()["error"]["code"] == "insufficient_stock"

    await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"], "100",
        lot="LOT-FRESH",
        expires_at=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
    )
    ok = await _confirm_order(client, org_owner_headers, ids["product_id"], "80")
    assert ok["confirmed"].status_code == 200


async def test_reserved_stock_expiring_reopens_risk(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="REXP-01")
    await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"], "100",
        lot="LOT-R",
        expires_at=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
    )
    await _confirm_order(
        client, org_owner_headers, ids["product_id"], "80",
        required_at=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
    )
    async with new_session() as db:
        lot = (
            await db.execute(
                select(InventoryLot).where(InventoryLot.product_id == ids["product_id"])
            )
        ).scalar_one()
        lot.expires_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()
    health = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    alerts = {a["alert_type"] for a in health.json()["alerts"]}
    assert "STOCKOUT_RISK" in alerts
    assert "ORDER_FULFILLMENT_RISK" in alerts
    dashboard = await client.get("/api/v1/dashboard", headers=org_owner_headers)
    assert dashboard.json()["at_risk_orders"] >= 1


async def test_workbench_shortage_uses_unreserved(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="WBUN-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100")
    await _confirm_order(
        client, org_owner_headers, ids["product_id"], "80",
        required_at=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
    )
    wb = await client.get("/api/v1/purchase-workbench", headers=org_owner_headers)
    item = next(i for i in wb.json() if i["product_id"] == ids["product_id"])
    assert Decimal(item["demand_7d"]) == Decimal("80")
    assert Decimal(item["reserved_for_due"]) == Decimal("80")
    assert Decimal(item["shortage_7d"]) == Decimal("0")


async def test_market_mapping_requires_own_product(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
    second_org_headers: dict[str, str],
) -> None:
    product = await client.post(
        "/api/v1/products",
        headers=org_owner_headers,
        json={"sku": "MAP-OWN", "name": "组织一商品"},
    )
    resp = await client.post(
        f"/api/v1/products/{product.json()['id']}/market-mappings",
        headers=second_org_headers,
        json={"provider": "mock", "external_symbol": "SYM", "region": "DOMESTIC"},
    )
    assert resp.status_code == 404


async def test_target_price_clear_single_truth(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    product = await client.post(
        "/api/v1/products",
        headers=org_owner_headers,
        json={"sku": "CLEAR-01", "name": "清空目标价", "target_sell_price": "118.00"},
    )
    product_id = product.json()["id"]
    await client.patch(
        f"/api/v1/products/{product_id}",
        headers=org_owner_headers,
        json={"target_sell_price": None},
    )
    prices = await client.get(f"/api/v1/products/{product_id}/prices", headers=org_owner_headers)
    assert prices.json()["target_sell_price"] is None
    assert any(
        p["price_type"] == "TARGET_SELL_PRICE" and p["source_reference_type"] == "CLEARED"
        for p in prices.json()["history"]
    )
    listing = await client.get("/api/v1/products", headers=org_owner_headers)
    row = next(p for p in listing.json() if p["id"] == product_id)
    assert row["target_sell_price"] is None


async def test_default_warehouse_location_mismatch_rejected(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    wh1 = await client.post(
        "/api/v1/warehouses", headers=org_owner_headers, json={"code": "WH01", "name": "一号仓"}
    )
    wh2 = await client.post(
        "/api/v1/warehouses", headers=org_owner_headers, json={"code": "WH02", "name": "二号仓"}
    )
    loc1 = await client.post(
        f"/api/v1/warehouses/{wh1.json()['id']}/locations",
        headers=org_owner_headers,
        json={"code": "L1", "name": "一仓库位"},
    )
    loc2 = await client.post(
        f"/api/v1/warehouses/{wh2.json()['id']}/locations",
        headers=org_owner_headers,
        json={"code": "L2", "name": "二仓库位"},
    )
    bad = await client.post(
        "/api/v1/products",
        headers=org_owner_headers,
        json={
            "sku": "PAIR-01",
            "name": "默认位错配",
            "default_warehouse_id": wh1.json()["id"],
            "default_location_id": loc2.json()["id"],
        },
    )
    assert bad.status_code == 409

    product = await client.post(
        "/api/v1/products",
        headers=org_owner_headers,
        json={
            "sku": "PAIR-02",
            "name": "默认位一致",
            "default_warehouse_id": wh1.json()["id"],
            "default_location_id": loc1.json()["id"],
        },
    )
    assert product.status_code == 201
    mismatch = await client.patch(
        f"/api/v1/products/{product.json()['id']}",
        headers=org_owner_headers,
        json={"default_warehouse_id": wh2.json()["id"]},
    )
    assert mismatch.status_code == 409
    fixed = await client.patch(
        f"/api/v1/products/{product.json()['id']}",
        headers=org_owner_headers,
        json={"default_warehouse_id": wh2.json()["id"], "default_location_id": loc2.json()["id"]},
    )
    assert fixed.status_code == 200


async def test_adjust_syncs_lots(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="ADJL-01")
    await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"], "100", lot="LOT-A"
    )
    for delta in ("-20", "+10", "-5"):
        resp = await client.post(
            "/api/v1/inventory/adjust",
            headers=org_owner_headers,
            json={
                "product_id": ids["product_id"],
                "warehouse_id": ids["wh1"],
                "quantity": delta,
                "reason": "盘点",
            },
        )
        assert resp.status_code == 200, resp.text
    inv = await client.get(f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers)
    assert Decimal(inv.json()["on_hand"]) == Decimal("85")
    async with new_session() as db:
        lots = (
            await db.execute(
                select(InventoryLot).where(
                    InventoryLot.product_id == ids["product_id"]
                )
            )
        ).scalars().all()
        assert sum((lot.quantity_remaining for lot in lots), Decimal("0")) == Decimal("85")


async def test_concurrent_same_lot_receive_single_lot(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="CONL-01")

    async def receive() -> int:
        resp = await client.post(
            "/api/v1/inventory/receive",
            headers=org_owner_headers,
            json={
                "product_id": ids["product_id"],
                "warehouse_id": ids["wh1"],
                "quantity": "100",
                "unit_cost": "80.00",
                "lot_code": "LOT-SAME",
            },
        )
        return resp.status_code

    codes = await asyncio.gather(receive(), receive())
    assert codes == [201, 201]
    async with new_session() as db:
        lots = (
            await db.execute(
                select(InventoryLot).where(
                    InventoryLot.product_id == ids["product_id"],
                    InventoryLot.lot_code == "LOT-SAME",
                )
            )
        ).scalars().all()
        assert len(lots) == 1
        assert lots[0].quantity_remaining == Decimal("200")


async def test_ai_inventory_tool_excludes_expired(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="AIEXP-01")
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"], "100",
        lot="LOT-E", expires_at=past,
    )
    await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"], "100",
        lot="LOT-F",
        expires_at=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
    )
    resp = await client.post(
        "/api/v1/ai/employee-assistant",
        headers=org_owner_headers,
        json={"query": "AIEXP-01 还有多少库存？"},
    )
    inventory_tool = resp.json()["tools"].get("库存", {})
    assert Decimal(inventory_tool["available"]) == Decimal("100")
    assert Decimal(inventory_tool["expired_qty"]) == Decimal("100")


async def test_ai_market_tool_includes_basis(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    from app.domains.market.models import MarketQuote

    ids = await _setup(client, org_owner_headers, sku="AIFX-01", wh_prefix="WH5")
    now = datetime.now(UTC)
    async with new_session() as db:
        org_uuid = await _org_id(db)
        db.add(
            MarketQuote(
                organization_id=org_uuid,
                product_id=ids["product_id"],
                external_symbol="USD",
                quote_kind="MARKET_SELL",
                price=Decimal("7.2"),
                currency="CNY",
                source="OpenErApiFxProvider (真实国际汇率参考)",
                region="INTERNATIONAL",
                unit="CNY",
                basis="FX",
                observed_at=now,
                fetched_at=now,
            )
        )
        await db.commit()
    resp = await client.post(
        "/api/v1/ai/employee-assistant",
        headers=org_owner_headers,
        json={"query": "AIFX-01 的市场行情"},
    )
    market_tool = resp.json()["tools"].get("市场", {})
    assert market_tool["quotes"]
    assert market_tool["quotes"][0]["basis"] == "FX"


async def test_dashboard_atp_pool_uses_full_incoming(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="ATPL-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "160")
    due = datetime.now(UTC) + timedelta(days=10)
    await _confirm_order(
        client, org_owner_headers, ids["product_id"], "80",
        required_at=due.isoformat(),
    )
    supplier = await client.post(
        "/api/v1/suppliers",
        headers=org_owner_headers,
        json={"code": "S-ATPL", "name": "长周期供应商"},
    )
    po = await client.post(
        "/api/v1/purchase-orders",
        headers=org_owner_headers,
        json={
            "supplier_id": supplier.json()["id"],
            "lines": [
                {
                    "product_id": ids["product_id"],
                    "ordered_qty": "100",
                    "unit_purchase_price": "80.00",
                    "expected_at": (due - timedelta(days=2)).isoformat(),
                }
            ],
        },
    )
    await client.post(
        f"/api/v1/purchase-orders/{po.json()['id']}/confirm", headers=org_owner_headers
    )
    async with new_session() as db:
        line = (
            await db.execute(
                select(SalesOrderLine).where(
                    SalesOrderLine.sales_order_id
                    == (await _order_id_for_product(db, ids["product_id"]))
                )
            )
        ).scalar_one()
        line.reserved_qty = Decimal("0")
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
        balance = (
            await db.execute(
                select(InventoryBalance).where(
                    InventoryBalance.product_id == ids["product_id"]
                )
            )
        ).scalar_one()
        balance.reserved = Decimal("0")
        await db.commit()
    dashboard = await client.get("/api/v1/dashboard", headers=org_owner_headers)
    assert dashboard.json()["at_risk_orders"] == 0


async def test_dashboard_market_anomaly_respects_fx(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    from app.domains.market.models import MarketQuote

    ids = await _setup(client, org_owner_headers, sku="DMFX-01", wh_prefix="WH6")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "10", cost="1000.00")
    now = datetime.now(UTC)
    async with new_session() as db:
        org_uuid = await _org_id(db)
        db.add(
            MarketQuote(
                organization_id=org_uuid,
                product_id=ids["product_id"],
                external_symbol="USD",
                quote_kind="MARKET_SELL",
                price=Decimal("7.2"),
                currency="CNY",
                source="OpenErApiFxProvider",
                region="INTERNATIONAL",
                unit="CNY",
                basis="FX",
                observed_at=now,
                fetched_at=now,
            )
        )
        await db.commit()
    dashboard = await client.get("/api/v1/dashboard", headers=org_owner_headers)
    assert dashboard.json()["market_anomalies"] == []


async def test_integration_receive_carries_expiry(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="IEXP-01")
    key = await client.post(
        "/api/v1/integrations/api-keys",
        headers=org_owner_headers,
        json={"name": "expiry", "scopes": ["inventory:receive"]},
    )
    resp = await client.post(
        "/api/v1/integrations/events",
        headers={"X-API-Key": key.json()["api_key"]},
        json={
            "schema_version": "1.0",
            "event_id": "exp-001",
            "type": "inventory.received",
            "source": "erp",
            "data": {
                "sku": "IEXP-01",
                "warehouse": "WH01",
                "quantity": "50",
                "unit_price": "80.00",
                "lot_code": "LOT-EXT",
                "expires_at": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
            },
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted"
    lots = await client.get(
        f"/api/v1/inventory/{ids['product_id']}/lots", headers=org_owner_headers
    )
    assert lots.json()[0]["expires_at"] is not None


async def test_image_resolve_size_limit(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/ai/resolve-product",
        headers=org_owner_headers,
        json={"image_data_url": "x" * 8_000_001},
    )
    assert resp.status_code == 422


async def _org_id(db) -> str:
    from app.domains.identity.models import Organization

    org = (await db.execute(select(Organization).limit(1))).scalar_one()
    return str(org.id)


async def _order_id_for_product(db, product_id: str) -> str:
    from app.domains.orders.models import SalesOrder, SalesOrderLine

    line = (
        await db.execute(
            select(SalesOrderLine)
            .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
            .where(SalesOrderLine.product_id == product_id)
            .limit(1)
        )
    ).scalar_one()
    return str(line.sales_order_id)
