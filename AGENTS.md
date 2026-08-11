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

## 最高优先级工程约束（不得降级）

- 不得以任何理由自行进行功能降级、范围缩水、架构降级或验收降级；不得把“必须”项改写成“可选/后续/TODO”后宣称完成。
- 不得用注释、空函数、hard-coded response、假成功状态代替核心实现；不得对已有功能 silent fallback 成低能力方案。
- 外部依赖缺失时：保留正式接口/数据模型/Provider 边界，使用**明确标记**的 Mock/Stub，且不得 Mock 核心业务逻辑；在 `docs/PROGRESS.md` 的 BLOCKERS 记录恢复条件。
- 未知配置（如未知 Market Provider 名称）必须显式报错（422/配置错误），禁止悄悄退回默认 Provider。
- Definition of Done 是完成合同：未完成项不得通过改文档、降测试、删条目或改措辞变成已完成。
- 新增业务规则必须补测试；安全/隔离相关修复必须补攻击型回归测试。
- 多仓库语义：同一 SKU 跨仓库时，查询/健康/工作台必须按 SKU 聚合，不得因多结果异常或随机取一行。
- AI Tool 必须遵循调用者 scope；API Key 的 scopes 必须真正执行，不能只存不查。

## Agent skills

### Issue tracker

GitHub Issues（`gh issue`）。见 `docs/agents/issue-tracker.md`。

### Triage labels

默认五标签：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文：根 `docs/CONTEXT.md` + `docs/DECISIONS.md`（ADR）。见 `docs/agents/domain.md`。
