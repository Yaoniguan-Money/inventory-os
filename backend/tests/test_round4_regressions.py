from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.core.database import new_session
from app.domains.orders.models import InventoryReservation, SalesOrderLine
from app.domains.warehouse.models import InventoryBalance, StockMovement


async def _setup(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    sku: str = "R4-01",
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
        json={"sku": sku, "name": "第四轮商品", "unit": "件", "default_warehouse_id": wh1.json()["id"]},
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


async def test_expired_lots_not_available_or_shippable(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="EXP-01")
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"], "100",
        lot="LOT-EXPIRED", expires_at=past,
    )
    await _receive(
        client, org_owner_headers, ids["product_id"], ids["wh1"], "100",
        lot="LOT-FRESH", expires_at=future,
    )

    single = await client.get(
        f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers
    )
    assert Decimal(single.json()["expired_qty"]) == Decimal("100")
    assert Decimal(single.json()["available"]) == Decimal("100")  # 150 - 0 - 100? 200-100=100

    health = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    expiry = next(a for a in health.json()["alerts"] if a["alert_type"] == "EXPIRY_RISK")
    assert expiry["severity"] == "CRITICAL"
    assert any(lot["expired"] for lot in expiry["evidence_json"]["lots"])

    # 出库 60（> 可售 100）会失败；订单 80 只能使用新鲜批次。
    equipment = await client.post(
        "/api/v1/equipment",
        headers=org_owner_headers,
        json={"asset_code": "E-EXP", "name": "过期测试设备"},
    )
    denied = await client.post(
        f"/api/v1/equipment/{equipment.json()['id']}/maintenance",
        headers=org_owner_headers,
        json={
            "maintenance_type": "REPLACE_PART",
            "parts": [{"product_id": ids["product_id"], "quantity": "160"}],
        },
    )
    assert denied.status_code == 409
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": "C-EXP", "name": "过期客户"},
    )
    order = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": ids["product_id"], "ordered_qty": "80"}],
        },
    )
    await client.post(f"/api/v1/orders/{order.json()['id']}/confirm", headers=org_owner_headers)
    fulfilled = await client.post(
        f"/api/v1/orders/{order.json()['id']}/fulfill",
        headers=org_owner_headers,
        json={"lines": [{"sales_order_line_id": order.json()["lines"][0]["id"], "quantity": "80"}]},
    )
    assert fulfilled.status_code == 200, fulfilled.text
    lots = await client.get(
        f"/api/v1/inventory/{ids['product_id']}/lots", headers=org_owner_headers
    )
    by_code = {lot["lot_code"]: lot for lot in lots.json()}
    assert Decimal(by_code["LOT-EXPIRED"]["quantity_remaining"]) == Decimal("100")
    assert Decimal(by_code["LOT-FRESH"]["quantity_remaining"]) == Decimal("20")


async def test_dormant_threshold_uses_config(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="DORM-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100")
    async with new_session() as db:
        db.add(
            StockMovement(
                organization_id=(await _org_id(db)),
                product_id=ids["product_id"],
                warehouse_id=ids["wh1"],
                movement_type="SHIPMENT",
                quantity=Decimal("-10"),
                occurred_at=datetime.now(UTC) - timedelta(days=60),
            )
        )
        await db.commit()
    health = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    dormant = next(a for a in health.json()["alerts"] if a["alert_type"] == "DORMANT_STOCK")
    assert dormant["status"] == "OPEN"
    assert dormant["evidence_json"]["dormant_days"] == 30


async def test_target_price_snapshot_on_create_and_update(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    product = await client.post(
        "/api/v1/products",
        headers=org_owner_headers,
        json={"sku": "PRICE-01", "name": "目标价商品", "target_sell_price": "118.00"},
    )
    assert product.status_code == 201
    product_id = product.json()["id"]
    prices = await client.get(f"/api/v1/products/{product_id}/prices", headers=org_owner_headers)
    assert Decimal(prices.json()["target_sell_price"]["price"]) == Decimal("118")

    await client.patch(
        f"/api/v1/products/{product_id}",
        headers=org_owner_headers,
        json={"target_sell_price": "99.00"},
    )
    prices2 = await client.get(f"/api/v1/products/{product_id}/prices", headers=org_owner_headers)
    assert Decimal(prices2.json()["target_sell_price"]["price"]) == Decimal("99")
    target_history = [
        p for p in prices2.json()["history"] if p["price_type"] == "TARGET_SELL_PRICE"
    ]
    assert len(target_history) == 2


async def test_fx_quote_never_triggers_price_pressure(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    from app.domains.market.models import MarketQuote

    ids_fx = await _setup(client, org_owner_headers, sku="FX-01", wh_prefix="WH2")
    await _receive(client, org_owner_headers, ids_fx["product_id"], ids_fx["wh1"], "10", cost="1000.00")
    ids_real = await _setup(client, org_owner_headers, sku="UOM-01", wh_prefix="WH3")
    await _receive(client, org_owner_headers, ids_real["product_id"], ids_real["wh1"], "10", cost="1000.00")
    now = datetime.now(UTC)
    async with new_session() as db:
        org_uuid = await _org_id(db)
        db.add(
            MarketQuote(
                organization_id=org_uuid,
                product_id=ids_fx["product_id"],
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
        db.add(
            MarketQuote(
                organization_id=org_uuid,
                product_id=ids_real["product_id"],
                external_symbol="AL-1",
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
    fx_health = await client.get(
        f"/api/v1/products/{ids_fx['product_id']}/health", headers=org_owner_headers
    )
    assert not any(a["alert_type"] == "PRICE_PRESSURE" for a in fx_health.json()["alerts"])
    real_health = await client.get(
        f"/api/v1/products/{ids_real['product_id']}/health", headers=org_owner_headers
    )
    assert any(a["alert_type"] == "PRICE_PRESSURE" for a in real_health.json()["alerts"])


async def test_maintenance_uses_cross_warehouse_allocation(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="ALLO-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh2"], "10")
    equipment = await client.post(
        "/api/v1/equipment",
        headers=org_owner_headers,
        json={"asset_code": "E-ALLO", "name": "跨仓领料设备"},
    )
    equipment_id = equipment.json()["id"]
    ok = await client.post(
        f"/api/v1/equipment/{equipment_id}/maintenance",
        headers=org_owner_headers,
        json={
            "maintenance_type": "REPLACE_PART",
            "parts": [{"product_id": ids["product_id"], "quantity": "6"}],
        },
    )
    assert ok.status_code == 201, ok.text
    listing = await client.get("/api/v1/inventory", headers=org_owner_headers)
    rows = {r["warehouse_code"]: r for r in listing.json() if r["product_id"] == ids["product_id"]}
    assert Decimal(rows["WH02"]["on_hand"]) == Decimal("4")
    denied = await client.post(
        f"/api/v1/equipment/{equipment_id}/maintenance",
        headers=org_owner_headers,
        json={
            "maintenance_type": "REPLACE_PART",
            "parts": [{"product_id": ids["product_id"], "quantity": "5"}],
        },
    )
    assert denied.status_code == 409


async def test_diagnose_uses_latest_document_version(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    equipment = await client.post(
        "/api/v1/equipment",
        headers=org_owner_headers,
        json={"asset_code": "E-VER", "name": "版本设备"},
    )
    equipment_id = equipment.json()["id"]
    doc = await client.post(
        "/api/v1/knowledge/documents",
        headers=org_owner_headers,
        json={
            "title": "E-VER 手册",
            "document_type": "MANUAL",
            "access_scope": "ORG",
            "content": "旧版本：错误码 302 检查皮带张紧度。",
            "entity_links": [
                {"entity_type": "EQUIPMENT", "entity_id": equipment_id, "relation_type": "MANUAL"}
            ],
        },
    )
    assert doc.status_code == 201
    from app.domains.knowledge.models import KnowledgeChunk, KnowledgeDocumentVersion

    async with new_session() as db:
        version = (
            await db.execute(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.document_id == doc.json()["id"]
                )
            )
        ).scalar_one()
        v2 = KnowledgeDocumentVersion(
            document_id=version.document_id,
            version=2,
            content_hash="new-hash",
        )
        db.add(v2)
        await db.flush()
        db.add(
            KnowledgeChunk(
                document_version_id=v2.id,
                chunk_index=0,
                content="新版本：错误码 302 检查主轴轴承润滑。",
                metadata_json={},
            )
        )
        await db.commit()
    result = await client.post(
        f"/api/v1/equipment/{equipment_id}/diagnose",
        headers=org_owner_headers,
        json={"fault_code": "302", "symptom": "报错 302"},
    )
    excerpts = [c["excerpt"] for c in result.json()["citations"]]
    assert any("主轴轴承润滑" in e for e in excerpts)
    assert not any("皮带张紧度" in e for e in excerpts)


async def test_access_scope_literal_and_entity_ownership(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
    second_org_headers: dict[str, str],
) -> None:
    bad_scope = await client.post(
        "/api/v1/knowledge/documents",
        headers=org_owner_headers,
        json={
            "title": "拼错权限",
            "access_scope": "OWNR",
            "content": "测试",
        },
    )
    assert bad_scope.status_code == 422

    product = await client.post(
        "/api/v1/products",
        headers=org_owner_headers,
        json={"sku": "ORG-A-P", "name": "组织一商品"},
    )
    dirty = await client.post(
        "/api/v1/knowledge/documents",
        headers=second_org_headers,
        json={
            "title": "脏关联文档",
            "access_scope": "ORG",
            "content": "测试",
            "entity_links": [
                {"entity_type": "PRODUCT", "entity_id": product.json()["id"]}
            ],
        },
    )
    assert dirty.status_code == 404


async def test_order_list_uses_line_date_precedence(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="ODATE-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "200")
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": "C-ODATE", "name": "订单日期客户"},
    )
    # 订单头已逾期，但行级 10 天后 → 不算逾期。
    late = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [
                {
                    "product_id": ids["product_id"],
                    "ordered_qty": "50",
                    "required_at": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
                }
            ],
            "required_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        },
    )
    await client.post(f"/api/v1/orders/{late.json()['id']}/confirm", headers=org_owner_headers)
    # 订单头 10 天后，但行级 1 天前 → 算逾期。
    early = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [
                {
                    "product_id": ids["product_id"],
                    "ordered_qty": "50",
                    "required_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
                }
            ],
            "required_at": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
        },
    )
    await client.post(f"/api/v1/orders/{early.json()['id']}/confirm", headers=org_owner_headers)
    overdue = await client.get("/api/v1/orders?overdue=true", headers=org_owner_headers)
    assert [o["id"] for o in overdue.json()] == [early.json()["id"]]

    dashboard = await client.get("/api/v1/dashboard", headers=org_owner_headers)
    assert dashboard.json()["orders_due"] == 1


async def test_atp_allocates_incoming_by_deadline(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="ATP-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "160")
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": "C-ATP", "name": "ATP 客户"},
    )
    due = datetime.now(UTC) + timedelta(days=5)
    order1 = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": ids["product_id"], "ordered_qty": "80"}],
            "required_at": due.isoformat(),
        },
    )
    order2 = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": ids["product_id"], "ordered_qty": "80"}],
            "required_at": (due + timedelta(hours=1)).isoformat(),
        },
    )
    await client.post(f"/api/v1/orders/{order1.json()['id']}/confirm", headers=org_owner_headers)
    await client.post(f"/api/v1/orders/{order2.json()['id']}/confirm", headers=org_owner_headers)
    supplier = await client.post(
        "/api/v1/suppliers",
        headers=org_owner_headers,
        json={"code": "S-ATP", "name": "ATP 供应商"},
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
                    "expected_at": (due - timedelta(days=1)).isoformat(),
                }
            ],
        },
    )
    await client.post(f"/api/v1/purchase-orders/{po.json()['id']}/confirm", headers=org_owner_headers)

    # 模拟“预留覆盖缺失”：两单各缺 80，只有一笔在途 100。
    async with new_session() as db:
        for order_id in (order1.json()["id"], order2.json()["id"]):
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
    # 最早订单分到 80，较晚订单只剩 20 → 恰好 1 单风险。
    assert dashboard.json()["at_risk_orders"] == 1
    health = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    fulfillment = next(
        a for a in health.json()["alerts"] if a["alert_type"] == "ORDER_FULFILLMENT_RISK"
    )
    assert len(fulfillment["evidence_json"]["orders"]) == 1


async def test_inventory_product_level_fields_and_projected(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup(client, org_owner_headers, sku="PROJ-01")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh1"], "100")
    await _receive(client, org_owner_headers, ids["product_id"], ids["wh2"], "50")
    listing = await client.get("/api/v1/inventory", headers=org_owner_headers)
    rows = [r for r in listing.json() if r["product_id"] == ids["product_id"]]
    assert len(rows) == 2
    assert rows[0]["health_status"] == rows[1]["health_status"]
    assert rows[0]["incoming"] == rows[1]["incoming"]
    assert "expired_qty" in rows[0] and "projected" in rows[0]
    single = await client.get(
        f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers
    )
    assert Decimal(single.json()["available"]) == Decimal("150")
    assert Decimal(single.json()["projected"]) == Decimal("150")
    overview = await client.get(
        f"/api/v1/products/{ids['product_id']}/overview", headers=org_owner_headers
    )
    assert Decimal(overview.json()["inventory"]["projected"]) == Decimal("150")
    wb = await client.get("/api/v1/purchase-workbench", headers=org_owner_headers)
    item = next(i for i in wb.json() if i["product_id"] == ids["product_id"])
    assert Decimal(item["projected"]) == Decimal("150")


async def _org_id(db) -> str:
    from app.domains.identity.models import Organization

    org = (await db.execute(select(Organization).limit(1))).scalar_one()
    return str(org.id)
