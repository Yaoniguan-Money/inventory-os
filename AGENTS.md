# AGENTS.md

## 项目级硬规则

- 先读 `docs/CONTEXT.md` / `docs/DECISIONS.md` / `docs/PROGRESS.md`，再动手。
- 不修改已经确定的产品边界，除非用户明确要求。
- 数据库业务状态优先，AI 不作为账本。
- 所有库存写入必须经过 Warehouse Service。
- 所有订单履约必须经过 Order/Fulfillment Service。
- 所有金额使用 Decimal（NUMERIC），禁止 float。
- 所有时间内部存 UTC。
- 所有组织数据必须 organization-scoped，禁止跨企业访问。
- 不允许核心 ledger hard delete（StockMovement / EventLog / AuditLog 只追加）。
- 新增业务规则必须补测试；修 Bug 先写复现，再修复，再加 regression test。
- 前端服务端状态使用 TanStack Query；SSE 只做 invalidate trigger，不作为唯一真相。
- GSAP 动效必须尊重 `prefers-reduced-motion`。
- 不提交 secrets（API Key / Token / Cookie / 密码只进 `.env`，仓库只提交 `.env.example`）。
- 每个阶段完成后更新 `docs/PROGRESS.md`。
- 仓库级 Skills 位于 `.agents/skills/`，按任务调用，不要一次性全部塞进上下文。

## Agent skills

### Issue tracker

GitHub Issues（`gh issue`）。见 `docs/agents/issue-tracker.md`。

### Triage labels

默认五标签：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文：根 `docs/CONTEXT.md` + `docs/DECISIONS.md`（ADR）。见 `docs/agents/domain.md`。
