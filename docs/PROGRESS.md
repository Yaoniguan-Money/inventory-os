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
- 批次边界 Bug：有批次 + 无批次混存时，出库先消费批次、剩余部分从未批次余额出库，不再错误抛“批次库存不足”（订单履约与备件领用两处一致）。回归测试 2 项（两条出库链路各 1 项）。
- 多批次成本快照：一次发货横跨多个 Lot 时，DeliveryLine.unit_cost_snapshot 按实际发货数量加权平均，不再只记第一批成本。回归测试 1 项。
- 采购工作台补齐国内/国际市场行情；商品详情补齐 7 日待交付、订单关键列、趋势图与国内/国际行情拆分。
- Market Provider 按映射选择并默认接入真实国际汇率参考源（open_er_api，无 Key）；前端映射表单可选 Provider。
- 当前后端测试 60 项全通过（含 9 项新增回归），前端 5 项测试 + E2E 通过。

## 第三轮审计修复（多仓库 / 权限 / 契约 / 页面规格）

- 多仓库聚合：库存健康、采购工作台、`GET /inventory/{product_id}` 均按 SKU 聚合（On Hand/Reserved/Available 跨仓库求和），不再多结果异常或随机取一行。
- 工作台 7 日需求与健康引擎口径一致：`line.required_at OR order.required_at`。
- AI 员工助手 Tool 级 scope：成本类字段仅 `pricing:cost:read` 可见，SALES 无法通过 AI 问出成本。
- API Key scope 真正执行：事件入口按事件类型校验 scope，缺失返回 403。
- Forecast HTTP 契约补齐：`subject_id` / `horizon` / `params` 请求体已定义并回显，Provider 仍返回 disabled。
- Market Provider 注册表化：未知 Provider 直接 422/报错，禁止 silent fallback 到 Mock。
- 采购工作台：Reserved、历史采购数量/价格时间序列、行情事件、行情更新时间全部上屏。
- 商品旗舰页：状态/条码/默认仓库/默认库位/健康状态头部字段，批次表含位置与入库时间。
- 仓库中心：Incoming、默认库位、健康状态、最近入库/出库、查看流水（movements 弹窗）。
- 订单中心：客户/商品/逾期/交付期限过滤；订单详情每 SKU 显示当前可用、在途、履约风险。
- Dashboard：新增聚合接口 `/api/v1/dashboard`，正确展示库存金额（On Hand×平均成本）、未来 7 日到期订单、履约风险订单、7 日订单压力、即将交付订单（按交付日期排序）、市场价格异常。
- AGENTS.md 补入“最高优先级工程约束”（不得功能降级/silent fallback/DoD 降级、多仓库聚合、Tool/API Key scope 执行）。
- 当前后端测试 71 项全通过（本轮新增 11 项），前端构建/测试与 E2E 待最终验证。

## 第四轮审计修复（健康公式 / 跨仓预留 / 成本聚合 / 智能出入库 / 收尾）

- 库存健康核心公式修正：只对“未被预留覆盖”的到期需求（`unreserved_due`）计算缺口；
  已 100% 预留的订单不再被误报缺货/履约风险。Health、Dashboard、商品详情、订单详情口径统一。
- 跨仓订单分配：确认订单按默认仓优先跨仓拆分 Reservation（WH01 100 + WH02 20 场景）；
  交付按预留 FIFO 跨仓消费批次；取消按预留逐仓释放。
- 移动加权平均成本改为 SKU 全局聚合（入库前 old_on_hand 汇总全仓），价格快照不再被单仓污染。
- `issue_stock`（维修领料）与手工负调整显式尊重 Reserved：最大可扣 = Available，
  禁止悄悄挪用订单预留，由业务层拒绝（409）而非数据库约束兜底。
- 智能出入库产品流：前端新增 ProductResolver（扫码/文字/拍照 → `/ai/resolve-product` →
  候选确认 → 入库），接入仓库入库窗口与商品中心；后端视觉输出改为结构化 JSON 解析后二次匹配。
- Market Quote/Event 去重加入 `product_id`：多个 SKU 追踪同一外部符号时互不串货。
- AI Provider 配置显式化：未知 Provider 直接报错；`openai` 缺 Key 返回显式 disabled Provider，
  不再无声退回 Demo。
- 日期口径统一 `COALESCE(line.required_at, order.required_at)` 与
  `COALESCE(line.expected_at, po.expected_at)`（需求与在途两处），行级日期优先。
- 知识文档详情按角色校验 OWNER scope；维修 `fault_record_id` 必须属于当前组织与当前设备。
- Playwright 加入 GitHub Actions（独立 E2E Job）；README 测试计数更新。
- 当前后端测试 79 项全通过（本轮新增 8 项），前端构建/测试与 E2E 待最终验证。

## 第五轮审计修复（过期批次 / 阈值一致性 / 价格账唯一路径 / 语义与边界）

- P0 过期批次：`expired_lot_quantity()` 进入健康可用量计算与 `EXPIRY_RISK`（已过期 CRITICAL）；
  `issue_stock` / 订单履约消费批次时排除 `expires_at < now`，且可用校验扣除过期量，过期库存不可出库。
- P0 呆滞阈值：`DORMANT_STOCK` 使用 `health_dormant_days`（30）而非写死 90 天，60 天前出过货即进入呆滞。
- P0 目标售价唯一写路径：Product 创建/更新同步写入 `TARGET_SELL_PRICE` 快照（价格账唯一真相）。
- P0/P1 汇率语义：`MarketQuote` 增加 `unit/basis`；`open_er_api` 标记 `unit=CNY, basis=FX`，
  UI 明确显示“汇率参考（外汇环境）”，`PRICE_PRESSURE` 只在可比口径（非 FX、单位一致/未指定）计算。
- P1 跨仓领料：新增 `allocate_issue()` 通用跨仓可用库存分配器，设备维修备件按默认仓优先逐仓扣减。
- P1 设备诊断只检索每个文档最新版本，旧 SOP/旧手册不再混入证据。
- P1 权限枚举：`access_scope` 改为 `Literal["ORG","OWNER"]` + DB CheckConstraint；
  知识文档实体关联（PRODUCT/EQUIPMENT/WAREHOUSE/SUPPLIER）校验组织归属，杜绝跨企业脏关联。
- P1 订单日期口径统一：列表逾期/交付期限筛选与 Dashboard `orders_due/upcoming` 使用
  `COALESCE(line.required_at, order.required_at)`（行级优先）。
- P1 ATP：同一商品的 incoming 按截止时间顺序分配，订单级风险不再被多单重复“借用”。
- P2 Inventory 多仓列表：`incoming/health/last_receipt/...` 等商品级字段对所有 Warehouse 行一致展示；
  `Projected = Available + Incoming` 正式落地（单商品、列表、商品页、工作台）。
- P2 商品详情健康分改为只显示后端权威分；订单创建支持动态多 SKU 行；`/forecast/*` 增加 `market:read` 鉴权。
- 新增 11 项回归测试；E2E 新增智能出入库故事（扫码识别 → 确认入库 → 库存增加）。
- 当前后端测试 90 项全通过，前端构建/测试与 2 条 E2E 全部通过。

## 第六轮审计修复（并发 / 过期与预留三套真相 / 工作台口径 / 前端联动 / 语义收尾）

- P0 Health 并发：`inventory_alerts` 增加 `(org, product, alert_type) WHERE status='OPEN'` 部分唯一索引，
  `_upsert_alert` 改为 SAVEPOINT + IntegrityError 重取，GET 并发重算不再 MultipleResultsFound/500（并发测试 3 连发均 200）。
- P0 确认订单不可预留过期库存：confirm 校验与分配均扣除每仓过期量；只有过期库存时确认被拒。
- P0 预留覆盖三套真相统一：Health / Dashboard / 订单详情 / Workbench 的预留覆盖一律以“可售（未过期）库存”为上限，
  预留实物过期后重新打开 STOCKOUT_RISK 与 ORDER_FULFILLMENT_RISK（回归测试覆盖）。
- P0 工作台缺口口径：`shortage_7d` 改为 `unreserved_due - available - incoming`，不再重复扣已预留需求。
- P0 采购页“全部到货”：前端带 `lines` body 调用 receive；E2E 核心故事新增该按钮回归（不再 422）。
- P1 多仓列表语义：`/inventory` 返回 SKU 汇总行（`row_type=SKU`，携带全局 incoming/projected/health）
  与各仓库行（`row_type=WAREHOUSE`，只含本仓 available/expired/projected），不再把全局 Incoming 叠加到每行。
- P1 Market Mapping 校验商品组织归属（跨企业商品 404）。
- P1 目标售价清空：PATCH `target_sell_price: null` 写入 `CLEARED` 快照，`get_prices` 视为无目标价，消除双真相。
- P1 默认仓库/库位一致性：两者必须同仓；更新仓库时联动校验旧库位（409）。
- P1 Adjust 同步批次：盘亏按 FIFO 扣减 Lot 并逐 Lot 记流水，盘盈新建 ADJ Lot，Balance 与 Lot 不再分叉。
- P1 Lot 并发：`(org, product, warehouse, lot_code)` 唯一约束 + SAVEPOINT 重取；并发同批号入库仅产生一个 Lot；
  `get_balance_locked` 同样加并发保护。
- P1 AI 工具口径：库存 Tool 扣除过期量（含 `expired_qty`），市场 Tool 携带 `unit/basis`（FX 不再在 AI 层丢失）。
- P1 Dashboard：ATP 池改用全量在途（长订单可用 8 日后到货），市场异常旁路遵守 UOM/FX 可比规则。
- P2 集成事件支持 `expires_at`；`image_data_url` 限制 8MB（前后端）；Available 趋势更名为 `available_projected`
  并在 UI 注明“按当前预留推算”，不再冒充历史 Available。
- 新增 15 项回归测试；当前后端测试 105 项全通过，前端构建/测试与 2 条 E2E 通过。

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
- [x] 权限测试、核心库存/订单测试通过（pytest 105 项，含跨租户/权限绕过/批次边界/成本快照/多仓库/API Key scope/AI Tool scope/健康公式/跨仓预留/过期批次/ATP/实体归属/并发/预留覆盖回归）
- [x] Playwright 核心链路通过
- [x] CI 工作流已配置；本地等价检查（ruff/mypy/pytest/build/typecheck/lint/test）全绿，推送后由 GitHub Actions 验证
- [x] docs/PROGRESS.md 处于最终完成状态
- [x] README 可让新机器独立跑起来

## BLOCKERS

无。外部 Provider（市场、AI）按计划以明确标记的 Mock/Demo Provider 运行，接口与数据模型保持可替换；接入真实 Key 即可启用。

## BLOCKERS

无。
