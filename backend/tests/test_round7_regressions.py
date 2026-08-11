from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.core.database import new_session
from app.domains.orders.models import InventoryReservation, SalesOrderLine
from app.domains.purchasing.models import PurchaseOrder, PurchaseOrderLine
from app.domains.warehouse.models import InventoryBalance


async def _setup(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    sku: str = "R7-01",
) -> dict[str, str]:
    wh1 = await client.post(
        "/api/v1/warehouses", headers=headers, json={"code": "WH01", "name": "一号仓"}
    )
    product = await client.post(
        "/api/v1/products",
        headers=headers,
        json={"sku": sku, "name": "第七轮商品", "unit": "件", "default_warehouse_id": wh1.json()["id"]},
    )
    return {"product_id": product.json()["id"], "wh1": wh1.json()["id"]}


async def _po(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    product_id: str,
    qty: str,
    *,
    expected_at: str | None = None,
) -> dict:
    supplier = await client.post(
        "/api/v1/suppliers",
        headers=headers,
        json={"code": f"S-{uuid.uuid4().hex[:8]}", "name": "第七轮供应商"},
    )
    line = {"product_id": product_id, "ordered_qty": qty, "unit_purchase_price": "80.00"}
    if expected_at:
        line["expected_at"] = expected_at
    po = await client.post(
        "/api/v1/purchase-orders",
        headers=headers,
        json={"supplier_id": supplier.json()["id"], "lines": [line]},
    )
    await client.post(f"/api/v1/purchase-orders/{po.json()['id']}/confirm", headers=headers)
    return po.json()


async def _receive(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    product_id: str,
    warehouse_id: str,
    qty: str,
    *,
    purchase_order_line_id: str | None = None,
    lot: str | None = None,
) -> int:
    payload = {
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "quantity": qty,
        "unit_cost": "80.00",
    }
    if lot:
        payload["lot_code"] = lot
    if purchase_order_line_id:
        payload["purchase_order_line_id"] = purchase_order_line_id
    resp = await client.post("/api/v1/inventory/receive", headers=headers, json=payload)
    return resp.status_code


async def test_po_linked_receive_validation_and_sync(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
    second_org_headers: dict[str, str],
) -> None:
    ids = await _setup(client, org_owner_headers, sku="POL-01")
    po = await _po(client, org_owner_headers, ids["product_id"], "100")
    line_id = po["lines"][0]["id"]

    # 跨组织：Org B 用 Org A 的 PO 行 → 404。
    other = await client.post(
        "/api/v1/products",
        headers=second_org_headers,
        json={"sku": "POL-OTHER", "name": "另一组织商品"},
    )
    status = await _receive(
        client, second_org_headers, other.json()["id"], (await _org_wh(client, second_org_headers)),
        "10", purchase_order_line_id=line_id,
    )
    assert status == 404

    # 跨 SKU：同组织但商品不匹配 → 404。
    other_own = await client.post(
        "/api/v1/products",
        headers=org_owner_headers,
        json={"sku": "POL-SKU", "name": "另一商品", "default_warehouse_id": ids["wh1"]},
    )
    status = await _receive(
        client, org_owner_headers, other_own.json()["id"], ids["wh1"],
        "10", purchase_order_line_id=line_id,
    )
    assert status == 404

    # 超过剩余数量 → 409。
    status = await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"],
        "101", purchase_order_line_id=line_id,
    )
    assert status == 409

    # 正常关联入库：received_qty / PO status / Incoming 同步。
    assert await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"],
        "40", purchase_order_line_id=line_id, lot="LOT-POL",
    ) == 201
    async with new_session() as db:
        line = (await db.execute(select(PurchaseOrderLine).limit(1))).scalar_one()
        assert line.received_qty == Decimal("40")
        po_row = (await db.execute(select(PurchaseOrder).limit(1))).scalar_one()
        assert po_row.status == "PARTIAL"
    wb = await client.get("/api/v1/purchase-workbench", headers=org_owner_headers)
    item = next(i for i in wb.json() if i["product_id"] == ids["product_id"])
    assert Decimal(item["incoming"]) == Decimal("60")

    assert await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"],
        "60", purchase_order_line_id=line_id,
    ) == 201
    async with new_session() as db:
        po_row = (await db.execute(select(PurchaseOrder).limit(1))).scalar_one()
        assert po_row.status == "RECEIVED"
    wb2 = await client.get("/api/v1/purchase-workbench", headers=org_owner_headers)
    item2 = next(i for i in wb2.json() if i["product_id"] == ids["product_id"])
    assert Decimal(item2["incoming"]) == Decimal("0")


async def test_atp_unknown_eta_excluded_for_dated_orders(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="ETA-01")
    await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["wh1"],
            "quantity": "160",
            "unit_cost": "80.00",
        },
    )
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": f"C-{uuid.uuid4().hex[:8]}", "name": "ETA 客户"},
    )
    order = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": ids["product_id"], "ordered_qty": "80"}],
            "required_at": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
        },
    )
    await client.post(f"/api/v1/orders/{order.json()['id']}/confirm", headers=org_owner_headers)
    # 未知 ETA 的在途。
    await _po(client, org_owner_headers, ids["product_id"], "100")
    # 释放预留，制造未覆盖需求。
    async with new_session() as db:
        line = (
            await db.execute(
                select(SalesOrderLine).where(
                    SalesOrderLine.sales_order_id == order.json()["id"]
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
        await db.commit()

    dashboard = await client.get("/api/v1/dashboard", headers=org_owner_headers)
    assert dashboard.json()["at_risk_orders"] >= 1
    health = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    assert any(
        a["alert_type"] == "ORDER_FULFILLMENT_RISK" for a in health.json()["alerts"]
    )
    wb = await client.get("/api/v1/purchase-workbench", headers=org_owner_headers)
    item = next(i for i in wb.json() if i["product_id"] == ids["product_id"])
    assert Decimal(item["incoming"]) == Decimal("100")
    assert Decimal(item["incoming_before_7d"]) == Decimal("0")


async def test_order_detail_uses_allocated_incoming_share(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="SHARE-01")
    await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["wh1"],
            "quantity": "160",
            "unit_cost": "80.00",
        },
    )
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": f"C-{uuid.uuid4().hex[:8]}", "name": "共享客户"},
    )
    orders = []
    for _ in range(2):
        order = await client.post(
            "/api/v1/orders",
            headers=org_owner_headers,
            json={
                "customer_id": customer.json()["id"],
                "lines": [{"product_id": ids["product_id"], "ordered_qty": "50"}],
                "required_at": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
            },
        )
        await client.post(f"/api/v1/orders/{order.json()['id']}/confirm", headers=org_owner_headers)
        orders.append(order.json())
    await _po(
        client, org_owner_headers, ids["product_id"], "100",
        expected_at=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
    )
    async with new_session() as db:
        for order in orders:
            line = (
                await db.execute(
                    select(SalesOrderLine).where(
                        SalesOrderLine.sales_order_id == order["id"]
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
        await db.commit()
    for order in orders:
        detail = await client.get(f"/api/v1/orders/{order['id']}", headers=org_owner_headers)
        line = detail.json()["lines"][0]
        # 每单只认领自己的缺口份额（50），而不是把 100 全部算给自己的在途。
        assert Decimal(line["incoming"]) == Decimal("50")


async def _org_wh(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/warehouses", headers=headers, json={"code": "WH-OTHER", "name": "另一仓库"}
    )
    assert resp.status_code == 201
    return resp.json()["id"]
