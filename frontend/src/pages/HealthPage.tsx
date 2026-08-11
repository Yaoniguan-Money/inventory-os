import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api.ts'
import { fmtDate } from '../lib/format.ts'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  ProductLink,
  Spinner,
  statusTone,
} from '../components/ui.tsx'

export default function HealthPage() {
  const [explainId, setExplainId] = useState<string | null>(null)
  const overview = useQuery({
    queryKey: ['health'],
    queryFn: () => api.get<Record<string, unknown>>('/health/overview'),
  })
  const alerts = useQuery({
    queryKey: ['health', 'alerts'],
    queryFn: () =>
      api.get<
        Array<{
          id: string
          product_id: string
          alert_type: string
          severity: string
          status: string
          title: string
          evidence_json: Record<string, unknown>
          opened_at: string
        }>
      >('/health/alerts?status=OPEN'),
  })
  const explain = useMutation({
    mutationFn: (id: string) => api.post<{ explanation: string }>(`/ai/explain-alert/${id}`),
    onSuccess: (_data, id) => setExplainId(id),
  })

  const products = overview.data?.products as
    | Array<{ product_id: string; sku: string; name: string; score: number; alerts: unknown[] }>
    | undefined

  return (
    <div>
      <PageHeader
        title="风险中心"
        description="确定性规则生成的库存健康告警与可解释分数"
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card>
          <div className="text-xs text-slate-400">组织健康分</div>
          <div className="tabular mt-1 text-2xl font-semibold text-emerald-300">
            {String(overview.data?.org_score ?? '—')}
          </div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">开放告警</div>
          <div className="tabular mt-1 text-2xl font-semibold text-red-400">
            {String(overview.data?.open_alert_count ?? 0)}
          </div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">严重级别分布</div>
          <div className="mt-1 text-sm text-slate-300">
            {JSON.stringify(overview.data?.by_severity ?? {})}
          </div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">规则类型分布</div>
          <div className="mt-1 text-sm text-slate-300">{JSON.stringify(overview.data?.by_type ?? {})}</div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="各商品健康分">
          {overview.isLoading ? (
            <Spinner />
          ) : (
            <div className="space-y-2">
              {(products ?? []).map((p) => (
                <div key={p.product_id} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
                  <ProductLink id={p.product_id}>
                    {p.sku} · {p.name}
                  </ProductLink>
                  <div className="flex items-center gap-2">
                    <span className="tabular text-sm">{p.score}</span>
                    <Badge tone={p.score < 70 ? 'red' : p.score < 90 ? 'amber' : 'green'}>
                      {p.alerts.length} 告警
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="开放告警">
          {alerts.isLoading ? (
            <Spinner />
          ) : !alerts.data?.length ? (
            <EmptyState text="暂无开放告警" />
          ) : (
            <div className="space-y-2">
              {alerts.data.map((a) => (
                <div key={a.id} className="rounded-lg border border-red-500/20 bg-red-500/5 p-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm text-red-300">{a.title}</div>
                    <Badge tone={statusTone(a.severity)}>{a.severity}</Badge>
                  </div>
                  <div className="mt-1 text-xs text-slate-400">
                    {a.alert_type} · {fmtDate(a.opened_at)}
                  </div>
                  <div className="mt-1 text-[11px] text-slate-500">{JSON.stringify(a.evidence_json)}</div>
                  <Button variant="ghost" className="mt-2 text-xs" onClick={() => explain.mutate(a.id)}>
                    为什么？
                  </Button>
                  {explainId === a.id && explain.data && (
                    <div className="mt-2 rounded-lg bg-slate-800/70 p-3 text-sm text-slate-200">
                      {explain.data.explanation}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
