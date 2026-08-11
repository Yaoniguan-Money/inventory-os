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
    sku: str = "R6-01",
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
        json={"sku": sku, "name": "第六轮商品", "unit": "件", "default_warehouse_id": wh1.json()["id"]},
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


async def _order(
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
        json={"code": f"C-{uuid.uuid4().hex[:8]}", "name": "第六轮客户"},
    )
    payload = {
        "customer_id": customer.json()["id"],
        "lines": [{"product_id": product_id, "ordered_qty": qty}],
    }
    if required_at:
        payload["required_at"] = required_at
    order = await client.post("/api/v1/orders", headers=headers, json=payload)
    assert order.status_code == 201, order.text
    confirmed = await client.post(
        f"/api/v1/orders/{order.json()['id']}/confirm", headers=headers
    )
    assert confirmed.status_code == 200, confirmed.text
    return order.json()


async def _po(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    product_id: str,
    qty: str,
    *,
    expected_at: str,
) -> None:
    supplier = await client.post(
        "/api/v1/suppliers",
        headers=headers,
        json={"code": f"S-{uuid.uuid4().hex[:8]}", "name": "第六轮供应商"},
    )
    po = await client.post(
        "/api/v1/purchase-orders",
        headers=headers,
        json={
            "supplier_id": supplier.json()["id"],
            "lines": [
                {
                    "product_id": product_id,
                    "ordered_qty": qty,
                    "unit_purchase_price": "80.00",
                    "expected_at": expected_at,
                }
            ],
        },
    )
    await client.post(f"/api/v1/purchase-orders/{po.json()['id']}/confirm", headers=headers)


async def _release_reservation(
    client: httpx.AsyncClient, headers: dict[str, str], order_id: str
) -> None:
    async with new_session() as db:
        line = (
            await db.execute(
                select(SalesOrderLine).where(SalesOrderLine.sales_order_id == order_id)
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
            balance = (
                await db.execute(
                    select(InventoryBalance).where(
                        InventoryBalance.warehouse_id == reservation.warehouse_id,
                        InventoryBalance.product_id == line.product_id,
                    )
                )
            ).scalar_one()
            balance.reserved -= reservation.quantity
            reservation.status = "RELEASED"
            reservation.quantity = Decimal("0")
            await db.flush()
        await db.commit()


async def test_workbench_shortage_uses_7d_incoming_only(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="WB7-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100")
    order = await _order(
        client, org_owner_headers, ids["product_id"], "80",
        required_at=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
    )
    await _release_reservation(client, org_owner_headers, order["id"])
    async with new_session() as db:
        balance = (
            await db.execute(
                select(InventoryBalance).where(
                    InventoryBalance.product_id == ids["product_id"]
                )
            )
        ).scalar_one()
        balance.on_hand = Decimal("20")
        await db.commit()
    # 30 天后才到的在途不能用于 7 日缺口。
    await _po(
        client, org_owner_headers, ids["product_id"], "100",
        expected_at=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
    )
    wb = await client.get("/api/v1/purchase-workbench", headers=org_owner_headers)
    item = next(i for i in wb.json() if i["product_id"] == ids["product_id"])
    assert Decimal(item["incoming"]) == Decimal("100")
    assert Decimal(item["incoming_before_7d"]) == Decimal("0")
    assert Decimal(item["shortage_7d"]) == Decimal("60")


async def test_workbench_shortage_uses_7d_incoming_when_in_time(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="WB7B-01", wh_prefix="WH1")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100")
    order = await _order(
        client, org_owner_headers, ids["product_id"], "80",
        required_at=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
    )
    await _release_reservation(client, org_owner_headers, order["id"])
    await _po(
        client, org_owner_headers, ids["product_id"], "100",
        expected_at=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
    )
    wb = await client.get("/api/v1/purchase-workbench", headers=org_owner_headers)
    item = next(i for i in wb.json() if i["product_id"] == ids["product_id"])
    assert Decimal(item["incoming_before_7d"]) == Decimal("100")
    assert Decimal(item["shortage_7d"]) == Decimal("0")


async def test_atp_time_bucket_allocation(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="ATP7-01", wh_prefix="WH2")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "160")
    now = datetime.now(UTC)
    order1 = await _order(
        client, org_owner_headers, ids["product_id"], "80",
        required_at=(now + timedelta(days=3)).isoformat(),
    )
    order2 = await _order(
        client, org_owner_headers, ids["product_id"], "80",
        required_at=(now + timedelta(days=4)).isoformat(),
    )
    await _release_reservation(client, org_owner_headers, order1["id"])
    await _release_reservation(client, org_owner_headers, order2["id"])
    # 时间桶：80 件 2 天后到、20 件 5 天后到。
    await _po(
        client, org_owner_headers, ids["product_id"], "80",
        expected_at=(now + timedelta(days=2)).isoformat(),
    )
    await _po(
        client, org_owner_headers, ids["product_id"], "20",
        expected_at=(now + timedelta(days=5)).isoformat(),
    )
    dashboard = await client.get("/api/v1/dashboard", headers=org_owner_headers)
    # 订单1（+3d）用掉 2 天后到的 80；订单2（+4d）只剩 5 天后的 20（不可用）→ 1 单风险。
    assert dashboard.json()["at_risk_orders"] == 1
    health = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    fulfillment = next(
        a for a in health.json()["alerts"] if a["alert_type"] == "ORDER_FULFILLMENT_RISK"
    )
    assert len(fulfillment["evidence_json"]["orders"]) == 1


async def test_order_detail_stock_semantics_after_expiry(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="ODET-01")
    await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"], "100",
        lot="LOT-OD",
        expires_at=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
    )
    order = await _order(client, org_owner_headers, ids["product_id"], "80")
    async with new_session() as db:
        lot = (
            await db.execute(
                select(InventoryLot).where(InventoryLot.product_id == ids["product_id"])
            )
        ).scalar_one()
        lot.expires_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()
    detail = await client.get(f"/api/v1/orders/{order['id']}", headers=org_owner_headers)
    line = detail.json()["lines"][0]
    assert Decimal(line["available"]) == Decimal("0")
    assert Decimal(line["expired_qty"]) == Decimal("100")
    assert line["fulfillment_risk"] is True


async def test_concurrent_cross_warehouse_receive_cost(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="CCST-01", wh_prefix="WH3")

    async def receive(wh: str, qty: str, cost: str) -> int:
        resp = await client.post(
            "/api/v1/inventory/receive",
            headers=org_owner_headers,
            json={
                "product_id": ids["product_id"],
                "warehouse_id": wh,
                "quantity": qty,
                "unit_cost": cost,
                "lot_code": f"LOT-{wh[-4:]}-{cost}",
            },
        )
        return resp.status_code

    codes = await asyncio.gather(
        receive(ids["wh1"], "100", "80.00"),
        receive(ids["wh2"], "100", "100.00"),
    )
    assert codes == [201, 201]
    prices = await client.get(
        f"/api/v1/products/{ids['product_id']}/prices", headers=org_owner_headers
    )
    assert Decimal(prices.json()["weighted_avg_cost"]["price"]) == Decimal("90")


async def test_price_pressure_requires_same_currency(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    from app.domains.market.models import MarketQuote

    ids_usd = await _setup(client, org_owner_headers, sku="CUR-USD", wh_prefix="WH4")
    ids_cny = await _setup(client, org_owner_headers, sku="CUR-CNY", wh_prefix="WH5")
    await _receive(client, org_owner_headers, ids_usd["product_id"], ids_usd["wh1"], "10", cost="1000.00")
    await _receive(client, org_owner_headers, ids_cny["product_id"], ids_cny["wh1"], "10", cost="1000.00")
    now = datetime.now(UTC)
    async with new_session() as db:
        org_uuid = await _org_id(db)
        db.add(
            MarketQuote(
                organization_id=org_uuid,
                product_id=ids_usd["product_id"],
                external_symbol="AL-USD",
                quote_kind="MARKET_BUY",
                price=Decimal("50"),
                currency="USD",
                source="GenericHttpJsonProvider",
                region="INTERNATIONAL",
                observed_at=now,
                fetched_at=now,
            )
        )
        db.add(
            MarketQuote(
                organization_id=org_uuid,
                product_id=ids_cny["product_id"],
                external_symbol="AL-CNY",
                quote_kind="MARKET_BUY",
                price=Decimal("50"),
                currency="CNY",
                source="MockMarketProvider (Demo)",
                region="DOMESTIC",
                observed_at=now,
                fetched_at=now,
            )
        )
        await db.commit()
    usd_health = await client.get(
        f"/api/v1/products/{ids_usd['product_id']}/health", headers=org_owner_headers
    )
    assert not any(a["alert_type"] == "PRICE_PRESSURE" for a in usd_health.json()["alerts"])
    cny_health = await client.get(
        f"/api/v1/products/{ids_cny['product_id']}/health", headers=org_owner_headers
    )
    assert any(a["alert_type"] == "PRICE_PRESSURE" for a in cny_health.json()["alerts"])


async def test_negative_adjust_respects_sellable_coverage(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="ADJS-01")
    now = datetime.now(UTC)
    await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"], "60",
        lot="LOT-F",
        expires_at=(now + timedelta(days=30)).isoformat(),
    )
    await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"], "40",
        lot="LOT-E",
        expires_at=(now - timedelta(days=1)).isoformat(),
    )
    await _order(client, org_owner_headers, ids["product_id"], "50")
    ok = await client.post(
        "/api/v1/inventory/adjust",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["wh1"],
            "quantity": "-10",
            "reason": "盘点",
        },
    )
    assert ok.status_code == 200, ok.text
    denied = await client.post(
        "/api/v1/inventory/adjust",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["wh1"],
            "quantity": "-1",
            "reason": "盘点",
        },
    )
    assert denied.status_code == 409
    assert "未过期可售" in denied.json()["error"]["message"]


async def test_integration_unknown_schema_version_rejected(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="VER-01")
    key = await client.post(
        "/api/v1/integrations/api-keys",
        headers=org_owner_headers,
        json={"name": "version", "scopes": ["inventory:receive"]},
    )
    resp = await client.post(
        "/api/v1/integrations/events",
        headers={"X-API-Key": key.json()["api_key"]},
        json={
            "schema_version": "2.0",
            "event_id": "v2-001",
            "type": "inventory.received",
            "source": "erp",
            "data": {"sku": "VER-01", "warehouse": "WH01", "quantity": "10"},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert "schema_version" in resp.json()["message"]
    inv = await client.get(f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers)
    assert inv.status_code == 404


async def _org_id(db) -> str:
    from app.domains.identity.models import Organization

    org = (await db.execute(select(Organization).limit(1))).scalar_one()
    return str(org.id)
