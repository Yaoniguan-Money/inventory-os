import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api.ts'
import { fmtMoney } from '../lib/format.ts'
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

interface Product {
  id: string
  sku: string
  name: string
  category: string | null
  status: string
  unit: string
  target_sell_price: string | null
  barcode: string | null
}

export default function ProductsPage() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState({
    sku: '',
    name: '',
    category: '',
    unit: 'pcs',
    barcode: '',
    target_sell_price: '',
  })
  const [error, setError] = useState<unknown>(null)

  const products = useQuery({
    queryKey: ['products', search],
    queryFn: () => api.get<Product[]>(`/products?search=${encodeURIComponent(search)}`),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      api.post('/products', {
        sku: form.sku,
        name: form.name,
        category: form.category || null,
        unit: form.unit,
        barcode: form.barcode || null,
        target_sell_price: form.target_sell_price || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] })
      setCreateOpen(false)
      setForm({ sku: '', name: '', category: '', unit: 'pcs', barcode: '', target_sell_price: '' })
    },
    onError: setError,
  })

  return (
    <div>
      <PageHeader
        title="商品中心"
        description="SKU、批次、价格与市场跟踪"
        action={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-1 inline h-4 w-4" /> 新建商品
          </Button>
        }
      />
      <Card className="p-0">
        <div className="border-b border-slate-800 p-3">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索 SKU / 名称 / 条码"
            className="w-full max-w-sm rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none focus:border-sky-500"
          />
        </div>
        {products.isLoading ? (
          <Spinner />
        ) : !products.data?.length ? (
          <EmptyState text="暂无商品" />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                <th className="px-4 py-2.5">SKU</th>
                <th className="px-4 py-2.5">名称</th>
                <th className="px-4 py-2.5">分类</th>
                <th className="px-4 py-2.5 text-right">目标售价</th>
                <th className="px-4 py-2.5">状态</th>
              </tr>
            </thead>
            <tbody>
              {products.data.map((p) => (
                <tr key={p.id} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                  <td className="px-4 py-2.5">
                    <Link to={`/products/${p.id}`} className="font-medium text-sky-300 hover:underline">
                      {p.sku}
                    </Link>
                  </td>
                  <td className="px-4 py-2.5 text-slate-200">{p.name}</td>
                  <td className="px-4 py-2.5 text-slate-400">{p.category ?? '—'}</td>
                  <td className="tabular px-4 py-2.5 text-right text-slate-200">
                    {fmtMoney(p.target_sell_price)}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge tone={statusTone(p.status)}>{p.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="新建商品">
        <ErrorNote error={error} />
        <div className="space-y-3">
          <input
            placeholder="SKU *"
            value={form.sku}
            onChange={(e) => setForm({ ...form, sku: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none focus:border-sky-500"
          />
          <input
            placeholder="名称 *"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none focus:border-sky-500"
          />
          <div className="grid grid-cols-2 gap-2">
            <input
              placeholder="分类"
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none focus:border-sky-500"
            />
            <input
              placeholder="单位"
              value={form.unit}
              onChange={(e) => setForm({ ...form, unit: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none focus:border-sky-500"
            />
          </div>
          <input
            placeholder="条码"
            value={form.barcode}
            onChange={(e) => setForm({ ...form, barcode: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none focus:border-sky-500"
          />
          <input
            placeholder="目标售价"
            value={form.target_sell_price}
            onChange={(e) => setForm({ ...form, target_sell_price: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none focus:border-sky-500"
          />
          <Button
            onClick={() => createMutation.mutate()}
            disabled={!form.sku || !form.name || createMutation.isPending}
            className="w-full"
          >
            {createMutation.isPending ? '创建中…' : '创建'}
          </Button>
        </div>
      </Modal>
    </div>
  )
}
