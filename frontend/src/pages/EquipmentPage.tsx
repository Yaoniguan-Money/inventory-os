import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
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
  statusTone,
} from '../components/ui.tsx'

export default function EquipmentPage() {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [form, setForm] = useState({
    asset_code: '',
    name: '',
    model: '',
    location: '',
    production_line: '',
  })

  const equipment = useQuery({
    queryKey: ['equipment'],
    queryFn: () =>
      api.get<
        Array<{
          id: string
          asset_code: string
          name: string
          model: string | null
          location: string | null
          status: string
          next_maintenance_at: string | null
        }>
      >('/equipment'),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      api.post('/equipment', {
        asset_code: form.asset_code,
        name: form.name,
        model: form.model || null,
        location: form.location || null,
        production_line: form.production_line || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['equipment'] })
      setCreateOpen(false)
    },
    onError: setError,
  })

  return (
    <div>
      <PageHeader
        title="设备维护"
        description="设备档案、点检、故障、维修与知识检索辅助"
        action={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-1 inline h-4 w-4" /> 新增设备
          </Button>
        }
      />
      <ErrorNote error={error} />
      <Card className="p-0">
        {equipment.isLoading ? (
          <Spinner />
        ) : !equipment.data?.length ? (
          <EmptyState text="暂无设备" />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                <th className="px-4 py-2.5">资产编码</th>
                <th className="px-4 py-2.5">名称</th>
                <th className="px-4 py-2.5">型号</th>
                <th className="px-4 py-2.5">位置</th>
                <th className="px-4 py-2.5">下次维护</th>
                <th className="px-4 py-2.5">状态</th>
              </tr>
            </thead>
            <tbody>
              {equipment.data.map((e) => (
                <tr key={e.id} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                  <td className="px-4 py-2.5">
                    <Link to={`/equipment/${e.id}`} className="font-medium text-sky-300 hover:underline">
                      {e.asset_code}
                    </Link>
                  </td>
                  <td className="px-4 py-2.5 text-slate-200">{e.name}</td>
                  <td className="px-4 py-2.5 text-slate-400">{e.model ?? '—'}</td>
                  <td className="px-4 py-2.5 text-slate-400">{e.location ?? '—'}</td>
                  <td className="px-4 py-2.5 text-slate-400">{e.next_maintenance_at ?? '—'}</td>
                  <td className="px-4 py-2.5">
                    <Badge tone={statusTone(e.status)}>{e.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="新增设备">
        <div className="space-y-3">
          <input
            placeholder="资产编码 *（如 E-07）"
            value={form.asset_code}
            onChange={(e) => setForm({ ...form, asset_code: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <input
            placeholder="名称 *"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <input
            placeholder="型号"
            value={form.model}
            onChange={(e) => setForm({ ...form, model: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <div className="grid grid-cols-2 gap-2">
            <input
              placeholder="位置"
              value={form.location}
              onChange={(e) => setForm({ ...form, location: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
            />
            <input
              placeholder="产线"
              value={form.production_line}
              onChange={(e) => setForm({ ...form, production_line: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
            />
          </div>
          <Button
            className="w-full"
            disabled={!form.asset_code || !form.name || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            创建
          </Button>
        </div>
      </Modal>
    </div>
  )
}
