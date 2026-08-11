import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api.ts'
import { fmtDate } from '../lib/format.ts'
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  Modal,
  PageHeader,
  Spinner,
} from '../components/ui.tsx'

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [created, setCreated] = useState<string | null>(null)
  const [form, setForm] = useState({ name: '', scopes: '' })

  const keys = useQuery({
    queryKey: ['api-keys'],
    queryFn: () =>
      api.get<
        Array<{
          id: string
          name: string
          prefix: string
          scopes: string[]
          last_used_at: string | null
          revoked_at: string | null
          created_at: string
        }>
      >('/integrations/api-keys'),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      api.post<{ api_key: string }>('/integrations/api-keys', {
        name: form.name,
        scopes: form.scopes
          ? form.scopes.split(',').map((s) => s.trim()).filter(Boolean)
          : ['inventory:receive'],
      }),
    onSuccess: (data) => {
      setCreated(data.api_key)
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
    onError: setError,
  })
  const revokeMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/integrations/api-keys/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['api-keys'] }),
    onError: setError,
  })

  return (
    <div>
      <PageHeader
        title="集成与设置"
        description="API Key 管理、外部系统接入与开放接口"
      />
      <ErrorNote error={error} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="外部 API Key"
          action={<Button onClick={() => setCreateOpen(true)}>新建 Key</Button>}
        >
          {keys.isLoading ? (
            <Spinner />
          ) : !keys.data?.length ? (
            <div className="py-6 text-center text-sm text-slate-500">暂无 API Key</div>
          ) : (
            <div className="space-y-2">
              {keys.data.map((k) => (
                <div key={k.id} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
                  <div>
                    <div className="flex items-center gap-2 text-sm text-slate-200">
                      {k.name}
                      <Badge tone={k.revoked_at ? 'red' : 'green'}>
                        {k.revoked_at ? '已撤销' : '有效'}
                      </Badge>
                    </div>
                    <div className="text-xs text-slate-500">
                      {k.prefix} · {k.scopes.join(', ')} · 创建于 {fmtDate(k.created_at)}
                    </div>
                  </div>
                  {!k.revoked_at && (
                    <Button variant="danger" className="text-xs" onClick={() => revokeMutation.mutate(k.id)}>
                      撤销
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card title="开放能力">
          <div className="space-y-2 text-sm text-slate-300">
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
              <code className="text-sky-300">POST /api/v1/integrations/events</code>
              <div className="mt-1 text-xs text-slate-500">ERP / MES / PDA / 硬件网关 HTTP/JSON 接入（幂等）</div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
              <code className="text-sky-300">GET /api/v1/events/stream</code>
              <div className="mt-1 text-xs text-slate-500">SSE 实时事件流（after cursor 断点恢复）</div>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
              <code className="text-sky-300">/api/v1/* + /docs</code>
              <div className="mt-1 text-xs text-slate-500">REST API 与 OpenAPI 文档</div>
            </div>
          </div>
        </Card>
      </div>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="新建 API Key">
        {created ? (
          <div className="space-y-3">
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3">
              <div className="mb-1 text-xs text-emerald-300">请立即保存，此密钥只显示一次：</div>
              <code className="break-all text-sm text-emerald-200">{created}</code>
            </div>
            <Button
              className="w-full"
              onClick={() => {
                setCreated(null)
                setCreateOpen(false)
                setForm({ name: '', scopes: '' })
              }}
            >
              完成
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            <input
              placeholder="名称（如 erp-bridge）"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
            />
            <input
              placeholder="权限（逗号分隔，默认 inventory:receive）"
              value={form.scopes}
              onChange={(e) => setForm({ ...form, scopes: e.target.value })}
              className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
            />
            <Button
              className="w-full"
              disabled={!form.name || createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              创建
            </Button>
          </div>
        )}
      </Modal>
    </div>
  )
}
