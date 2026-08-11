# InventoryOS 项目上下文

## 一句话产品定义

InventoryOS 是一个面向中小制造企业、以 SKU 和设备资产为核心，将库存、订单履约、采购在途、企业成本与售价、外部市场行情、库存健康、设备维护和企业知识统一到同一个实时经营系统中的智能运营底座。

## 核心原则

1. 一个 SKU 是产品中心：点进 SKU 能一路看到库存、批次、订单、履约、采购、成本、售价、市场、风险、时间线。
2. 一个业务动作只发生一次：履约事务一次完成 StockMovement → Delivery → Reservation → InventoryBalance → EventLog。
3. "库存 1000" 不是答案：必须区分 On Hand / Reserved / Available / Incoming / Projected。
4. 市场行情只说有证据的事实：抓取、保存、展示、趋势、摘要；不宣称预测。
5. AI 是 Copilot，不是数据库：AI 可识别、查询、总结、解释、建议，不可自己算账或篡改账本。
6. 开放接口从第一天存在：ERP / MES / PDA / 扫码枪 / 硬件网关通过 Integration API + Provider + Event 接入。

## 核心领域术语

- Organization / User / Membership / Role：多租户与 RBAC。
- Product / SKU：商品中心，唯一约束 `(organization_id, sku)`。
- InventoryBalance：`on_hand / reserved` 事务投影，`available = on_hand - reserved`。
- InventoryLot：批次库存，临期检测与溯源的真相基础。
- StockMovement：库存流水，只追加不可删。
- SalesOrder / Reservation / Delivery：订单确认占用库存、部分履约、取消释放。
- PurchaseOrder / Incoming：采购在途；到货走正式 Receive 事务。
- InternalPriceSnapshot：企业价格快照（最近采购价 / 移动平均成本 / 目标售价 / 实际成交价）。
- MarketQuote / MarketEvent / ProductMarketMapping：外部行情与商品映射。
- InventoryAlert：确定性规则 + evidence_json 的健康告警。
- EventLog + SSE after cursor：持久事件流，可断点恢复。
- EquipmentAsset / FaultRecord / MaintenanceRecord：设备维护链路。
- KnowledgeDocument / Version / Chunk / EntityLink：企业内部知识库。
- ForecastProvider：V1 明确 disabled 的扩展位，禁止伪造预测。

## 架构约定

- 核心业务规则放 domain service，不放 route、不放 React、不放 LLM prompt。
- 数据库事务是唯一真相：库存、订单、事件、审计同一事务提交。
- 并发控制：行级锁（`SELECT ... FOR UPDATE`）+ 乐观锁版本号。
- 所有写操作按需写 AuditLog。
- Provider 抽象：`MarketDataProvider` / `AIFactory` / `ProductResolver` / `ForecastProvider`。

## 产品边界（V1 不做）

机械臂 / AGV / PLC 深度控制 / 价格需求预测 / 面向客户客服 / 自动下单采购 / 自动改价 / 财务总账 / 发票税务 / CRM / MES / ERP 全量 / 复杂运输 / 多币种核算 / AI 自主危险写操作。
