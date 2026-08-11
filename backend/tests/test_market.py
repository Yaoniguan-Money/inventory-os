from __future__ import annotations

from decimal import Decimal

import httpx


async def _setup_market(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    sku: str = "M001",
    symbol: str = "AL-99.7",
) -> dict[str, str]:
    wh = await client.post(
        "/api/v1/warehouses", headers=headers, json={"code": "WH01", "name": "一号仓库"}
    )
    assert wh.status_code == 201
    product = await client.post(
        "/api/v1/products",
        headers=headers,
        json={"sku": sku, "name": "铝锭", "unit": "t", "market_tracking_enabled": True},
    )
    assert product.status_code == 201
    product_id = product.json()["id"]
    mapping = await client.post(
        f"/api/v1/products/{product_id}/market-mappings",
        headers=headers,
        json={"provider": "mock", "external_symbol": symbol, "region": "DOMESTIC"},
    )
    assert mapping.status_code == 201, mapping.text
    return {"product_id": product_id, "warehouse_id": wh.json()["id"]}


async def test_market_refresh_saves_quotes_and_events(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_market(client, org_owner_headers)
    resp = await client.post("/api/v1/market/refresh", headers=org_owner_headers)
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["refreshed"] == 1
    assert result["quotes_saved"] == 2
    assert result["events_saved"] >= 1

    market = await client.get(
        f"/api/v1/products/{ids['product_id']}/market", headers=org_owner_headers
    )
    assert market.status_code == 200
    data = market.json()
    kinds = {q["quote_kind"] for q in data["quotes"]}
    assert kinds == {"MARKET_BUY", "MARKET_SELL"}
    for quote in data["quotes"]:
        assert quote["source"] == "MockMarketProvider (Demo)"
        assert quote["observed_at"]
        assert quote["fetched_at"]
        assert quote["currency"] == "CNY"
        assert quote["region"] == "DOMESTIC"
    assert len(data["events"]) >= 1
    assert data["events"][0]["source"] == "MockMarketProvider (Demo)"


async def test_market_refresh_is_idempotent(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_market(client, org_owner_headers, sku="M002", symbol="CU-1")
    await client.post("/api/v1/market/refresh", headers=org_owner_headers)
    second = (await client.post("/api/v1/market/refresh", headers=org_owner_headers)).json()
    # 时间序列：第二次刷新写入新的观测时点，不产生重复时点。
    assert second["quotes_saved"] == 2
    market = await client.get(
        f"/api/v1/products/{ids['product_id']}/market", headers=org_owner_headers
    )
    quotes = market.json()["quotes"]
    assert len(quotes) == 4
    assert len({q["observed_at"] for q in quotes}) == 2  # BUY/SELL 共享同一观测时点


async def test_price_pressure_alert_uses_market_quote(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_market(client, org_owner_headers, sku="M003", symbol="ZN-1")
    await client.post("/api/v1/market/refresh", headers=org_owner_headers)
    await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={
            "product_id": ids["product_id"],
            "warehouse_id": ids["warehouse_id"],
            "quantity": "10",
            "unit_cost": "200.00",
        },
    )
    health = await client.get(
        f"/api/v1/products/{ids['product_id']}/health", headers=org_owner_headers
    )
    pressure = next(
        (a for a in health.json()["alerts"] if a["alert_type"] == "PRICE_PRESSURE"), None
    )
    assert pressure is not None
    assert Decimal(pressure["evidence_json"]["weighted_avg_cost"]) == Decimal("200")
    assert Decimal(pressure["evidence_json"]["gap_pct"]) > 10


async def test_market_provider_boundaries_exist() -> None:
    from app.providers.market import (
        GenericHttpJsonProvider,
        GenericRssProvider,
        MockMarketProvider,
        get_market_provider,
    )

    assert get_market_provider("mock").name == "mock"
    assert get_market_provider("http_json").name == "http_json"
    assert get_market_provider("rss").name == "rss"
    assert MockMarketProvider().name == "mock"
    assert GenericHttpJsonProvider().name == "http_json"
    assert GenericRssProvider().name == "rss"
