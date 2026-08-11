import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { api } from '../lib/api.ts'
import { fmtDate, fmtMoney, fmtQty } from '../lib/format.ts'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Modal,
  PageHeader,
  ProductLink,
  Spinner,
  statusTone,
} from '../components/ui.tsx'

interface WorkbenchItem {
  product_id: string
  sku: string
  name: string
  on_hand: string
  reserved: string
  available: string
  incoming: string
  demand_7d: string
  shortage_7d: string
  last_purchase_price: string | null
  weighted_avg_cost: string | null
  market_quotes: {
    DOMESTIC?: { MARKET_BUY?: MarketQuoteLike; MARKET_SELL?: MarketQuoteLike }
    INTERNATIONAL?: { MARKET_BUY?: MarketQuoteLike; MARKET_SELL?: MarketQuoteLike }
  }
  suppliers: Array<{ supplier_id: string; name: string }>
  purchase_orders: Array<{ po_id: string; po_no: string; expected_at: string | null; incoming: string }>
}

interface MarketQuoteLike {
  price: string
  currency: string
  source: string
  observed_at: string
}

export default function PurchasingPage() {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [form, setForm] = useState({
    supplier_id: '',
    product_id: '',
    ordered_qty: '',
    unit_purchase_price: '',
    expected_at: '',
  })

  const workbench = useQuery({
    queryKey: ['purchasing'],
    queryFn: () => api.get<WorkbenchItem[]>('/purchase-workbench'),
  })
  const suppliers = useQuery({
    queryKey: ['suppliers'],
    queryFn: () => api.get<Array<{ id: string; code: string; name: string }>>('/suppliers'),
  })
  const products = useQuery({
    queryKey: ['products'],
    queryFn: () => api.get<Array<{ id: string; sku: string; name: string }>>('/products'),
  })
  const pos = useQuery({
    queryKey: ['purchase-orders'],
    queryFn: () =>
      api.get<
        Array<{
          id: string
          po_no: string
          supplier_name: string
          status: string
          expected_at: string | null
          lines: Array<{ id: string; sku: string; ordered_qty: string; received_qty: string; incoming_qty: string }>
        }>
      >('/purchase-orders'),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      api.post('/purchase-orders', {
        supplier_id: form.supplier_id,
        lines: [
          {
            product_id: form.product_id,
            ordered_qty: form.ordered_qty,
            unit_purchase_price: form.unit_purchase_price || null,
          },
        ],
        expected_at: form.expected_at ? new Date(form.expected_at).toISOString() : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['purchase-orders'] })
      queryClient.invalidateQueries({ queryKey: ['purchasing'] })
      setCreateOpen(false)
    },
    onError: setError,
  })

  const actionMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      api.post(`/purchase-orders/${id}/${action}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['purchase-orders'] })
      queryClient.invalidateQueries({ queryKey: ['purchasing'] })
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
    },
    onError: setError,
  })

  return (
    <div>
      <PageHeader
        title="采购中心"
        description="库存缺口、需求、在途、历史采购价与市场行情统一视图"
        action={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-1 inline h-4 w-4" /> 新建采购单
          </Button>
        }
      />
      <ErrorNote error={error} />

      <Card title="原材料采购工作台" className="mb-4 p-0">
        {workbench.isLoading ? (
          <Spinner />
        ) : !workbench.data?.length ? (
          <EmptyState text="暂无商品数据" />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                <th className="px-4 py-2.5">SKU</th>
                <th className="px-4 py-2.5 text-right">On Hand</th>
                <th className="px-4 py-2.5 text-right">Available</th>
                <th className="px-4 py-2.5 text-right">Incoming</th>
                <th className="px-4 py-2.5 text-right">7日需求</th>
                <th className="px-4 py-2.5 text-right">缺口</th>
                <th className="px-4 py-2.5 text-right">最近采购价</th>
                <th className="px-4 py-2.5 text-right">平均成本</th>
                <th className="px-4 py-2.5 text-right">国内采购价</th>
                <th className="px-4 py-2.5 text-right">国际参考价</th>
                <th className="px-4 py-2.5">供应商</th>
              </tr>
            </thead>
            <tbody>
              {workbench.data.map((w) => (
                <tr key={w.product_id} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                  <td className="px-4 py-2.5">
                    <ProductLink id={w.product_id}>
                      {w.sku} · {w.name}
                    </ProductLink>
                  </td>
                  <td className="tabular px-4 py-2.5 text-right">{fmtQty(w.on_hand)}</td>
                  <td className="tabular px-4 py-2.5 text-right">{fmtQty(w.available)}</td>
                  <td className="tabular px-4 py-2.5 text-right text-emerald-300">{fmtQty(w.incoming)}</td>
                  <td className="tabular px-4 py-2.5 text-right">{fmtQty(w.demand_7d)}</td>
                  <td className="tabular px-4 py-2.5 text-right">
                    {Number(w.shortage_7d) > 0 ? (
                      <span className="text-red-400">{fmtQty(w.shortage_7d)}</span>
                    ) : (
                      <span className="text-slate-600">0</span>
                    )}
                  </td>
                  <td className="tabular px-4 py-2.5 text-right">{fmtMoney(w.last_purchase_price)}</td>
                  <td className="tabular px-4 py-2.5 text-right">{fmtMoney(w.weighted_avg_cost)}</td>
                  <td className="px-4 py-2.5 text-right">
                    {w.market_quotes?.DOMESTIC?.MARKET_BUY ? (
                      <div className="text-xs">
                        <div className="tabular text-slate-200">
                          {fmtMoney(w.market_quotes.DOMESTIC.MARKET_BUY.price, w.market_quotes.DOMESTIC.MARKET_BUY.currency)}
                        </div>
                        <div className="text-[10px] text-slate-500">
                          {w.market_quotes.DOMESTIC.MARKET_BUY.source}
                        </div>
                      </div>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {w.market_quotes?.INTERNATIONAL?.MARKET_SELL ? (
                      <div className="text-xs">
                        <div className="tabular text-slate-200">
                          {fmtMoney(
                            w.market_quotes.INTERNATIONAL.MARKET_SELL.price,
                            w.market_quotes.INTERNATIONAL.MARKET_SELL.currency,
                          )}
                        </div>
                        <div className="text-[10px] text-slate-500">
                          {w.market_quotes.INTERNATIONAL.MARKET_SELL.source}
                        </div>
                      </div>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-slate-400">
                    {w.suppliers.map((s) => s.name).join('、') || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="采购订单" className="p-0">
        {pos.isLoading ? (
          <Spinner />
        ) : !pos.data?.length ? (
          <EmptyState text="暂无采购订单" />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                <th className="px-4 py-2.5">单号</th>
                <th className="px-4 py-2.5">供应商</th>
                <th className="px-4 py-2.5">商品</th>
                <th className="px-4 py-2.5 text-right">在途</th>
                <th className="px-4 py-2.5">预计到货</th>
                <th className="px-4 py-2.5">状态</th>
                <th className="px-4 py-2.5">操作</th>
              </tr>
            </thead>
            <tbody>
              {pos.data.map((po) => (
                <tr key={po.id} className="border-b border-slate-800/60">
                  <td className="px-4 py-2.5 text-slate-200">{po.po_no}</td>
                  <td className="px-4 py-2.5 text-slate-300">{po.supplier_name}</td>
                  <td className="px-4 py-2.5">
                    {po.lines.map((l) => (
                      <div key={l.id} className="text-xs text-slate-400">{l.sku}</div>
                    ))}
                  </td>
                  <td className="tabular px-4 py-2.5 text-right">
                    {po.lines.map((l) => (
                      <div key={l.id}>{fmtQty(l.incoming_qty)}</div>
                    ))}
                  </td>
                  <td className="px-4 py-2.5 text-slate-400">{fmtDate(po.expected_at)}</td>
                  <td className="px-4 py-2.5">
                    <Badge tone={statusTone(po.status)}>{po.status}</Badge>
                  </td>
                  <td className="px-4 py-2.5">
                    {po.status === 'DRAFT' && (
                      <Button
                        variant="ghost"
                        className="text-xs"
                        onClick={() => actionMutation.mutate({ id: po.id, action: 'confirm' })}
                      >
                        确认
                      </Button>
                    )}
                    {['CONFIRMED', 'PARTIAL'].includes(po.status) && (
                      <Button
                        variant="outline"
                        className="text-xs"
                        onClick={() => actionMutation.mutate({ id: po.id, action: 'receive' })}
                      >
                        全部到货
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="新建采购订单">
        <div className="space-y-3">
          <select
            value={form.supplier_id}
            onChange={(e) => setForm({ ...form, supplier_id: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          >
            <option value="">选择供应商 *</option>
            {suppliers.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.code} · {s.name}
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
              placeholder="采购单价"
              value={form.unit_purchase_price}
              onChange={(e) => setForm({ ...form, unit_purchase_price: e.target.value })}
              className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
            />
          </div>
          <input
            type="datetime-local"
            value={form.expected_at}
            onChange={(e) => setForm({ ...form, expected_at: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <Button
            className="w-full"
            disabled={!form.supplier_id || !form.product_id || !form.ordered_qty || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            {createMutation.isPending ? '创建中…' : '创建草稿'}
          </Button>
        </div>
      </Modal>
    </div>
  )
}
