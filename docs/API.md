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

> 请求/响应 schema 见 FastAPI `/docs`（OpenAPI）。当前实现以真实路由为准。
