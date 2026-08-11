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
- 工作台同时返回国内/国际最新市场行情（价格、币种、来源、时间）。
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

- MarketDataProvider 抽象 + MockMarketProvider（明确 Demo 标记）+ GenericHttpJsonProvider + GenericRssProvider + OpenErApiFxProvider（真实国际汇率参考，无需 Key）。
- MarketQuote / MarketEvent / ProductMarketMapping；来源、时间、币种、地区完整保存。
- `/products/{id}/market`、`/market/refresh`、商品映射接口；PRICE_PRESSURE 规则联动。
- refresh 按映射选择 Provider（不同 SKU 可挂不同数据源）；默认配置开箱即用真实国际参考源（`MARKET_PROVIDER=open_er_api`）。

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

## Phase 8 — Frontend Business UI

**已完成**

- React 19 + TS + Vite + Tailwind v4 + TanStack Query + React Router + GSAP + ECharts 依赖就绪。
- 深色经营驾驶舱视觉；红色仅表示风险；关键数字 tabular-nums；数字变化 200~500ms GSAP 动效且尊重 `prefers-reduced-motion`。
- 页面：登录、经营驾驶舱、商品中心、商品详情（旗舰页）、订单中心/详情、仓库中心、采购中心、市场行情、风险中心、设备维护/详情、企业知识库、员工助手、集成与设置。
- SSE 客户端：收到 `inventory.*`/`orders.*`/`price.*`/`market.*`/`health.*` 等事件后精准 invalidate query，REST 重新拉取权威状态。
- 商品详情一页含：库存指标、企业价格、外部市场、订单履约、批次、风险告警（可 AI 解释）、时间线。
- 旗舰页增强：未来 7 日待交付指标；订单表含客户 / Reserved / 要求交付 / 成交价；库存/可用、成本/成交价、国内外市场行情趋势图（ECharts）；市场卡片明确拆分为国内/国际。
- 前端测试：Vitest 5 项（format、UI primitives）；typecheck / lint / build 通过。

## Phase 8.5（前端）— Equipment + Knowledge UI

**已完成**

- 设备列表/详情：点检、故障记录、维修记录、AI 诊断（含引用与免责声明）。
- 知识库：文档列表、新建（自动分块）、权限过滤检索、来源引用。
- 员工助手聊天页：问题 → 权限过滤 → 知识检索 → 业务 Tool → 证据回答。

## Phase 9（前端）— AI 能力入口

**已完成**

- 员工助手、告警解释、商品识别（条码自动确认/文本需确认）、AI capability 展示。
- 无 AI Key 时全系统正常运行（DemoAIProvider 明确标记）。

## Phase 10 — Demo / E2E / Polish

**已完成**

- Demo seed（幂等）：10 个 SKU（A001 订单压力 / A002 积压 / A003 临期 / A004 健康 + 6 个常规）、5 个订单（已完成/部分/未交付）、1 张采购在途、市场行情、设备 E-07、知识文档。
- `app/scripts/reset_e2e.py`：一键重建 e2e 数据库并 seed。
- Playwright 核心链路 E2E 通过：登录 → 打开商品 A → 创建订单 → 确认 → 查看 Reserved/Available 变化 → 部分交付 → PARTIAL → 商品时间线 → 库存风险。
- README / DEMO / API 文档补全；`.env.example` 补充 Market/HTTP/RSS 配置。
- 代码已提交并推送至 GitHub 私有仓库：https://github.com/Yaoniguan-Money/inventory-os

## 安全与边界回归修复（第二轮审计）

- 跨租户脏引用：Product 创建/更新校验 default_warehouse_id / default_location_id 必须属于当前组织；订单确认 `_default_warehouse()` 按 organization_id 重新校验，历史脏数据直接拒绝（404）。攻击型回归测试 4 项。
- 知识库权限绕过：设备诊断按调用者角色过滤 `access_scope=OWNER` 的文档，普通设备查看者无法获得管理层文档片段。回归测试 1 项。
- 批次边界 Bug：有批次 + 无批次混存时，出库先消费批次、剩余部分从未批次余额出库，不再错误抛“批次库存不足”（订单履约与备件领用两处一致）。回归测试 1 项。
- 多批次成本快照：一次发货横跨多个 Lot 时，DeliveryLine.unit_cost_snapshot 按实际发货数量加权平均，不再只记第一批成本。回归测试 1 项。
- 采购工作台补齐国内/国际市场行情；商品详情补齐 7 日待交付、订单关键列、趋势图与国内/国际行情拆分。
- Market Provider 按映射选择并默认接入真实国际汇率参考源（open_er_api，无 Key）；前端映射表单可选 Provider。
- 当前后端测试 59 项全通过（含 8 项新增回归），前端 5 项测试 + E2E 通过。

## Definition of Done 核对

- [x] private repo 创建：https://github.com/Yaoniguan-Money/inventory-os
- [x] 两组 Skills 已安装到仓库级 `.agents/skills`（GSAP 8 个 + Matt Pocock engineering 17 个）
- [x] 后端可启动（uvicorn，E2E 实测）
- [x] 前端可启动（vite dev，E2E 实测）
- [x] PostgreSQL migration 一键执行（`alembic upgrade head`，`alembic check` 无漂移）
- [x] seed 一键执行（幂等）
- [x] 可登录；有 organization + role
- [x] 可创建 SKU；可入库；可记录单位购入价；可查看批次、库位、流水
- [x] 可创建订单；确认占用库存；部分交付；全部交付；取消释放占用
- [x] 可创建采购订单；有 Incoming；采购到货进入库存
- [x] 最近采购价 / 移动平均成本 / 目标售价 / 订单实际成交价
- [x] Market Buy / Sell，来源与更新时间
- [x] 库存健康规则 + 可解释 evidence
- [x] 商品详情一页联动；Dashboard 整体风险
- [x] 外部系统 API Key + HTTP/JSON 接入，事件幂等；SSE 断点恢复
- [x] AI 无 Key 不影响核心业务；AI 不直接修改库存账
- [x] 设备档案/点检/故障/维修；故障诊断带来源；备件关联 SKU 库存
- [x] 知识库录入/检索/权限过滤/引用；员工助手查询知识与业务数据
- [x] 采购中心统一视图（库存/在途/需求/历史采购价/供应商/行情）
- [x] ForecastProvider / capability / API 存在且 disabled；UI 无伪预测
- [x] 未实现面向客户客服助手
- [x] 权限测试、核心库存/订单测试通过（pytest 59 项，含跨租户/权限绕过/批次边界/成本快照回归）
- [x] Playwright 核心链路通过
- [x] CI 工作流已配置；本地等价检查（ruff/mypy/pytest/build/typecheck/lint/test）全绿，推送后由 GitHub Actions 验证
- [x] docs/PROGRESS.md 处于最终完成状态
- [x] README 可让新机器独立跑起来

## BLOCKERS

无。外部 Provider（市场、AI）按计划以明确标记的 Mock/Demo Provider 运行，接口与数据模型保持可替换；接入真实 Key 即可启用。

## BLOCKERS

无。
