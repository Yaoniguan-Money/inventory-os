import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { api } from '../lib/api.ts'
import { fmtDate, fmtQty } from '../lib/format.ts'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Modal,
  OrderLink,
  PageHeader,
  ProductLink,
  Spinner,
  statusTone,
} from '../components/ui.tsx'

interface Order {
  id: string
  order_no: string
  customer_name: string
  status: string
  required_at: string | null
  lines: Array<{
    id: string
    product_id: string
    sku: string
    name: string
    ordered_qty: string
    delivered_qty: string
    remaining_qty: string
  }>
}

export default function OrdersPage() {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [filter, setFilter] = useState('')

  const orders = useQuery({
    queryKey: ['orders'],
    queryFn: () => api.get<Order[]>('/orders'),
  })
  const customers = useQuery({
    queryKey: ['customers'],
    queryFn: () => api.get<Array<{ id: string; code: string; name: string }>>('/customers'),
  })
  const products = useQuery({
    queryKey: ['products'],
    queryFn: () => api.get<Array<{ id: string; sku: string; name: string }>>('/products'),
  })

  const [form, setForm] = useState({
    customer_id: '',
    product_id: '',
    ordered_qty: '',
    unit_sell_price: '',
    required_at: '',
  })

  const createMutation = useMutation({
    mutationFn: () =>
      api.post('/orders', {
        customer_id: form.customer_id,
        lines: [
          {
            product_id: form.product_id,
            ordered_qty: form.ordered_qty,
            unit_sell_price: form.unit_sell_price || null,
          },
        ],
        required_at: form.required_at ? new Date(form.required_at).toISOString() : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      setCreateOpen(false)
      setForm({ customer_id: '', product_id: '', ordered_qty: '', unit_sell_price: '', required_at: '' })
    },
    onError: setError,
  })

  const actionMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'confirm' | 'cancel' }) =>
      api.post(`/orders/${id}/${action}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: setError,
  })

  const visible = orders.data?.filter(
    (o) => !filter || o.status === filter,
  )

  return (
    <div>
      <PageHeader
        title="订单中心"
        description="创建、确认、交付与取消订单"
        action={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-1 inline h-4 w-4" /> 新建订单
          </Button>
        }
      />
      <ErrorNote error={error} />
      <Card className="p-0">
        <div className="flex gap-2 border-b border-slate-800 p-3">
          {['', 'DRAFT', 'CONFIRMED', 'PARTIAL', 'FULFILLED', 'CANCELLED'].map((s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={`rounded-full px-3 py-1 text-xs ${
                filter === s ? 'bg-sky-500/20 text-sky-300' : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              {s || '全部'}
            </button>
          ))}
        </div>
        {orders.isLoading ? (
          <Spinner />
        ) : !visible?.length ? (
          <EmptyState text="暂无订单" />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                <th className="px-4 py-2.5">订单号</th>
                <th className="px-4 py-2.5">客户</th>
                <th className="px-4 py-2.5">商品</th>
                <th className="px-4 py-2.5 text-right">数量</th>
                <th className="px-4 py-2.5 text-right">已交付</th>
                <th className="px-4 py-2.5">要求交付</th>
                <th className="px-4 py-2.5">状态</th>
                <th className="px-4 py-2.5">操作</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((o) => (
                <tr key={o.id} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                  <td className="px-4 py-2.5">
                    <OrderLink id={o.id}>{o.order_no}</OrderLink>
                  </td>
                  <td className="px-4 py-2.5 text-slate-300">{o.customer_name}</td>
                  <td className="px-4 py-2.5">
                    {o.lines.map((l) => (
                      <div key={l.id}>
                        <ProductLink id={l.product_id}>{l.sku}</ProductLink>
                      </div>
                    ))}
                  </td>
                  <td className="tabular px-4 py-2.5 text-right">
                    {o.lines.map((l) => (
                      <div key={l.id}>{fmtQty(l.ordered_qty)}</div>
                    ))}
                  </td>
                  <td className="tabular px-4 py-2.5 text-right">
                    {o.lines.map((l) => (
                      <div key={l.id}>{fmtQty(l.delivered_qty)}</div>
                    ))}
                  </td>
                  <td className="px-4 py-2.5 text-slate-400">{fmtDate(o.required_at)}</td>
                  <td className="px-4 py-2.5">
                    <Badge tone={statusTone(o.status)}>{o.status}</Badge>
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex gap-1.5">
                      {o.status === 'DRAFT' && (
                        <Button
                          variant="ghost"
                          className="text-xs"
                          onClick={() => actionMutation.mutate({ id: o.id, action: 'confirm' })}
                        >
                          确认
                        </Button>
                      )}
                      {['DRAFT', 'CONFIRMED', 'PARTIAL'].includes(o.status) && (
                        <Button
                          variant="danger"
                          className="text-xs"
                          onClick={() => actionMutation.mutate({ id: o.id, action: 'cancel' })}
                        >
                          取消
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="新建销售订单">
        <div className="space-y-3">
          <select
            value={form.customer_id}
            onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          >
            <option value="">选择客户 *</option>
            {customers.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.code} · {c.name}
              </option>
            ))}
          </select>
          <select
            value={form.product_id}
            onChange={(e) => setForm({ ...form, product_id: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          >
            <option value="">选择商品 *</option>
            {products.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.sku} · {p.name}
              </option>
            ))}
          </select>
          <div className="grid grid-cols-2 gap-2">
            <input
              placeholder="数量 *"
              value={form.ordered_qty}
              onChange={(e) => setForm({ ...form, ordered_qty: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
            />
            <input
              placeholder="成交价"
              value={form.unit_sell_price}
              onChange={(e) => setForm({ ...form, unit_sell_price: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
            />
          </div>
          <input
            type="datetime-local"
            value={form.required_at}
            onChange={(e) => setForm({ ...form, required_at: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <Button
            className="w-full"
            disabled={!form.customer_id || !form.product_id || !form.ordered_qty || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            {createMutation.isPending ? '创建中…' : '创建草稿'}
          </Button>
        </div>
      </Modal>
    </div>
  )
}
