# Architecture Decision Records

## ADR-001: 数据库是真相，事件流持久化

- 状态：已采纳
- 决定：所有核心业务状态由 PostgreSQL + 确定性业务规则维护；业务事件写入持久 `EventLog`（`sequence_id BIGSERIAL` 为游标），SSE 通过 `after=<sequence_id>` 恢复。
- 理由：支持多 worker、服务重启与断线恢复，不依赖进程内内存。

## ADR-002: 金额一律 Decimal/NUMERIC

- 状态：已采纳
- 决定：所有金额列使用 `NUMERIC(18,4)`，Python 侧 Pydantic/SQLAlchemy 使用 `Decimal`。
- 理由：避免 float 误差污染成本与价格账。

## ADR-003: 库存账户模型

- 状态：已采纳
- 决定：`InventoryBalance(on_hand, reserved, version)` 作为事务投影；`InventoryLot` 是批次真相；`StockMovement` 只追加；`available = on_hand - reserved`；禁止负库存与超预留。
- 理由：满足"一个业务动作只发生一次"和审计要求。

## ADR-004: 一个履约动作一个事务

- 状态：已采纳
- 决定：订单确认/部分交付/取消在单个数据库事务内更新 OrderLine、Reservation、InventoryBalance、StockMovement、Delivery、EventLog、AuditLog。
- 理由：避免前端或人工二次扣减造成状态漂移。

## ADR-005: Provider 边界与 Mock

- 状态：已采纳
- 决定：AI、Market、Forecast 全部走 Provider 接口；无真实 Key 时使用明确标记的 Mock Provider（`MockMarketProvider`、`DemoAIProvider`、`DisabledForecastProvider`），核心业务不 Mock。
- 理由：真实能力可替换接入，且无 Key 时系统仍完整可运行。

## ADR-006: 跨组织隔离在数据层

- 状态：已采纳
- 决定：所有业务查询强制 `organization_id` 作用域；角色权限通过 scope 判定，不在业务代码中散落 `if role == ...`。
- 理由：防止跨企业数据泄漏只依赖前端。

## ADR-007: RBAC scope 模型

- 状态：已采纳
- 决定：角色 OWNER/ADMIN/MANAGER/WAREHOUSE/SALES/PURCHASING/VIEWER 映射到细粒度 scope（如 `inventory:receive`、`orders:confirm`），依赖注入 `RequireScope` 校验。
- 理由：权限可组合、可扩展、可测试。

## ADR-008: Skills 仓库级共享

- 状态：已采纳
- 决定：GSAP 与 Matt Pocock engineering skills 复制到 `.agents/skills/`，随仓库共享；不改第三方内容。
- 理由：团队/Codex 会话切换后仍可发现同一组 skills。
