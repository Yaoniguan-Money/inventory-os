import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/api.ts'
import { fmtDate, fmtMoney, fmtQty } from '../lib/format.ts'
import { Badge, Card, GsapNumber, PageHeader, Spinner, statusTone } from '../components/ui.tsx'

interface DashboardData {
  inventory_value: string
  on_hand_units: string
  sku_count: number
  reserved_units: string
  orders_due: number
  at_risk_orders: number
  health_score: number
  health_by_severity: Record<string, number>
  health_by_type: Record<string, number>
  pressure_7d: Array<{
    product_id: string
    sku: string
    name: string
    due_demand: string
    available: string
    incoming: string
    shortage: string
  }>
  upcoming_orders: Array<{
    id: string
    order_no: string
    customer_name: string
    required_at: string | null
    status: string
    remaining_total: string
  }>
  market_anomalies: Array<{
    product_id: string
    sku: string
    name: string
    title: string
    evidence: Record<string, unknown>
  }>
  recent_events: Array<{
    sequence_id: number
    event_type: string
    occurred_at: string
    payload: Record<string, unknown>
  }>
}

export default function DashboardPage() {
  const data = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api.get<DashboardData>('/dashboard'),
  })

  if (data.isLoading) return <Spinner />
  const d = data.data!

  return (
    <div>
      <PageHeader title="经营驾驶舱" description="库存金额、订单压力、履约风险与市场异常的实时视图" />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Card>
          <div className="text-xs text-slate-400">Inventory Value</div>
          <div className="tabular mt-1 text-2xl font-semibold text-slate-100">
            <GsapNumber value={Number(d.inventory_value)} format={(v) => fmtMoney(v)} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">按移动平均成本估值</div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">On Hand Units</div>
          <div className="tabular mt-1 text-2xl font-semibold text-slate-100">
            <GsapNumber value={Number(d.on_hand_units)} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">{d.sku_count} 个 SKU 有库存</div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">Reserved Units</div>
          <div className="tabular mt-1 text-2xl font-semibold text-amber-300">
            <GsapNumber value={Number(d.reserved_units)} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">已被订单占用</div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">Orders Due</div>
          <div className="tabular mt-1 text-2xl font-semibold text-slate-100">
            <GsapNumber value={d.orders_due} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">未来 7 日（含逾期）</div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">At-Risk Orders</div>
          <div className="tabular mt-1 text-2xl font-semibold text-red-400">
            <GsapNumber value={d.at_risk_orders} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">剩余量超过可用+在途</div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">Health Score</div>
          <div className="tabular mt-1 text-2xl font-semibold text-emerald-300">
            <GsapNumber value={d.health_score} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">组织健康分 / 100</div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="未来 7 日订单压力">
          {d.pressure_7d.length ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                  <th className="py-2">SKU</th>
                  <th className="py-2 text-right">需求</th>
                  <th className="py-2 text-right">可用</th>
                  <th className="py-2 text-right">在途</th>
                  <th className="py-2 text-right">缺口</th>
                </tr>
              </thead>
              <tbody>
                {d.pressure_7d.map((p) => (
                  <tr key={p.product_id} className="border-t border-slate-800/60">
                    <td className="py-2">
                      <Link to={`/products/${p.product_id}`} className="text-sky-300 hover:underline">
                        {p.sku} · {p.name}
                      </Link>
                    </td>
                    <td className="tabular py-2 text-right">{fmtQty(p.due_demand)}</td>
                    <td className="tabular py-2 text-right">{fmtQty(p.available)}</td>
                    <td className="tabular py-2 text-right">{fmtQty(p.incoming)}</td>
                    <td className="tabular py-2 text-right text-red-400">{fmtQty(p.shortage)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="py-6 text-center text-sm text-slate-500">未来 7 日无库存缺口</div>
          )}
        </Card>

        <Card title="即将交付订单" action={<Link to="/orders" className="text-xs text-sky-300">全部 →</Link>}>
          {d.upcoming_orders.length ? (
            <div className="space-y-1.5">
              {d.upcoming_orders.map((o) => (
                <div key={o.id} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
                  <div className="min-w-0">
                    <Link to={`/orders/${o.id}`} className="text-sm text-sky-300 hover:underline">
                      {o.order_no}
                    </Link>
                    <div className="text-xs text-slate-500">{o.customer_name}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="tabular text-xs text-slate-400">{fmtDate(o.required_at)}</span>
                    <span className="tabular text-xs text-slate-300">{fmtQty(o.remaining_total)}</span>
                    <Badge tone={statusTone(o.status)}>{o.status}</Badge>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-6 text-center text-sm text-slate-500">暂无进行中订单</div>
          )}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="市场价格异常">
          {d.market_anomalies.length ? (
            <div className="space-y-2">
              {d.market_anomalies.map((m) => (
                <div key={`${m.product_id}-${m.title}`} className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
                  <div className="text-sm text-amber-300">
                    <Link to={`/products/${m.product_id}`} className="hover:underline">
                      {m.sku} · {m.name}
                    </Link>{' '}
                    — {m.title}
                  </div>
                  <div className="mt-1 text-xs text-slate-400">{JSON.stringify(m.evidence)}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-6 text-center text-sm text-slate-500">未发现市场价格异常</div>
          )}
        </Card>

        <Card title="库存健康分布与最新事件">
          <div className="flex h-24 items-end gap-3">
            {Object.entries(d.health_by_severity).map(([severity, count]) => (
              <div key={severity} className="flex flex-1 flex-col items-center gap-1">
                <span className="tabular text-xs text-slate-300">{count}</span>
                <div
                  className="w-full rounded-t-md"
                  style={{
                    height: `${Math.max(6, count * 14)}px`,
                    background:
                      severity === 'CRITICAL' || severity === 'HIGH'
                        ? 'rgba(248,113,113,.7)'
                        : severity === 'MEDIUM'
                          ? 'rgba(251,191,36,.7)'
                          : 'rgba(148,163,184,.5)',
                  }}
                />
                <span className="text-[10px] text-slate-500">{severity}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 space-y-1 border-t border-slate-800 pt-3">
            {d.recent_events.map((e) => (
              <div key={e.sequence_id} className="flex items-start gap-2 text-xs">
                <Badge tone={statusTone('CONFIRMED')}>{e.event_type}</Badge>
                <span className="min-w-0 flex-1 truncate text-slate-400">
                  {JSON.stringify(e.payload).slice(0, 100)}
                </span>
                <span className="tabular shrink-0 text-slate-600">{fmtDate(e.occurred_at)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
