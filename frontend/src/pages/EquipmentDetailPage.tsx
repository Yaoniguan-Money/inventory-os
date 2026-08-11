import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api } from '../lib/api.ts'
import { fmtDate } from '../lib/format.ts'
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  PageHeader,
  Spinner,
  statusTone,
} from '../components/ui.tsx'

export default function EquipmentDetailPage() {
  const { equipmentId } = useParams()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<'faults' | 'maintenance' | 'diagnose'>('faults')
  const [error, setError] = useState<unknown>(null)
  const [diagnose, setDiagnose] = useState<Record<string, unknown> | null>(null)
  const [faultForm, setFaultForm] = useState({ fault_code: '', symptom: '', severity: 'MEDIUM' })

  const equipment = useQuery({
    queryKey: ['equipment', equipmentId],
    queryFn: () =>
      api.get<{
        id: string
        asset_code: string
        name: string
        model: string | null
        serial_number: string | null
        location: string | null
        status: string
      }>(`/equipment/${equipmentId}`),
  })
  const faults = useQuery({
    queryKey: ['equipment', equipmentId, 'faults'],
    queryFn: () =>
      api.get<Array<Record<string, unknown>>>(`/equipment/${equipmentId}/faults`),
  })
  const maintenance = useQuery({
    queryKey: ['equipment', equipmentId, 'maintenance'],
    queryFn: () =>
      api.get<Array<Record<string, unknown>>>(`/equipment/${equipmentId}/maintenance`),
  })

  const faultMutation = useMutation({
    mutationFn: () => api.post(`/equipment/${equipmentId}/faults`, faultForm),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['equipment'] })
      setFaultForm({ fault_code: '', symptom: '', severity: 'MEDIUM' })
    },
    onError: setError,
  })
  const diagnoseMutation = useMutation({
    mutationFn: () =>
      api.post<Record<string, unknown>>(`/equipment/${equipmentId}/diagnose`, {
        fault_code: faultForm.fault_code || null,
        symptom: faultForm.symptom,
      }),
    onSuccess: (data) => setDiagnose(data),
    onError: setError,
  })

  if (equipment.isLoading) return <Spinner />
  const data = equipment.data!

  return (
    <div>
      <PageHeader
        title={`${data.asset_code} · ${data.name}`}
        description={`${data.model ?? '无型号'} · ${data.location ?? '未定位'} · 序列号 ${data.serial_number ?? '—'}`}
        action={<Badge tone={statusTone(data.status)}>{data.status}</Badge>}
      />
      <ErrorNote error={error} />

      <div className="mb-4 flex gap-2">
        {(['faults', 'maintenance', 'diagnose'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-lg px-3 py-1.5 text-sm ${
              tab === t ? 'bg-sky-500/20 text-sky-300' : 'text-slate-400 hover:bg-slate-800'
            }`}
          >
            {{ faults: '故障记录', maintenance: '维修记录', diagnose: 'AI 诊断' }[t]}
          </button>
        ))}
      </div>

      {tab === 'faults' && (
        <Card title="故障记录">
          <div className="mb-3 grid grid-cols-3 gap-2">
            <input
              placeholder="错误码"
              value={faultForm.fault_code}
              onChange={(e) => setFaultForm({ ...faultForm, fault_code: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
            />
            <input
              placeholder="故障现象 *"
              value={faultForm.symptom}
              onChange={(e) => setFaultForm({ ...faultForm, symptom: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
            />
            <Button onClick={() => faultMutation.mutate()} disabled={!faultForm.symptom}>
              记录故障
            </Button>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="py-2">错误码</th>
                <th className="py-2">现象</th>
                <th className="py-2">严重度</th>
                <th className="py-2">状态</th>
                <th className="py-2">时间</th>
              </tr>
            </thead>
            <tbody>
              {(faults.data ?? []).map((f) => (
                <tr key={String(f.id)} className="border-t border-slate-800/60">
                  <td className="py-2 text-slate-300">{String(f.fault_code ?? '—')}</td>
                  <td className="py-2 text-slate-300">{String(f.symptom)}</td>
                  <td className="py-2">
                    <Badge tone={statusTone(String(f.severity))}>{String(f.severity)}</Badge>
                  </td>
                  <td className="py-2">
                    <Badge tone={statusTone(String(f.status))}>{String(f.status)}</Badge>
                  </td>
                  <td className="py-2 text-slate-400">{fmtDate(String(f.occurred_at))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {tab === 'maintenance' && (
        <Card title="维修记录">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="py-2">类型</th>
                <th className="py-2">描述</th>
                <th className="py-2">执行人</th>
                <th className="py-2 text-right">停机(分钟)</th>
                <th className="py-2">结果</th>
                <th className="py-2">时间</th>
              </tr>
            </thead>
            <tbody>
              {(maintenance.data ?? []).map((m) => (
                <tr key={String(m.id)} className="border-t border-slate-800/60">
                  <td className="py-2 text-slate-300">{String(m.maintenance_type)}</td>
                  <td className="py-2 text-slate-300">{String(m.description ?? '—')}</td>
                  <td className="py-2 text-slate-400">{String(m.performed_by ?? '—')}</td>
                  <td className="tabular py-2 text-right">{String(m.downtime_minutes ?? '—')}</td>
                  <td className="py-2">
                    <Badge tone={statusTone(String(m.result))}>{String(m.result)}</Badge>
                  </td>
                  <td className="py-2 text-slate-400">{fmtDate(String(m.performed_at))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {tab === 'diagnose' && (
        <Card title="AI 故障诊断（辅助判断）">
          <div className="mb-3 grid grid-cols-3 gap-2">
            <input
              placeholder="错误码"
              value={faultForm.fault_code}
              onChange={(e) => setFaultForm({ ...faultForm, fault_code: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
            />
            <input
              placeholder="故障现象 *"
              value={faultForm.symptom}
              onChange={(e) => setFaultForm({ ...faultForm, symptom: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
            />
            <Button onClick={() => diagnoseMutation.mutate()} disabled={!faultForm.symptom}>
              诊断
            </Button>
          </div>
          {diagnose && (
            <div className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <div>
                <div className="mb-1 text-sm font-medium text-slate-200">可能原因</div>
                {(diagnose.possible_causes as string[]).map((c) => (
                  <div key={c} className="text-sm text-slate-300">• {c}</div>
                ))}
              </div>
              <div>
                <div className="mb-1 text-sm font-medium text-slate-200">建议检查步骤</div>
                {(diagnose.recommended_steps as string[]).map((s, i) => (
                  <div key={s} className="text-sm text-slate-300">
                    {i + 1}. {s}
                  </div>
                ))}
              </div>
              <div>
                <div className="mb-1 text-sm font-medium text-slate-200">引用依据</div>
                {(diagnose.citations as Array<{ title: string; excerpt: string }>).map((c) => (
                  <div key={c.title} className="text-xs text-slate-400">
                    <span className="text-sky-300">{c.title}</span>：{c.excerpt}
                  </div>
                ))}
              </div>
              <div className="text-xs text-amber-300">{String(diagnose.disclaimer)}</div>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
