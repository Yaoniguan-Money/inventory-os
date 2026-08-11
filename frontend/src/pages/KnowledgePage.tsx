import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { api } from '../lib/api.ts'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Modal,
  PageHeader,
  Spinner,
} from '../components/ui.tsx'

export default function KnowledgePage() {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [form, setForm] = useState({
    title: '',
    document_type: 'SOP',
    access_scope: 'ORG',
    content: '',
  })

  const documents = useQuery({
    queryKey: ['knowledge'],
    queryFn: () =>
      api.get<Array<Record<string, unknown>>>('/knowledge/documents'),
  })
  const search = useQuery({
    queryKey: ['knowledge', 'search', query],
    queryFn: () =>
      api.post<{ hits: Array<Record<string, unknown>> }>('/knowledge/search', { query }),
    enabled: query.trim().length > 0,
  })

  const createMutation = useMutation({
    mutationFn: () => api.post('/knowledge/documents', form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge'] })
      setCreateOpen(false)
      setForm({ title: '', document_type: 'SOP', access_scope: 'ORG', content: '' })
    },
    onError: setError,
  })

  return (
    <div>
      <PageHeader
        title="企业知识库"
        description="手册、SOP、故障案例与内部问答（权限过滤 + 来源引用）"
        action={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-1 inline h-4 w-4" /> 新建文档
          </Button>
        }
      />
      <ErrorNote error={error} />

      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <Card title="文档列表">
          {documents.isLoading ? (
            <Spinner />
          ) : !documents.data?.length ? (
            <EmptyState text="暂无文档" />
          ) : (
            <div className="space-y-2">
              {documents.data.map((d) => (
                <div key={String(d.id)} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
                  <div>
                    <div className="text-sm text-slate-200">{String(d.title)}</div>
                    <div className="text-xs text-slate-500">
                      {String(d.document_type)} · {String(d.access_scope)}
                    </div>
                  </div>
                  <Badge tone="green">{String(d.status)}</Badge>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="知识检索">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入问题，如：A103 应该放哪个仓位？"
            className="mb-3 w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none focus:border-sky-500"
          />
          {query.trim() && (
            <div className="space-y-2">
              {(search.data?.hits ?? []).map((h, i) => (
                <div key={i} className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
                  <div className="text-sm font-medium text-sky-300">{String(h.document_title)}</div>
                  <div className="mt-1 text-xs text-slate-400">{String(h.excerpt)}</div>
                  <div className="mt-1 text-[11px] text-slate-600">匹配分 {String(h.score)}</div>
                </div>
              ))}
              {search.data && search.data.hits.length === 0 && (
                <div className="text-sm text-slate-500">无匹配结果</div>
              )}
            </div>
          )}
        </Card>
      </div>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="新建知识文档" wide>
        <div className="space-y-3">
          <input
            placeholder="标题 *"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <div className="grid grid-cols-2 gap-2">
            <select
              value={form.document_type}
              onChange={(e) => setForm({ ...form, document_type: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
            >
              {['SOP', 'MANUAL', 'FAQ', 'CASE', 'POLICY'].map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <select
              value={form.access_scope}
              onChange={(e) => setForm({ ...form, access_scope: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
            >
              <option value="ORG">组织可见</option>
              <option value="OWNER">仅管理层</option>
            </select>
          </div>
          <textarea
            placeholder="文档内容 *（自动分块并建立检索索引）"
            value={form.content}
            onChange={(e) => setForm({ ...form, content: e.target.value })}
            rows={8}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <Button
            className="w-full"
            disabled={!form.title || !form.content || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            创建
          </Button>
        </div>
      </Modal>
    </div>
  )
}
