# InventoryOS 实施进度

> 本文件是跨会话续做的事实源。每个阶段完成后必须更新。

## Phase 0 — Repo / Skills / Docs

**已完成**

- 创建 monorepo `inventory-os`（D:\Users\yaoni\Desktop\供应链\inventory-os）。
- `git init`（main 分支）。
- GitHub CLI 已登录（Yaoniguan-Money），后续创建 private repo 并 push。
- 安装仓库级 Skills：
  - GSAP（8 个）：gsap-core / gsap-frameworks / gsap-performance / gsap-plugins / gsap-react / gsap-scrolltrigger / gsap-timeline / gsap-utils
  - Matt Pocock engineering（17 个）：ask-matt / code-review / codebase-design / diagnosing-bugs / domain-modeling / grill-with-docs / implement / improve-codebase-architecture / prototype / research / resolving-merge-conflicts / setup-matt-pocock-skills / tdd / to-spec / to-tickets / triage / wayfinder / wizard
  - 位置：`.agents/skills/`
- 根文件：AGENTS.md / README.md / .gitignore / .env.example / docker-compose.yml / Makefile
- 文档：CONTEXT.md / DECISIONS.md / API.md / DEMO.md / PROGRESS.md / docs/agents/*
- CI 骨架（.github/workflows/ci.yml）

**当前可运行能力**：尚未初始化 backend/frontend（Phase 0 进行中）。

**测试结果**：无。

**剩余事项**

- backend/frontend 脚手架初始化。
- `gh repo create inventory-os --private --source . --remote origin` 并首次 push。

**关键文件**：见上。

**下一步**：初始化 backend（uv + FastAPI）与 frontend（Vite + React + TS）。

## Phase 1 — Backend Foundation

**已完成**

- FastAPI + SQLAlchemy 2.x + asyncpg + Alembic + PostgreSQL（docker compose，端口 5433）。
- 全量初始迁移 `6ac2490bd8b9`（identity/catalog/warehouse/orders/purchasing/pricing/market/health/equipment/knowledge/integrations 全部表）。
- Organization / User / Membership / RBAC scope（OWNER/ADMIN/MANAGER/WAREHOUSE/SALES/PURCHASING/VIEWER）。
- Argon2 密码哈希 + JWT 登录；`/auth/login|logout|me`；用户管理；API Key 创建/列出/撤销（仅创建时显示明文，sha256 存储）。
- 跨组织隔离、403 权限测试通过。

**测试**：`tests/test_identity.py` 6 项通过。

## Phase 2 — Catalog + Warehouse

**已完成**

- Product CRUD（UNIQUE(org, sku)）；Warehouse / Location；InventoryLot / StockMovement / InventoryBalance（行锁 + 版本号）。
- Receive（批次、移动加权平均成本、LAST_PURCHASE_PRICE/WEIGHTED_AVG_COST 快照、EventLog、AuditLog）；Adjust（禁止负库存）。
- 库存列表 / 批次 / 流水接口；StockMovement 无 DELETE API。

**测试**：`tests/test_catalog_warehouse.py` 6 项通过。

## Phase 3 — Orders + Reservations + Fulfillment

**已完成**

- Customer / SalesOrder / SalesOrderLine / InventoryReservation / Delivery / DeliveryLine。
- DRAFT → CONFIRMED（预留）→ PARTIAL / FULFILLED → CANCELLED（释放）。
- 部分交付不重复扣 Available；禁止超预留发货；并发确认防超卖（行锁）；确认时返回缺口 + incoming。
- 订单确认记录 ACTUAL_SELL_PRICE 快照。

**测试**：`tests/test_orders.py` 7 项通过（含 1000/300/100 标准场景与并发测试）。

## Phase 4 — Purchases + Pricing

**已完成**

- Supplier / PurchaseOrder / PurchaseOrderLine；DRAFT → CONFIRMED（Incoming）→ PARTIAL/RECEIVED。
- 采购到货走正式 Receive 事务（批次 + 流水 + 平均成本 + 最近采购价）。
- `/purchase-workbench`：On Hand / Reserved / Available / Incoming / 7 日需求 / 缺口 / 最近采购价 / 供应商 / PO。
- 目标售价维护（TARGET_SELL_PRICE 快照）；价格历史接口。

**测试**：`tests/test_purchasing_pricing.py` 7 项通过。

## Phase 5 — Persistent Events + Integrations + SSE

**已完成**

- EventLog（sequence_id BIGSERIAL 游标 + event_id UUID 分离）+ 全局事件写入。
- `GET /events/stream?after=<seq>`：org 作用域、断点恢复、heartbeat、可选 limit 追赶。
- `POST /integrations/events`：统一 Envelope、schema_version、API Key 认证、`event_id+source+org` 幂等（InboundEvent 唯一约束）、返回 accepted/duplicate/rejected。
- 支持 `inventory.received` / `inventory.adjusted` 事件类型，字段错误明确指出。

**测试**：`tests/test_integrations_sse.py` 4 项通过（含 SSE after 游标恢复）。

## Phase 6 — Inventory Health

**已完成**

- 确定性规则：STOCKOUT_RISK（7 日缺口）、OVERSTOCK（覆盖天数）、DORMANT_STOCK、EXPIRY_RISK、ORDER_FULFILLMENT_RISK、PRICE_PRESSURE、DATA_ANOMALY。
- 每条告警带 evidence_json，UI/AI 共用同一证据；健康分 0~100 可解释扣分。
- `/health/overview`、`/health/alerts`、`/products/{id}/health`、`/health/recalculate`。

**测试**：`tests/test_health.py` 5 项通过。

## Phase 7 — Market Intelligence

**已完成**

- MarketDataProvider 抽象 + MockMarketProvider（明确 Demo 标记）+ GenericHttpJsonProvider + GenericRssProvider。
- MarketQuote / MarketEvent / ProductMarketMapping；来源、时间、币种、地区完整保存。
- `/products/{id}/market`、`/market/refresh`、商品映射接口；PRICE_PRESSURE 规则联动。

**测试**：`tests/test_market.py` 4 项通过。

## Phase 8.5（后端）— Equipment + Knowledge

**已完成**

- 设备档案 / 点检 / 故障 / 维修记录；维修备件领用走正式库存出库服务（SHIPMENT 流水）。
- 设备诊断：检索设备手册 + 历史故障，输出可能原因 + 检查步骤 + 引用 + 免责声明。
- KnowledgeDocument / Version / Chunk / EntityLink；ORGANIZATION+access_scope 权限过滤检索；来源引用。

**测试**：`tests/test_equipment_knowledge.py` 4 项通过。

## Phase 9（后端）— AI + Forecast

**已完成**

- AIProvider 抽象（capability 声明）；DemoAIProvider（无 Key 可运行）+ OpenAI-compatible Provider。
- 员工助手（权限过滤 → 知识检索 → 只读业务 Tool → 证据组合 → 回答）。
- 商品识别（条码 exact match 自动确认，文本/图片需确认）；告警解释基于 evidence。
- ForecastProvider 契约 + DisabledForecastProvider；capability 明确 disabled，不生成伪预测。

**测试**：`tests/test_ai.py` 6 项通过。

**当前后端状态**：mypy 0 errors、ruff clean、`alembic check` 无漂移、pytest 48 项全通过。

**下一步**：前端业务 UI（Phase 8）。

## BLOCKERS

无。
