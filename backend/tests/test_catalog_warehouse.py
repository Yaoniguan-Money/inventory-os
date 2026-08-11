from __future__ import annotations

from decimal import Decimal

import httpx
from sqlalchemy import func, select

from app.core.database import new_session
from app.domains.identity.models import User
from app.domains.integrations.models import EventLog
from app.domains.warehouse.models import InventoryBalance, StockMovement


async def _setup_org(client: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    wh_resp = await client.post(
        "/api/v1/warehouses",
        headers=headers,
        json={"code": "WH01", "name": "一号仓库"},
    )
    assert wh_resp.status_code == 201, wh_resp.text
    warehouse_id = wh_resp.json()["id"]

    loc_resp = await client.post(
        f"/api/v1/warehouses/{warehouse_id}/locations",
        headers=headers,
        json={"code": "A-01", "name": "A区01", "zone": "A"},
    )
    assert loc_resp.status_code == 201, loc_resp.text
    location_id = loc_resp.json()["id"]

    product_resp = await client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "sku": "A001",
            "name": "铝合金板材",
            "category": "原材料",
            "unit": "pcs",
            "target_sell_price": "116.00",
            "currency": "CNY",
        },
    )
    assert product_resp.status_code == 201, product_resp.text
    product_id = product_resp.json()["id"]
    return {"warehouse_id": warehouse_id, "location_id": location_id, "product_id": product_id}


async def test_receive_increases_on_hand_and_creates_ledger(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
) -> None:
    ids = await _setup_org(client, org_owner_headers)
    resp = await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["warehouse_id"],
            "location_id": ids["location_id"],
            "quantity": "500",
            "unit_cost": "82.00",
            "lot_code": "LOT-A001-1",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert Decimal(data["balance"]["on_hand"]) == Decimal("500")
    assert Decimal(data["balance"]["available"]) == Decimal("500")
    assert Decimal(data["weighted_avg_cost"]) == Decimal("82")

    inv = await client.get(f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers)
    assert inv.status_code == 200
    assert Decimal(inv.json()["on_hand"]) == Decimal("500")

    lots = await client.get(f"/api/v1/inventory/{ids['product_id']}/lots", headers=org_owner_headers)
    assert len(lots.json()) == 1
    assert lots.json()[0]["lot_code"] == "LOT-A001-1"

    movements = await client.get(
        f"/api/v1/inventory/{ids['product_id']}/movements", headers=org_owner_headers
    )
    assert len(movements.json()) == 1
    assert movements.json()[0]["movement_type"] == "RECEIPT"

    async with new_session() as db:
        balance = (
            await db.execute(
                select(InventoryBalance).where(InventoryBalance.product_id == ids["product_id"])
            )
        ).scalar_one()
        assert balance.on_hand == Decimal("500")
        assert balance.reserved == Decimal("0")
        event_count = (
            await db.execute(
                select(func.count()).select_from(EventLog).where(EventLog.event_type == "inventory.received")
            )
        ).scalar_one()
        assert event_count == 1


async def test_receive_updates_weighted_average_cost(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
) -> None:
    ids = await _setup_org(client, org_owner_headers)
    for qty, price in [("100", "80.00"), ("100", "100.00")]:
        resp = await client.post(
            "/api/v1/inventory/receive",
            headers=org_owner_headers,
            json={
                "product_id": ids["product_id"],
                "warehouse_id": ids["warehouse_id"],
                "quantity": qty,
                "unit_cost": price,
            },
        )
        assert resp.status_code == 201, resp.text
    assert resp.json()["weighted_avg_cost"] == "90.0000"


async def test_adjust_and_negative_inventory_forbidden(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
) -> None:
    ids = await _setup_org(client, org_owner_headers)
    await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["warehouse_id"],
            "quantity": "100",
        },
    )
    ok = await client.post(
        "/api/v1/inventory/adjust",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["warehouse_id"],
            "quantity": "-40",
            "reason": "盘点修正",
        },
    )
    assert ok.status_code == 200
    assert Decimal(ok.json()["balance"]["on_hand"]) == Decimal("60")

    bad = await client.post(
        "/api/v1/inventory/adjust",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["warehouse_id"],
            "quantity": "-100",
            "reason": "超扣",
        },
    )
    assert bad.status_code == 409
    assert bad.json()["error"]["code"] == "insufficient_stock"


async def test_cross_org_cannot_see_inventory(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
    second_org_headers: dict[str, str],
) -> None:
    ids = await _setup_org(client, org_owner_headers)
    await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["warehouse_id"],
            "quantity": "10",
        },
    )
    listing = await client.get("/api/v1/inventory", headers=second_org_headers)
    assert listing.status_code == 200
    assert listing.json() == []
    detail = await client.get(
        f"/api/v1/inventory/{ids['product_id']}", headers=second_org_headers
    )
    assert detail.status_code == 404


async def test_viewer_cannot_receive(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
) -> None:
    ids = await _setup_org(client, org_owner_headers)
    created = await client.post(
        "/api/v1/users",
        headers=org_owner_headers,
        json={
            "email": "viewer2@example.com",
            "password": "Viewer@12345",
            "display_name": "只读用户2",
            "role": "VIEWER",
        },
    )
    assert created.status_code == 201

    from app.core.security import create_access_token

    async with new_session() as db:
        viewer = (
            await db.execute(select(User).where(User.email == "viewer2@example.com"))
        ).scalar_one()
        token = create_access_token(str(viewer.id))

    resp = await client.post(
        "/api/v1/inventory/receive",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["warehouse_id"],
            "quantity": "1",
        },
    )
    assert resp.status_code == 403


async def test_stock_movement_has_no_delete_api(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
) -> None:
    ids = await _setup_org(client, org_owner_headers)
    await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["warehouse_id"],
            "quantity": "5",
        },
    )
    async with new_session() as db:
        movement = (
            await db.execute(select(StockMovement).limit(1))
        ).scalar_one()
    resp = await client.request(
        "DELETE",
        f"/api/v1/inventory/{ids['product_id']}/movements/{movement.id}",
        headers=org_owner_headers,
    )
    assert resp.status_code in (404, 405)
