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
    import pytest

    from app.providers.market import (
        GenericHttpJsonProvider,
        GenericRssProvider,
        MockMarketProvider,
        OpenErApiFxProvider,
        get_market_provider,
    )

    assert get_market_provider("mock").name == "mock"
    assert get_market_provider("http_json").name == "http_json"
    assert get_market_provider("rss").name == "rss"
    assert get_market_provider("open_er_api").name == "open_er_api"
    assert MockMarketProvider().name == "mock"
    assert GenericHttpJsonProvider().name == "http_json"
    assert GenericRssProvider().name == "rss"
    assert OpenErApiFxProvider().name == "open_er_api"
    with pytest.raises(ValueError):
        get_market_provider("open_er_ap1")


async def test_unknown_market_provider_rejected(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    product = await client.post(
        "/api/v1/products", headers=org_owner_headers, json={"sku": "P-BAD", "name": "坏映射"}
    )
    assert product.status_code == 201
    resp = await client.post(
        f"/api/v1/products/{product.json()['id']}/market-mappings",
        headers=org_owner_headers,
        json={"provider": "open_er_ap1", "external_symbol": "USD", "region": "INTERNATIONAL"},
    )
    assert resp.status_code == 422


async def test_refresh_uses_mapping_provider(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    """不同映射使用不同 Provider：mock 保存行情，未配置 URL 的 http_json 不保存。"""

    await client.post(
        "/api/v1/warehouses", headers=org_owner_headers, json={"code": "WH01", "name": "一号仓库"}
    )
    p1 = await client.post(
        "/api/v1/products", headers=org_owner_headers, json={"sku": "P1", "name": "映射1"}
    )
    p2 = await client.post(
        "/api/v1/products", headers=org_owner_headers, json={"sku": "P2", "name": "映射2"}
    )
    await client.post(
        f"/api/v1/products/{p1.json()['id']}/market-mappings",
        headers=org_owner_headers,
        json={"provider": "mock", "external_symbol": "SYM1", "region": "DOMESTIC"},
    )
    await client.post(
        f"/api/v1/products/{p2.json()['id']}/market-mappings",
        headers=org_owner_headers,
        json={"provider": "http_json", "external_symbol": "SYM2", "region": "DOMESTIC"},
    )
    result = (await client.post("/api/v1/market/refresh", headers=org_owner_headers)).json()
    assert result["refreshed"] == 2
    assert result["quotes_saved"] == 2  # 只有 mock 映射写入
    market1 = await client.get(
        f"/api/v1/products/{p1.json()['id']}/market", headers=org_owner_headers
    )
    market2 = await client.get(
        f"/api/v1/products/{p2.json()['id']}/market", headers=org_owner_headers
    )
    assert len(market1.json()["quotes"]) == 2
    assert market2.json()["quotes"] == []


async def test_open_er_api_provider_parses_real_rates(monkeypatch) -> None:
    from app.providers.market.open_er_api import OpenErApiFxProvider

    class FakeResponse:
        def json(self):
            return {"result": "success", "rates": {"USD": "0.14"}}

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr("app.providers.market.open_er_api.httpx.AsyncClient", FakeClient)
    provider = OpenErApiFxProvider()
    quotes = await provider.get_latest_quotes("USD", "INTERNATIONAL")
    assert len(quotes) == 1
    assert quotes[0].external_symbol == "USD"
    assert str(quotes[0].price).startswith("7.14")
    assert quotes[0].source.startswith("OpenErApiFxProvider")


async def test_workbench_includes_market_quotes(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    ids = await _setup_market(client, org_owner_headers, sku="WB01", symbol="WB-SYM")
    await client.post("/api/v1/market/refresh", headers=org_owner_headers)
    wb = await client.get("/api/v1/purchase-workbench", headers=org_owner_headers)
    assert wb.status_code == 200
    item = next(i for i in wb.json() if i["product_id"] == ids["product_id"])
    domestic = item["market_quotes"]["DOMESTIC"]
    assert "MARKET_BUY" in domestic
    assert domestic["MARKET_BUY"]["source"] == "MockMarketProvider (Demo)"
    assert domestic["MARKET_BUY"]["observed_at"]
    assert Decimal(domestic["MARKET_BUY"]["price"]) > 0


async def test_product_overview_has_due_7d_and_trends(
    client: httpx.AsyncClient, org_owner_headers: dict[str, str]
) -> None:
    from datetime import UTC, datetime, timedelta

    wh = await client.post(
        "/api/v1/warehouses", headers=org_owner_headers, json={"code": "WH01", "name": "一号仓库"}
    )
    product = await client.post(
        "/api/v1/products",
        headers=org_owner_headers,
        json={
            "sku": "TREND01",
            "name": "趋势商品",
            "default_warehouse_id": wh.json()["id"],
            "market_tracking_enabled": True,
        },
    )
    product_id = product.json()["id"]
    await client.post(
        "/api/v1/inventory/receive",
        headers=org_owner_headers,
        json={
            "product_id": product_id,
            "warehouse_id": wh.json()["id"],
            "quantity": "100",
            "unit_cost": "80.00",
            "lot_code": "LOT-TREND",
        },
    )
    await client.post(
        f"/api/v1/products/{product_id}/market-mappings",
        headers=org_owner_headers,
        json={"provider": "mock", "external_symbol": "TREND-SYM", "region": "DOMESTIC"},
    )
    await client.post("/api/v1/market/refresh", headers=org_owner_headers)
    customer = await client.post(
        "/api/v1/customers",
        headers=org_owner_headers,
        json={"code": "C-TREND", "name": "趋势客户"},
    )
    order = await client.post(
        "/api/v1/orders",
        headers=org_owner_headers,
        json={
            "customer_id": customer.json()["id"],
            "lines": [{"product_id": product_id, "ordered_qty": "30"}],
            "required_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
        },
    )
    await client.post(f"/api/v1/orders/{order.json()['id']}/confirm", headers=org_owner_headers)

    overview = await client.get(f"/api/v1/products/{product_id}/overview", headers=org_owner_headers)
    assert overview.status_code == 200
    data = overview.json()
    assert Decimal(data["inventory"]["due_7d"]) == Decimal("30")
    assert len(data["trends"]["on_hand"]) >= 1
    assert len(data["trends"]["available"]) >= 1
    assert len(data["trends"]["weighted_avg_cost"]) >= 1
    assert len(data["trends"]["market_buy_domestic"]) >= 1
    assert data["trends"]["market_buy_domestic"][0]["source"]
