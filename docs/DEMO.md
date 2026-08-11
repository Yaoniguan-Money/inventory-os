# Demo 指南

## 准备

```bash
docker compose up -d postgres
cd backend
uv run alembic upgrade head
uv run python -m app.scripts.seed
uv run uvicorn app.main:app --reload
cd ../frontend && npm install && npm run dev
```

访问 http://localhost:5173 ，使用 `admin@inventoryos.dev` / `Demo@12345` 登录。

## 主故事（Scene 1~7）

### Scene 1 — 新货入库

商品中心 → 打开 `A001 精密铝合金板材` → 「入库」：数量 500、单位购入价 ¥82、批次 `LOT-NEW-1` → 确认。

观察：On Hand / 驾驶舱数字实时变化（SSE 触发重新拉取）。

### Scene 2 — 销售订单

订单中心 → 新建订单：客户 `C001`、商品 `A001`、数量 300、成交价 ¥116 → 创建草稿 → 确认。

观察：Reserved +300，Available -300。

### Scene 3 — 部分交付

打开该订单 → 「交付」100 件 → 订单进入 `PARTIAL`。

观察：On Hand -100、Reserved -100、Delivered +100，Available 没有被扣两遍。

### Scene 4 — 商品全景

打开 `A001`：一页看到库存、批次、订单履约、企业价格（最近采购价/平均成本/目标售价/成交价）、外部市场行情、风险、时间线。

### Scene 5 — 库存健康

风险中心：`STOCKOUT_RISK` 告警展示证据（available / due_demand / incoming / shortage）。点「为什么」→ AI 基于 evidence 解释。

### Scene 6 — 市场行情

市场行情页选择 `A001`：展示 Mock Provider 的市场采购价/常见售价、来源与更新时间；企业内部价格与外部价格明确分区。

### Scene 7 — 开放能力

集成与设置：创建 API Key，然后用：

```bash
curl -X POST http://localhost:8000/api/v1/integrations/events \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <创建的key>" \
  -d '{
    "schema_version": "1.0",
    "event_id": "ext-demo-001",
    "type": "inventory.received",
    "occurred_at": "2026-08-11T08:00:00Z",
    "source": "erp",
    "data": {"sku": "A001", "warehouse": "WH01", "quantity": "500", "unit_price": "82.00", "currency": "CNY"}
  }'
```

重放同一事件返回 `duplicate`。SSE：`GET /api/v1/events/stream?after=<seq>`。

## 默认数据

10 个 SKU；4 个典型商品：A001 订单压力、A002 积压、A003 临期（14 天后过期批次）、A004 健康；5 个订单（已完成/部分/未交付）；1 张采购单在途；市场行情；设备 E-07 与知识文档。
