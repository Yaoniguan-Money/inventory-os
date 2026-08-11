from __future__ import annotations

from decimal import Decimal

import httpx
from sqlalchemy import select

from app.core.database import new_session
from app.domains.pricing.models import InternalPriceSnapshot


async def _setup(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    sku: str = "RAW01",
) -> dict[str, str]:
    wh = await client.post(
        "/api/v1/warehouses", headers=headers, json={"code": "WH01", "name": "一号仓库"}
    )
    assert wh.status_code == 201
    warehouse_id = wh.json()["id"]
    product = await client.post(
        "/api/v1/products",
        headers=headers,
        json={"sku": sku, "name": "原材料", "unit": "kg", "default_warehouse_id": warehouse_id},
    )
    assert product.status_code == 201
    product_id = product.json()["id"]
    supplier = await client.post(
        "/api/v1/suppliers",
        headers=headers,
        json={"code": "S001", "name": "供应商甲", "contact": "李四"},
    )
    assert supplier.status_code == 201
    supplier_id = supplier.json()["id"]
    return {"warehouse_id": warehouse_id, "product_id": product_id, "supplier_id": supplier_id}


async def test_purchase_order_incoming_and_receive(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers)
    po_resp = await client.post(
        "/api/v1/purchase-orders",
        headers=org_owner_headers,
        json={
            "supplier_id": ids["supplier_id"],
            "lines": [
                {
                    "product_id": ids["product_id"],
                    "ordered_qty": "500",
                    "unit_purchase_price": "82.00",
                }
            ],
        },
    )
    assert po_resp.status_code == 201, po_resp.text
    po = po_resp.json()
    assert po["status"] == "DRAFT"
    assert Decimal(po["lines"][0]["incoming_qty"]) == Decimal("0")  # draft is not incoming yet

    confirmed = await client.post(
        f"/api/v1/purchase-orders/{po['id']}/confirm", headers=org_owner_headers
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "CONFIRMED"
    assert Decimal(confirmed.json()["lines"][0]["incoming_qty"]) == Decimal("500")

    # Workbench shows incoming without on-hand.
    wb = await client.get("/api/v1/purchase-workbench", headers=org_owner_headers)
    item = wb.json()[0]
    assert Decimal(item["incoming"]) == Decimal("500")
    assert Decimal(item["on_hand"]) == Decimal("0")

    received = await client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        headers=org_owner_headers,
        json={
            "lines": [
                {
                    "purchase_order_line_id": confirmed.json()["lines"][0]["id"],
                    "quantity": "500",
                    "lot_code": "RAW-LOT-1",
                }
            ]
        },
    )
    assert received.status_code == 200, received.text
    assert received.json()["status"] == "RECEIVED"
    assert Decimal(received.json()["lines"][0]["received_qty"]) == Decimal("500")
    assert Decimal(received.json()["lines"][0]["incoming_qty"]) == Decimal("0")

    inv = await client.get(f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers)
    assert Decimal(inv.json()["on_hand"]) == Decimal("500")

    prices = await client.get(
        f"/api/v1/products/{ids['product_id']}/prices", headers=org_owner_headers
    )
    assert prices.status_code == 200
    assert Decimal(prices.json()["last_purchase_price"]["price"]) == Decimal("82")
    assert Decimal(prices.json()["weighted_avg_cost"]["price"]) == Decimal("82")


async def test_partial_purchase_receive(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="RAW02")
    po = (
        await client.post(
            "/api/v1/purchase-orders",
            headers=org_owner_headers,
            json={
                "supplier_id": ids["supplier_id"],
                "lines": [
                    {
                        "product_id": ids["product_id"],
                        "ordered_qty": "100",
                        "unit_purchase_price": "10.00",
                    }
                ],
            },
        )
    ).json()
    confirmed = (
        await client.post(
            f"/api/v1/purchase-orders/{po['id']}/confirm", headers=org_owner_headers
        )
    ).json()
    line_id = confirmed["lines"][0]["id"]
    resp = await client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        headers=org_owner_headers,
        json={"lines": [{"purchase_order_line_id": line_id, "quantity": "40"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "PARTIAL"
    assert Decimal(resp.json()["lines"][0]["incoming_qty"]) == Decimal("60")

    too_much = await client.post(
        f"/api/v1/purchase-orders/{po['id']}/receive",
        headers=org_owner_headers,
        json={"lines": [{"purchase_order_line_id": line_id, "quantity": "61"}]},
    )
    assert too_much.status_code == 422


async def test_weighted_average_cost_over_receipts(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="RAW03")
    po1 = (
        await client.post(
            "/api/v1/purchase-orders",
            headers=org_owner_headers,
            json={
                "supplier_id": ids["supplier_id"],
                "lines": [
                    {
                        "product_id": ids["product_id"],
                        "ordered_qty": "100",
                        "unit_purchase_price": "80.00",
                    }
                ],
            },
        )
    ).json()
    po2 = (
        await client.post(
            "/api/v1/purchase-orders",
            headers=org_owner_headers,
            json={
                "supplier_id": ids["supplier_id"],
                "lines": [
                    {
                        "product_id": ids["product_id"],
                        "ordered_qty": "100",
                        "unit_purchase_price": "100.00",
                    }
                ],
            },
        )
    ).json()
    for po in (po1, po2):
        await client.post(f"/api/v1/purchase-orders/{po['id']}/confirm", headers=org_owner_headers)
        line_id = (
            await client.get(f"/api/v1/purchase-orders/{po['id']}", headers=org_owner_headers)
        ).json()["lines"][0]["id"]
        await client.post(
            f"/api/v1/purchase-orders/{po['id']}/receive",
            headers=org_owner_headers,
            json={"lines": [{"purchase_order_line_id": line_id, "quantity": "100"}]},
        )
    prices = await client.get(
        f"/api/v1/products/{ids['product_id']}/prices", headers=org_owner_headers
    )
    assert Decimal(prices.json()["weighted_avg_cost"]["price"]) == Decimal("90")


async def test_target_price_and_actual_sell_price(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="RAW04")
    target = await client.post(
        f"/api/v1/products/{ids['product_id']}/target-price",
        headers=org_owner_headers,
        json={"price": "120.00", "currency": "CNY"},
    )
    assert target.status_code == 200
    assert Decimal(target.json()["target_sell_price"]["price"]) == Decimal("120")

    # Create + confirm a sales order to capture ACTUAL_SELL_PRICE.
    await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["warehouse_id"],
            "quantity": "10",
            "unit_cost": "80.00",
        },
    )
    customer = (
        await client.post(
            "/api/v1/customers",
            headers=org_owner_headers,
            json={"code": "C002", "name": "客户乙"},
        )
    ).json()
    order = (
        await client.post(
            "/api/v1/orders",
            headers=org_owner_headers,
            json={
                "customer_id": customer["id"],
                "lines": [
                    {
                        "product_id": ids["product_id"],
                        "ordered_qty": "5",
                        "unit_sell_price": "116.00",
                    }
                ],
            },
        )
    ).json()
    await client.post(f"/api/v1/orders/{order['id']}/confirm", headers=org_owner_headers)
    prices = await client.get(
        f"/api/v1/products/{ids['product_id']}/prices", headers=org_owner_headers
    )
    assert Decimal(prices.json()["actual_sell_price"]["price"]) == Decimal("116")
    assert prices.json()["actual_sell_price"]["source_reference_type"] == "SALES_ORDER_LINE"


async def test_cross_org_purchase_isolation(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
    second_org_headers: dict[str, str],
) -> None:
    ids = await _setup(client, org_owner_headers)
    po = (
        await client.post(
            "/api/v1/purchase-orders",
            headers=org_owner_headers,
            json={
                "supplier_id": ids["supplier_id"],
                "lines": [{"product_id": ids["product_id"], "ordered_qty": "10"}],
            },
        )
    ).json()
    resp = await client.get(f"/api/v1/purchase-orders/{po['id']}", headers=second_org_headers)
    assert resp.status_code == 404
    wb = await client.get("/api/v1/purchase-workbench", headers=second_org_headers)
    assert wb.json() == []


async def test_snapshots_recorded_in_db(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="RAW05")
    await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["warehouse_id"],
            "quantity": "20",
            "unit_cost": "50.00",
        },
    )
    async with new_session() as db:
        types = set(
            (
                await db.execute(
                    select(InternalPriceSnapshot.price_type).where(
                        InternalPriceSnapshot.product_id == ids["product_id"]
                    )
                )
            ).scalars()
        )
        assert types == {"LAST_PURCHASE_PRICE", "WEIGHTED_AVG_COST"}
