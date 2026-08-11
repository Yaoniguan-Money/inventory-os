from __future__ import annotations

from decimal import Decimal

import httpx


async def _setup_integration(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> dict[str, str]:
    wh = await client.post(
        "/api/v1/warehouses", headers=headers, json={"code": "WH01", "name": "一号仓库"}
    )
    assert wh.status_code == 201
    product = await client.post(
        "/api/v1/products",
        headers=headers,
        json={"sku": "EXT01", "name": "外部接入商品", "unit": "pcs"},
    )
    assert product.status_code == 201
    key = await client.post(
        "/api/v1/integrations/api-keys",
        headers=headers,
        json={"name": "erp", "scopes": ["inventory:receive"]},
    )
    assert key.status_code == 201
    return {
        "product_id": product.json()["id"],
        "api_key": key.json()["api_key"],
    }


async def test_integration_event_receive_and_idempotency(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_integration(client, org_owner_headers)
    envelope = {
        "schema_version": "1.0",
        "event_id": "ext-001",
        "type": "inventory.received",
        "occurred_at": "2026-08-11T08:00:00Z",
        "source": "erp",
        "data": {
            "sku": "EXT01",
            "warehouse": "WH01",
            "quantity": "500",
            "unit_price": "82.00",
            "currency": "CNY",
        },
    }
    headers = {"X-API-Key": ids["api_key"]}
    first = await client.post("/api/v1/integrations/events", headers=headers, json=envelope)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "accepted"

    inv = await client.get(f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers)
    assert Decimal(inv.json()["on_hand"]) == Decimal("500")

    replay = await client.post("/api/v1/integrations/events", headers=headers, json=envelope)
    assert replay.status_code == 200
    assert replay.json()["status"] == "duplicate"

    inv_after = await client.get(f"/api/v1/inventory/{ids['product_id']}", headers=org_owner_headers)
    assert Decimal(inv_after.json()["on_hand"]) == Decimal("500")


async def test_integration_event_rejects_bad_input(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_integration(client, org_owner_headers)
    headers = {"X-API-Key": ids["api_key"]}
    bad = await client.post(
        "/api/v1/integrations/events",
        headers=headers,
        json={
            "schema_version": "1.0",
            "event_id": "ext-002",
            "type": "inventory.received",
            "source": "erp",
            "data": {"sku": "UNKNOWN", "warehouse": "WH01", "quantity": "1"},
        },
    )
    assert bad.status_code == 200
    assert bad.json()["status"] == "rejected"
    assert "SKU 不存在" in bad.json()["message"]

    unknown_type = await client.post(
        "/api/v1/integrations/events",
        headers=headers,
        json={
            "schema_version": "1.0",
            "event_id": "ext-003",
            "type": "robot.move",
            "source": "erp",
            "data": {},
        },
    )
    assert unknown_type.json()["status"] == "rejected"

    missing_version = await client.post(
        "/api/v1/integrations/events",
        headers=headers,
        json={
            "event_id": "ext-004",
            "type": "inventory.received",
            "source": "erp",
            "data": {},
        },
    )
    assert missing_version.status_code == 422


async def test_integration_event_requires_valid_api_key(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    await _setup_integration(client, org_owner_headers)
    resp = await client.post(
        "/api/v1/integrations/events",
        headers={"X-API-Key": "io_bad.wrong"},
        json={
            "schema_version": "1.0",
            "event_id": "ext-005",
            "type": "inventory.received",
            "source": "erp",
            "data": {"sku": "EXT01", "warehouse": "WH01", "quantity": "1"},
        },
    )
    assert resp.status_code == 403


async def test_sse_streams_after_cursor(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_integration(client, org_owner_headers)
    await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": (await client.get("/api/v1/warehouses", headers=org_owner_headers)).json()[0]["id"],
            "quantity": "10",
        },
    )
    timeline = await client.get(
        f"/api/v1/products/{ids['product_id']}/timeline", headers=org_owner_headers
    )
    assert timeline.status_code == 200
    assert len(timeline.json()) >= 2  # product.created + inventory.received
    after_id = timeline.json()[0]["sequence_id"]  # timeline is newest-first

    async with client.stream(
        "GET",
        f"/api/v1/events/stream?after={after_id - 1}&limit=1",
        headers=org_owner_headers,
    ) as response:
        assert response.status_code == 200
        first_line = ""
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                first_line = line
                break
    assert first_line.startswith("data: ")
    assert '"event_type": "inventory.received"' in first_line
