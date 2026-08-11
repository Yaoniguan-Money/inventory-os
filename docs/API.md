# API 文档

所有接口前缀 `/api/v1`，OpenAPI 位于 `/docs`（FastAPI 自动生成）。

## Auth

```text
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me
GET  /api/v1/users
POST /api/v1/users
```

## Warehouses / Customers / Suppliers

```text
GET  /api/v1/warehouses
POST /api/v1/warehouses
GET  /api/v1/warehouses/{id}/locations
POST /api/v1/warehouses/{id}/locations
GET  /api/v1/customers
POST /api/v1/customers
GET  /api/v1/suppliers
POST /api/v1/suppliers
GET  /api/v1/purchase-workbench
```

## Products

```text
GET    /api/v1/products
POST   /api/v1/products
GET    /api/v1/products/{id}
PATCH  /api/v1/products/{id}
GET    /api/v1/products/{id}/timeline
GET    /api/v1/products/{id}/overview
POST   /api/v1/products/{id}/market-mappings
```

## Inventory

```text
GET  /api/v1/inventory
GET  /api/v1/inventory/{product_id}
GET  /api/v1/inventory/{product_id}/lots
GET  /api/v1/inventory/{product_id}/movements
POST /api/v1/inventory/receive
POST /api/v1/inventory/adjust
```

## Orders

```text
GET  /api/v1/orders
POST /api/v1/orders
GET  /api/v1/orders/{id}
POST /api/v1/orders/{id}/confirm
POST /api/v1/orders/{id}/fulfill
POST /api/v1/orders/{id}/cancel
```

## Purchases

```text
GET  /api/v1/purchase-orders
POST /api/v1/purchase-orders
GET  /api/v1/purchase-orders/{id}
POST /api/v1/purchase-orders/{id}/confirm
POST /api/v1/purchase-orders/{id}/receive
```

## Prices / Market / Health

```text
GET  /api/v1/products/{id}/prices
POST /api/v1/products/{id}/target-price
GET  /api/v1/products/{id}/market
POST /api/v1/market/refresh
GET  /api/v1/health/overview
GET  /api/v1/health/alerts
GET  /api/v1/products/{id}/health
POST /api/v1/health/recalculate
```

## Equipment / Knowledge

```text
GET  /api/v1/equipment
POST /api/v1/equipment
GET  /api/v1/equipment/{id}
PATCH /api/v1/equipment/{id}
GET  /api/v1/equipment/{id}/inspections
POST /api/v1/equipment/{id}/inspections
GET  /api/v1/equipment/{id}/faults
POST /api/v1/equipment/{id}/faults
GET  /api/v1/equipment/{id}/maintenance
POST /api/v1/equipment/{id}/maintenance
POST /api/v1/equipment/{id}/diagnose
GET  /api/v1/knowledge/documents
POST /api/v1/knowledge/documents
GET  /api/v1/knowledge/documents/{id}
POST /api/v1/knowledge/search
```

## Forecast（V1 明确 disabled）

```text
GET  /api/v1/forecast/capabilities
POST /api/v1/forecast/price
POST /api/v1/forecast/demand
POST /api/v1/forecast/supply-risk
```

请求体（已留好契约）：

```json
{"subject_id": "A001", "horizon": "30d", "params": {}}
```

返回 `enabled=false` 且回显 `subject_id` / `horizon`，不生成预测数据。

`/forecast/*` 需要 `market:read` 权限。

## AI / Integrations / Events

```text
POST /api/v1/ai/chat
POST /api/v1/ai/resolve-product
POST /api/v1/ai/explain-alert/{alert_id}
POST /api/v1/ai/employee-assistant
GET  /api/v1/ai/capabilities
POST /api/v1/integrations/events
GET  /api/v1/integrations/api-keys
POST /api/v1/integrations/api-keys
DELETE /api/v1/integrations/api-keys/{id}
GET  /api/v1/events/stream
GET  /api/v1/events
```

商品识别支持 `barcode` / `text` / `image_data_url`；视觉 Provider 需输出结构化 JSON
（`sku_candidates` / `model` / `barcode` / `keywords`），由 resolver 二次匹配；
条码精确命中才可自动高置信确认，图片/文本结果始终要求人工确认。

## Dashboard

```text
GET /api/v1/dashboard
```

返回：库存金额（按移动平均成本）、On Hand/Reserved、SKU 数、未来 7 日到期订单数、履约风险订单数、健康分、7 日订单压力、即将交付订单、市场价格异常、最新事件。

## API Key scopes

`POST /api/v1/integrations/events` 会按事件类型校验 Key scope：

```text
inventory.received -> inventory:receive
inventory.adjusted  -> inventory:adjust
```

缺少对应 scope 返回 403；未知 Provider 名称在创建映射时返回 422。

## 市场行情语义

- `MarketQuote` 含 `unit`（计价单位）与 `basis`（口径，如 `FX` 表示外汇环境）。
- `open_er_api` 输出标记为 `basis=FX` 的汇率参考，UI 明确显示为“汇率参考（外汇环境）”，
  不参与商品价格压力比较；只有可比口径（非 FX、单位一致或未指定）才计算 `PRICE_PRESSURE`。

## Projected

`Projected = Available + Incoming`，出现在单商品库存、库存列表、商品详情与采购工作台。

> 请求/响应 schema 见 FastAPI `/docs`（OpenAPI）。当前实现以真实路由为准。

## Market Providers

```text
mock           演示行情（明确标记）
open_er_api    真实国际汇率参考（open.er-api.com，无需 Key）
http_json      通用 HTTP/JSON（MARKET_HTTP_URL / MARKET_HTTP_TOKEN）
rss            通用 RSS Feed（MARKET_RSS_URL）
```

`POST /api/v1/market/refresh` 按 `ProductMarketMapping.provider` 逐个映射调用对应 Provider。
