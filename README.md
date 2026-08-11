# InventoryOS

面向中小制造企业的智能经营系统：以商品 / SKU 与设备资产为核心，把仓库库存、订单履约、采购在途、企业成本与售价、外部市场行情、库存健康、设备维护和企业知识统一到同一个实时经营系统中。

> 业务做具体，架构做通用；数据库是真相，业务服务负责计算，AI 负责识别、查询与解释。

## 技术栈

- Monorepo：`backend/`（Python 3.11+ · FastAPI · SQLAlchemy 2.x · Alembic · PostgreSQL · asyncpg）
- `frontend/`（React 19 · TypeScript · Vite · Tailwind CSS v4 · TanStack Query · React Router · GSAP · ECharts）
- 持久事件流：`EventLog` + SSE after cursor（服务重启/断线可恢复）
- Provider 边界：AI / Market / Forecast 均可替换；缺真实 Key 时使用明确标记的 Demo/Mock Provider
- 测试：pytest（48 项后端）、Vitest（前端）、Playwright（核心链路 E2E）、GitHub Actions CI

## 快速开始（Docker）

```bash
cp .env.example .env
docker compose up --build
```

- 前端：http://localhost:5173
- 后端 API / OpenAPI：http://localhost:8000/docs
- 默认 Demo 用户：`admin@inventoryos.dev` / `Demo@12345`

首次启动后执行：

```bash
docker compose exec backend uv run alembic upgrade head
docker compose exec backend uv run python -m app.scripts.seed
```

## 本地开发（不使用 Docker 前端/后端镜像）

前提：`uv`、Node 22+、Docker（仅用于 PostgreSQL）。

```bash
# 1. PostgreSQL
docker compose up -d postgres

# 2. 后端
cd backend
cp ../.env.example ../.env
uv sync
uv run alembic upgrade head
uv run python -m app.scripts.seed
uv run uvicorn app.main:app --reload

# 3. 前端（另开终端）
cd frontend
npm install
npm run dev
```

## 重置数据库

```bash
make reset            # docker compose down -v + migrate + seed
# 或手动：
docker compose down -v
docker compose up -d postgres
cd backend && uv run alembic upgrade head && uv run python -m app.scripts.seed
```

## 运行测试

```bash
# 后端（需要 PostgreSQL 在 5433 端口，测试库 inventory_os_test 自动建表）
cd backend
uv run pytest
uv run ruff check .
uv run mypy app

# 前端
cd frontend
npm run test -- --run
npm run lint
npm run typecheck
npm run build

# E2E（自动重建 inventory_os_e2e 数据库并启动前后端）
cd frontend
npx playwright test
```

## 配置 AI Provider

默认 `AI_PROVIDER=demo`（无 Key 可运行，回答基于系统内证据做确定性摘要）。

接入 OpenAI 兼容接口时，在 `.env` 配置：

```dotenv
AI_PROVIDER=openai
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=sk-...
AI_MODEL=gpt-4o-mini
```

AI 权限边界：所有工具只读；不直接修改库存/订单/价格账；写操作必须由人通过普通业务 API 确认。

## 配置 Market Provider

默认 `MARKET_PROVIDER=open_er_api`：开箱即用接入真实国际汇率参考价（open.er-api.com，无需 Key），
把映射的外部符号（如 `USD`）换算为 CNY/单位保存为国际市场参考价。

其它 Provider 按映射选择（不同 SKU 可挂不同数据源）：

- `mock`：明确标记的 Demo Provider（国内演示行情）。
- `http_json`：`MARKET_HTTP_URL=<url>`、`MARKET_HTTP_TOKEN=<token>`，期望 JSON 响应包含 `symbols` 数组。
- `rss`：`MARKET_RSS_URL=<feed-url>`，条目自动作为 MarketEvent 接入。

每条外部行情保存来源、更新时间、币种、地区；系统不输出未经证实的未来价格预测。

## 产品边界

包含：商品/仓库/批次/出入库、订单预留与履约、采购在途、企业价格快照、市场行情、库存健康规则与告警、设备维护、企业知识库、员工助手、开放集成（API Key + HTTP/JSON + SSE）。

不包含（V1）：机械臂/AGV/PLC 控制、价格与需求预测（仅保留 ForecastProvider 契约并明确 disabled）、面向客户客服助手、自动下单采购、财务总账、发票税务。

## 文档

- `docs/CONTEXT.md` 领域上下文
- `docs/DECISIONS.md` 架构决策
- `docs/API.md` API 清单
- `docs/DEMO.md` Demo 剧本
- `docs/PROGRESS.md` 实施进度
