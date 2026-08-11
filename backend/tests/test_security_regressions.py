from __future__ import annotations

from decimal import Decimal

import httpx
from sqlalchemy import select

from app.core.database import new_session
from app.core.security import create_access_token
from app.domains.catalog.models import Product
from app.domains.identity.models import User
from app.domains.orders.models import DeliveryLine as OrdersDeliveryLine


async def _org1_wh(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/warehouses", headers=headers, json={"code": "WH01", "name": "组织一仓库"}
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_cross_org_default_warehouse_rejected_on_create(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
    second_org_headers: dict[str, str],
) -> None:
    org1_wh = await _org1_wh(client, org_owner_headers)
    resp = await client.post(
        "/api/v1/products",
        headers=second_org_headers,
        json={
            "sku": "ATTACK-01",
            "name": "跨租户脏引用",
            "default_warehouse_id": org1_wh,
        },
    )
    assert resp.status_code == 404
    assert "默认仓库" in resp.json()["error"]["message"]


async def test_cross_org_default_location_rejected_on_create(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
    second_org_headers: dict[str, str],
) -> None:
    org1_wh = await _org1_wh(client, org_owner_headers)
    loc = await client.post(
        f"/api/v1/warehouses/{org1_wh}/locations",
        headers=org_owner_headers,
        json={"code": "A-01", "name": "A区01"},
    )
    assert loc.status_code == 201
    resp = await client.post(
        "/api/v1/products",
        headers=second_org_headers,
        json={
            "sku": "ATTACK-02",
            "name": "跨租户库位",
            "default_location_id": loc.json()["id"],
        },
    )
    assert resp.status_code == 404


async def test_cross_org_default_warehouse_rejected_on_update(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
    second_org_headers: dict[str, str],
) -> None:
    org1_wh = await _org1_wh(client, org_owner_headers)
    product = await client.post(
        "/api/v1/products",
        headers=second_org_headers,
        json={"sku": "ATTACK-03", "name": "先创建再污染"},
    )
    assert product.status_code == 201
    resp = await client.patch(
        f"/api/v1/products/{product.json()['id']}",
        headers=second_org_headers,
        json={"default_warehouse_id": org1_wh},
    )
    assert resp.status_code == 404


async def test_confirm_rejects_dirty_cross_org_default_warehouse(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
    second_org_headers: dict[str, str],
) -> None:
    org1_wh = await _org1_wh(client, org_owner_headers)
    product = await client.post(
        "/api/v1/products",
        headers=second_org_headers,
        json={"sku": "ATTACK-04", "name": "脏数据商品"},
    )
    assert product.status_code == 201
    product_id = product.json()["id"]
    # 模拟历史脏数据：直接把 Org B 商品指向 Org A 仓库。
    async with new_session() as db:
        row = await db.get(Product, product_id)
        row.default_warehouse_id = org1_wh
        await db.commit()

    customer = await client.post(
        "/api/v1/customers",
        headers=second_org_headers,
        json={"code": "C-ATTACK", "name": "脏数据客户"},
    )
    assert customer.status_code == 201
    order = await client.post(
        "/api/v1/orders",
        headers=second_org_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": product_id, "ordered_qty": "1"}],
        },
    )
    assert order.status_code == 201
    resp = await client.post(
        f"/api/v1/orders/{order.json()['id']}/confirm", headers=second_org_headers
    )
    assert resp.status_code == 404
    assert "默认仓库" in resp.json()["error"]["message"]


async def test_diagnose_hides_owner_scoped_knowledge_from_viewer(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    await client.post(
        "/api/v1/warehouses", headers=org_owner_headers, json={"code": "WH01", "name": "一号仓库"}
    )
    equipment = await client.post(
        "/api/v1/equipment",
        headers=org_owner_headers,
        json={"asset_code": "E-99", "name": "保密设备", "status": "OPERATIONAL"},
    )
    assert equipment.status_code == 201
    equipment_id = equipment.json()["id"]
    doc = await client.post(
        "/api/v1/knowledge/documents",
        headers=org_owner_headers,
        json={
            "title": "管理层机密手册 302",
            "document_type": "MANUAL",
            "access_scope": "OWNER",
            "content": "机密内容：错误码 302 必须由管理层授权的工程师处理。",
            "entity_links": [
                {"entity_type": "EQUIPMENT", "entity_id": equipment_id, "relation_type": "MANUAL"}
            ],
        },
    )
    assert doc.status_code == 201

    created = await client.post(
        "/api/v1/users",
        headers=org_owner_headers,
        json={
            "email": "warehouse-viewer@example.com",
            "password": "Warehouse@12345",
            "display_name": "仓库查看员",
            "role": "WAREHOUSE",
        },
    )
    assert created.status_code == 201
    async with new_session() as db:
        viewer = (
            await db.execute(
                select(User).where(User.email == "warehouse-viewer@example.com")
            )
        ).scalar_one()
        token = create_access_token(str(viewer.id))
    viewer_headers = {"Authorization": f"Bearer {token}"}

    result = await client.post(
        f"/api/v1/equipment/{equipment_id}/diagnose",
        headers=viewer_headers,
        json={"fault_code": "302", "symptom": "报错 302"},
    )
    assert result.status_code == 200
    titles = {c["title"] for c in result.json()["citations"]}
    assert "管理层机密手册 302" not in titles


async def test_shipment_consumes_unlocated_balance_after_lots(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    wh = await client.post(
        "/api/v1/warehouses", headers=org_owner_headers, json={"code": "WH01", "name": "一号仓库"}
    )
    warehouse_id = wh.json()["id"]
    product = await client.post(
        "/api/v1/products",
        headers=org_owner_headers,
        json={"sku": "MIX-01", "name": "混合批次商品", "default_warehouse_id": warehouse_id},
    )
    assert product.status_code == 201
    product_id = product.json()["id"]
    # 50 件有批次 + 50 件无批次
    await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity": "50",
            "unit_cost": "80.00",
            "lot_code": "LOT-MIX-1",
        },
    )
    await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={"product_id": product_id, "warehouse_id": warehouse_id, "quantity": "50"},
    )

    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": "C-MIX", "name": "混合客户"},
    )
    order = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": product_id, "ordered_qty": "80"}],
        },
    )
    assert order.status_code == 201
    order_id = order.json()["id"]
    line_id = order.json()["lines"][0]["id"]
    await client.post(f"/api/v1/orders/{order_id}/confirm", headers=org_owner_headers)
    fulfilled = await client.post(
        f"/api/v1/orders/{order_id}/fulfill",
        headers=org_owner_headers,
        json={"lines": [{"sales_order_line_id": line_id, "quantity": "80"}]},
    )
    assert fulfilled.status_code == 200, fulfilled.text
    assert fulfilled.json()["status"] == "FULFILLED"

    inv = await client.get(f"/api/v1/inventory/{product_id}", headers=org_owner_headers)
    assert Decimal(inv.json()["on_hand"]) == Decimal("20")
    movements = await client.get(
        f"/api/v1/inventory/{product_id}/movements", headers=org_owner_headers
    )
    shipments = [m for m in movements.json() if m["movement_type"] == "SHIPMENT"]
    assert len(shipments) == 2
    assert sum(1 for m in shipments if m["lot_id"] is not None) == 1
    assert sum(1 for m in shipments if m["lot_id"] is None) == 1


async def test_multi_lot_shipment_uses_weighted_cost_snapshot(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    wh = await client.post(
        "/api/v1/warehouses", headers=org_owner_headers, json={"code": "WH01", "name": "一号仓库"}
    )
    warehouse_id = wh.json()["id"]
    product = await client.post(
        "/api/v1/products",
        headers=org_owner_headers,
        json={"sku": "COST-01", "name": "多成本批次", "default_warehouse_id": warehouse_id},
    )
    assert product.status_code == 201
    product_id = product.json()["id"]
    for lot, qty, cost in [("LOT-C1", "10", "80.00"), ("LOT-C2", "10", "100.00")]:
        await client.post(
            "/api/v1/inventory/receive",
            headers=org_owner_headers,
            json={
                "product_id": product_id,
                "warehouse_id": warehouse_id,
                "quantity": qty,
                "unit_cost": cost,
                "lot_code": lot,
            },
        )
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": "C-COST", "name": "成本客户"},
    )
    order = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": product_id, "ordered_qty": "20"}],
        },
    )
    order_id = order.json()["id"]
    line_id = order.json()["lines"][0]["id"]
    await client.post(f"/api/v1/orders/{order_id}/confirm", headers=org_owner_headers)
    await client.post(
        f"/api/v1/orders/{order_id}/fulfill",
        headers=org_owner_headers,
        json={"lines": [{"sales_order_line_id": line_id, "quantity": "20"}]},
    )
    async with new_session() as db:
        delivery_line = (
            await db.execute(select(OrdersDeliveryLine).limit(1))
        ).scalar_one()
        assert delivery_line.unit_cost_snapshot == Decimal("90.0000")
