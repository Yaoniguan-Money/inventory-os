import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/api.ts'
import { fmtDate } from '../lib/format.ts'
import { Badge, Card, GsapNumber, PageHeader, Spinner, statusTone } from '../components/ui.tsx'

interface HealthOverview {
  org_score: number
  open_alert_count: number
  by_severity: Record<string, number>
  by_type: Record<string, number>
  products: Array<{
    product_id: string
    sku: string
    name: string
    score: number
    alerts: Array<{ alert_type: string; severity: string; title: string }>
  }>
}

interface EventItem {
  sequence_id: number
  event_type: string
  occurred_at: string
  payload: Record<string, unknown>
}

export default function DashboardPage() {
  const health = useQuery({
    queryKey: ['dashboard', 'health'],
    queryFn: () => api.get<HealthOverview>('/health/overview'),
  })
  const inventory = useQuery({
    queryKey: ['dashboard', 'inventory'],
    queryFn: () => api.get<Array<Record<string, string>>>('/inventory'),
  })
  const orders = useQuery({
    queryKey: ['dashboard', 'orders'],
    queryFn: () => api.get<Array<Record<string, unknown>>>('/orders'),
  })
  const events = useQuery({
    queryKey: ['dashboard', 'events'],
    queryFn: () => api.get<EventItem[]>('/events?limit=12'),
  })

  if (health.isLoading || inventory.isLoading || orders.isLoading) return <Spinner />

  const onHand = inventory.data?.reduce((s, r) => s + Number(r.on_hand ?? 0), 0) ?? 0
  const reserved = inventory.data?.reduce((s, r) => s + Number(r.reserved ?? 0), 0) ?? 0
  const ordersDue =
    orders.data?.filter((o) => ['CONFIRMED', 'PARTIAL'].includes(String(o.status))).length ?? 0
  const atRisk =
    health.data?.products.filter((p) => p.score < 80).length ?? 0

  return (
    <div>
      <PageHeader
        title="经营驾驶舱"
        description="库存、订单、市场与风险的一体化视图"
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Card>
          <div className="text-xs text-slate-400">Inventory Value</div>
          <div className="tabular mt-1 text-2xl font-semibold text-slate-100">
            <GsapNumber value={onHand} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">On Hand 总件数</div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">On Hand SKU Count</div>
          <div className="tabular mt-1 text-2xl font-semibold text-slate-100">
            <GsapNumber value={inventory.data?.length ?? 0} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">有库存的 SKU</div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">Reserved Units</div>
          <div className="tabular mt-1 text-2xl font-semibold text-amber-300">
            <GsapNumber value={reserved} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">已被订单占用</div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">Orders Due</div>
          <div className="tabular mt-1 text-2xl font-semibold text-slate-100">
            <GsapNumber value={ordersDue} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">进行中的订单</div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">At-Risk Orders</div>
          <div className="tabular mt-1 text-2xl font-semibold text-red-400">
            <GsapNumber value={atRisk} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">健康分 &lt; 80 的 SKU</div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">Health Score</div>
          <div className="tabular mt-1 text-2xl font-semibold text-emerald-300">
            <GsapNumber value={health.data?.org_score ?? 100} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">组织健康分 / 100</div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="高风险 SKU">
          {health.data?.products.filter((p) => p.alerts.length > 0).length ? (
            <div className="space-y-2">
              {health.data.products
                .filter((p) => p.alerts.length > 0)
                .slice(0, 6)
                .map((p) => (
                  <Link
                    key={p.product_id}
                    to={`/products/${p.product_id}`}
                    className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2 hover:border-slate-700"
                  >
                    <div>
                      <div className="text-sm font-medium text-slate-200">
                        {p.sku} · {p.name}
                      </div>
                      <div className="text-xs text-slate-500">
                        {p.alerts.map((a) => a.title).join('；')}
                      </div>
                    </div>
                    <Badge tone={p.score < 70 ? 'red' : 'amber'}>{p.score}</Badge>
                  </Link>
                ))}
            </div>
          ) : (
            <div className="py-6 text-center text-sm text-slate-500">暂无高风险 SKU</div>
          )}
        </Card>

        <Card title="最新事件时间线">
          <div className="space-y-1.5">
            {events.data?.map((e) => (
              <div key={e.sequence_id} className="flex items-start gap-2 text-xs">
                <Badge tone={statusTone(e.event_type.split('.')[0] === 'health' ? 'OPEN' : 'CONFIRMED')}>
                  {e.event_type}
                </Badge>
                <div className="min-w-0 flex-1 truncate text-slate-400">
                  {JSON.stringify(e.payload).slice(0, 120)}
                </div>
                <span className="tabular shrink-0 text-slate-600">{fmtDate(e.occurred_at)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="库存健康分布">
          <div className="flex h-32 items-end gap-2">
            {Object.entries(health.data?.by_severity ?? {}).map(([severity, count]) => (
              <div key={severity} className="flex flex-1 flex-col items-center gap-1">
                <div className="tabular text-sm text-slate-300">{count}</div>
                <div
                  className="w-full rounded-t-md"
                  style={{
                    height: `${Math.max(8, Number(count) * 18)}px`,
                    background:
                      severity === 'CRITICAL' || severity === 'HIGH'
                        ? 'rgba(248,113,113,.7)'
                        : severity === 'MEDIUM'
                          ? 'rgba(251,191,36,.7)'
                          : 'rgba(148,163,184,.5)',
                  }}
                />
                <div className="text-[10px] text-slate-500">{severity}</div>
              </div>
            ))}
          </div>
        </Card>
        <Card title="即将交付订单" action={<Link to="/orders" className="text-xs text-sky-300">全部 →</Link>}>
          <div className="space-y-1.5">
            {orders.data?.slice(0, 6).map((o) => (
              <div key={String(o.id)} className="flex items-center justify-between text-sm">
                <Link to={`/orders/${o.id}`} className="text-sky-300 hover:underline">
                  {String(o.order_no)}
                </Link>
                <div className="flex items-center gap-2">
                  <Badge tone={statusTone(String(o.status))}>{String(o.status)}</Badge>
                </div>
              </div>
            ))}
            {!orders.data?.length && (
              <div className="py-4 text-center text-sm text-slate-500">暂无订单</div>
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}
