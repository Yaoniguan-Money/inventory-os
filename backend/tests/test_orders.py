from __future__ import annotations

import asyncio
from decimal import Decimal

import httpx

from app.core.database import new_session
from app.core.security import create_access_token
from app.domains.identity.models import User


async def _setup_order_env(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    on_hand: str = "1000",
    sku: str = "A001",
) -> dict[str, str]:
    wh = await client.post(
        "/api/v1/warehouses", headers=headers, json={"code": "WH01", "name": "一号仓库"}
    )
    assert wh.status_code == 201
    warehouse_id = wh.json()["id"]
    product = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": sku,
            "name": "测试商品",
            "unit": "pcs",
            "default_warehouse_id": warehouse_id,
            "target_sell_price": "116.00",
        },
    )
    assert product.status_code == 201
    product_id = product.json()["id"]
    receive = await client.post(
        "/api/v1/inventory/receive",
        headers=headers,
        json={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity": on_hand,
            "unit_cost": "80.00",
            "lot_code": f"LOT-{sku}",
        },
    )
    assert receive.status_code == 201, receive.text
    customer = await client.post(
        "/api/v1/customers",
        headers=headers,
        json={"code": "C001", "name": "测试客户", "contact_name": "张三"},
    )
    assert customer.status_code == 201
    return {
        "warehouse_id": warehouse_id,
        "product_id": product_id,
        "customer_id": customer.json()["id"],
    }


async def _create_order(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    ids: dict[str, str],
    qty: str = "300",
    price: str = "116.00",
) -> dict:
    resp = await client.post(
        "/api/v1/orders",
        headers=headers,
        json={
            "customer_id": ids["customer_id"],
            "lines": [
                {
                    "product_id": ids["product_id"],
                    "ordered_qty": qty,
                    "unit_sell_price": price,
                }
            ],
            "required_at": "2026-08-14T00:00:00Z",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_full_order_lifecycle(client: httpx.AsyncClient, org_owner_headers: dict[str, str]) -> None:
    ids = await _setup_order_env(client, org_owner_headers)
    order = await _create_order(client, org_owner_headers, ids)
    assert order["status"] == "DRAFT"
    line_id = order["lines"][0]["id"]

    # Confirm: reserved 300, available 700.
    confirmed = await client.post(
        f"/api/v1/orders/{order['id']}/confirm", headers=org_owner_headers
    )
    assert confirmed.status_code == 200, confirmed.text
    data = confirmed.json()
    assert data["status"] == "CONFIRMED"
    assert Decimal(data["lines"][0]["reserved_qty"]) == Decimal("300")
    assert Decimal(data["lines"][0]["delivered_qty"]) == Decimal("0")

    inv = await client.get(f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers)
    assert Decimal(inv.json()["reserved"]) == Decimal("300")
    assert Decimal(inv.json()["available"]) == Decimal("700")

    # Partial fulfillment: 100 shipped -> on_hand 900, reserved 200, available unchanged.
    partial = await client.post(
        f"/api/v1/orders/{order['id']}/fulfill",
        headers=org_owner_headers,
        json={"lines": [{"sales_order_line_id": line_id, "quantity": "100"}]},
    )
    assert partial.status_code == 200, partial.text
    pdata = partial.json()
    assert pdata["status"] == "PARTIAL"
    assert Decimal(pdata["lines"][0]["delivered_qty"]) == Decimal("100")
    assert Decimal(pdata["lines"][0]["reserved_qty"]) == Decimal("200")

    inv2 = await client.get(f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers)
    assert Decimal(inv2.json()["on_hand"]) == Decimal("900")
    assert Decimal(inv2.json()["reserved"]) == Decimal("200")
    assert Decimal(inv2.json()["available"]) == Decimal("700")  # available not double-counted

    # Complete fulfillment.
    done = await client.post(
        f"/api/v1/orders/{order['id']}/fulfill",
        headers=org_owner_headers,
        json={"lines": [{"sales_order_line_id": line_id, "quantity": "200"}]},
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "FULFILLED"

    inv3 = await client.get(f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers)
    assert Decimal(inv3.json()["on_hand"]) == Decimal("700")
    assert Decimal(inv3.json()["reserved"]) == Decimal("0")
    assert Decimal(inv3.json()["available"]) == Decimal("700")


async def test_cancel_releases_reservation(client: httpx.AsyncClient, org_owner_headers: dict[str, str]) -> None:
    ids = await _setup_order_env(client, org_owner_headers)
    order = await _create_order(client, org_owner_headers, ids, qty="300")
    await client.post(f"/api/v1/orders/{order['id']}/confirm", headers=org_owner_headers)

    cancelled = await client.post(
        f"/api/v1/orders/{order['id']}/cancel", headers=org_owner_headers
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    inv = await client.get(f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers)
    assert Decimal(inv.json()["reserved"]) == Decimal("0")
    assert Decimal(inv.json()["available"]) == Decimal("1000")


async def test_cannot_fulfill_beyond_reservation(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_order_env(client, org_owner_headers)
    order = await _create_order(client, org_owner_headers, ids, qty="300")
    line_id = order["lines"][0]["id"]
    await client.post(f"/api/v1/orders/{order['id']}/confirm", headers=org_owner_headers)
    resp = await client.post(
        f"/api/v1/orders/{order['id']}/fulfill",
        headers=org_owner_headers,
        json={"lines": [{"sales_order_line_id": line_id, "quantity": "301"}]},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "insufficient_stock"


async def test_confirm_rejects_insufficient_stock(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_order_env(client, org_owner_headers, on_hand="100")
    order = await _create_order(client, org_owner_headers, ids, qty="150")
    resp = await client.post(f"/api/v1/orders/{order['id']}/confirm", headers=org_owner_headers)
    assert resp.status_code == 409
    details = resp.json()["error"]["details"]
    assert details["shortages"][0]["sku"] == "A001"
    assert Decimal(details["shortages"][0]["shortage"]) == Decimal("50")


async def test_concurrent_confirm_cannot_oversell(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_order_env(client, org_owner_headers, on_hand="100")
    order1 = await _create_order(client, org_owner_headers, ids, qty="60")
    order2 = await _create_order(client, org_owner_headers, ids, qty="60")

    async def confirm(o: dict) -> int:
        resp = await client.post(f"/api/v1/orders/{o['id']}/confirm", headers=org_owner_headers)
        return resp.status_code

    codes = await asyncio.gather(confirm(order1), confirm(order2))
    assert sorted(codes) == [200, 409]

    inv = await client.get(f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers)
    assert Decimal(inv.json()["reserved"]) == Decimal("60")
    assert Decimal(inv.json()["available"]) == Decimal("40")


async def test_cross_org_order_isolation(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
    second_org_headers: dict[str, str],
) -> None:
    ids = await _setup_order_env(client, org_owner_headers)
    order = await _create_order(client, org_owner_headers, ids)
    resp = await client.get(f"/api/v1/orders/{order['id']}", headers=second_org_headers)
    assert resp.status_code == 404


async def test_viewer_cannot_create_order(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_order_env(client, org_owner_headers)
    created = await client.post(
        "/api/v1/users",
        headers=org_owner_headers,
        json={
            "email": "viewer3@example.com",
            "password": "Viewer@12345",
            "display_name": "只读用户3",
            "role": "VIEWER",
        },
    )
    assert created.status_code == 201
    async with new_session() as db:
        viewer = (
            await db.execute(
                __import__("sqlalchemy").select(User).where(User.email == "viewer3@example.com")
            )
        ).scalar_one()
        token = create_access_token(str(viewer.id))
    resp = await client.post(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "customer_id": ids["customer_id"],
            "lines": [{"product_id": ids["product_id"], "ordered_qty": "1"}],
        },
    )
    assert resp.status_code == 403
