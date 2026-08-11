from __future__ import annotations

from decimal import Decimal

import httpx
from sqlalchemy import select

from app.core.database import new_session
from app.domains.warehouse.models import StockMovement


async def _setup_equipment(client: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    wh = await client.post(
        "/api/v1/warehouses", headers=headers, json={"code": "WH01", "name": "一号仓库"}
    )
    assert wh.status_code == 201
    warehouse_id = wh.json()["id"]
    product = await client.post(
        "/api/v1/products",
        headers=headers,
        json={"sku": "SP-01", "name": "轴承备件", "unit": "pcs", "default_warehouse_id": warehouse_id},
    )
    assert product.status_code == 201
    product_id = product.json()["id"]
    await client.post(
        "/api/v1/inventory/receive",
        headers=headers,
        json={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity": "10",
            "unit_cost": "50.00",
        },
    )
    equipment = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={
            "asset_code": "E-07",
            "name": "数控机床",
            "model": "CNC-500",
            "serial_number": "SN-2024-0007",
            "location": "一号车间",
            "production_line": "L1",
            "status": "OPERATIONAL",
        },
    )
    assert equipment.status_code == 201, equipment.text
    return {
        "warehouse_id": warehouse_id,
        "product_id": product_id,
        "equipment_id": equipment.json()["id"],
    }


async def test_equipment_lifecycle_and_part_usage(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_equipment(client, org_owner_headers)
    equipment_id = ids["equipment_id"]

    inspection = await client.post(
        f"/api/v1/equipment/{equipment_id}/inspections",
        headers=org_owner_headers,
        json={
            "inspection_type": "DAILY",
            "result": "PASS",
            "notes": "正常",
            "measurements_json": {"temp": 42},
        },
    )
    assert inspection.status_code == 201

    fault = await client.post(
        f"/api/v1/equipment/{equipment_id}/faults",
        headers=org_owner_headers,
        json={"fault_code": "302", "symptom": "主轴异响并报错 302", "severity": "HIGH"},
    )
    assert fault.status_code == 201
    fault_id = fault.json()["id"]

    maintenance = await client.post(
        f"/api/v1/equipment/{equipment_id}/maintenance",
        headers=org_owner_headers,
        json={
            "fault_record_id": fault_id,
            "maintenance_type": "REPLACE_BEARING",
            "description": "更换主轴轴承",
            "downtime_minutes": 90,
            "parts": [{"product_id": ids["product_id"], "quantity": "2"}],
        },
    )
    assert maintenance.status_code == 201, maintenance.text
    assert len(maintenance.json()["parts"]) == 1
    assert Decimal(maintenance.json()["parts"][0]["quantity"]) == Decimal("2")

    # 备件通过正式库存出库服务扣减。
    inv = await client.get(f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers)
    assert Decimal(inv.json()["on_hand"]) == Decimal("8")
    async with new_session() as db:
        movements = (
            await db.execute(
                select(StockMovement).where(
                    StockMovement.reference_type == "MAINTENANCE"
                )
            )
        ).scalars().all()
        assert len(movements) == 1
        assert movements[0].movement_type == "SHIPMENT"

    detail = await client.get(
        f"/api/v1/equipment/{equipment_id}/maintenance", headers=org_owner_headers
    )
    assert len(detail.json()) == 1


async def test_diagnose_returns_citations_from_knowledge(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_equipment(client, org_owner_headers)
    equipment_id = ids["equipment_id"]
    doc = await client.post(
        "/api/v1/knowledge/documents",
        headers=org_owner_headers,
        json={
            "title": "E-07 设备手册",
            "document_type": "MANUAL",
            "access_scope": "ORG",
            "content": (
                "错误码 302：主轴电机过载。\n"
                "第一步：检查主轴负载。\n"
                "第二步：检查轴承润滑。\n"
                "第三步：如异响持续，更换轴承。"
            ),
            "entity_links": [
                {
                    "entity_type": "EQUIPMENT",
                    "entity_id": equipment_id,
                    "relation_type": "MANUAL",
                }
            ],
        },
    )
    assert doc.status_code == 201, doc.text

    await client.post(
        f"/api/v1/equipment/{equipment_id}/faults",
        headers=org_owner_headers,
        json={"fault_code": "302", "symptom": "主轴异响"},
    )
    diagnose = await client.post(
        f"/api/v1/equipment/{equipment_id}/diagnose",
        headers=org_owner_headers,
        json={"fault_code": "302", "symptom": "主轴异响"},
    )
    assert diagnose.status_code == 200, diagnose.text
    result = diagnose.json()
    assert result["possible_causes"]
    assert result["recommended_steps"]
    assert "辅助判断" in result["disclaimer"]
    titles = {c["title"] for c in result["citations"]}
    assert "E-07 设备手册" in titles
    assert any(c["source_type"] == "history" for c in result["citations"])


async def test_knowledge_search_and_access_scope(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    await _setup_equipment(client, org_owner_headers)
    public_doc = await client.post(
        "/api/v1/knowledge/documents",
        headers=org_owner_headers,
        json={
            "title": "仓库 SOP",
            "document_type": "SOP",
            "access_scope": "ORG",
            "content": "A103 应存放在 A 区第三排。",
        },
    )
    assert public_doc.status_code == 201
    owner_doc = await client.post(
        "/api/v1/knowledge/documents",
        headers=org_owner_headers,
        json={
            "title": "管理层保密资料",
            "document_type": "POLICY",
            "access_scope": "OWNER",
            "content": "成本敏感信息仅管理层可见。",
        },
    )
    assert owner_doc.status_code == 201

    search = await client.post(
        "/api/v1/knowledge/search",
        headers=org_owner_headers,
        json={"query": "A103"},
    )
    assert search.status_code == 200
    assert len(search.json()["hits"]) >= 1
    assert search.json()["hits"][0]["document_title"] == "仓库 SOP"

    # 创建普通员工，不应搜到 OWNER 文档。
    created = await client.post(
        "/api/v1/users",
        headers=org_owner_headers,
        json={
            "email": "worker@example.com",
            "password": "Worker@12345",
            "display_name": "员工",
            "role": "WAREHOUSE",
        },
    )
    assert created.status_code == 201
    from app.core.security import create_access_token
    from app.domains.identity.models import User

    async with new_session() as db:
        worker = (
            await db.execute(select(User).where(User.email == "worker@example.com"))
        ).scalar_one()
        token = create_access_token(str(worker.id))
    worker_headers = {"Authorization": f"Bearer {token}"}
    worker_search = await client.post(
        "/api/v1/knowledge/search",
        headers=worker_headers,
        json={"query": "成本敏感"},
    )
    assert worker_search.status_code == 200
    assert worker_search.json()["hits"] == []

    docs = await client.get("/api/v1/knowledge/documents", headers=worker_headers)
    titles = {d["title"] for d in docs.json()}
    assert "管理层保密资料" not in titles


async def test_equipment_cross_org_isolation(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
    second_org_headers: dict[str, str],
) -> None:
    ids = await _setup_equipment(client, org_owner_headers)
    resp = await client.get(
        f"/api/v1/equipment/{ids['equipment_id']}", headers=second_org_headers
    )
    assert resp.status_code == 404
