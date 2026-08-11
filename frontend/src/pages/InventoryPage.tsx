import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api.ts'
import { fmtDate, fmtQty } from '../lib/format.ts'
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
} from '../components/ui.tsx'

interface Balance {
  product_id: string
  sku: string
  name: string
  warehouse_code: string
  on_hand: string
  reserved: string
  available: string
  incoming: string
  default_location_code: string | null
  health_status: string
  last_receipt_at: string | null
  last_shipment_at: string | null
}

export default function InventoryPage() {
  const queryClient = useQueryClient()
  const [error, setError] = useState<unknown>(null)
  const [receiveOpen, setReceiveOpen] = useState(false)
  const [adjustOpen, setAdjustOpen] = useState(false)
  const [movementProduct, setMovementProduct] = useState<{ id: string; sku: string } | null>(null)
  const [form, setForm] = useState({
    product_id: '',
    warehouse_id: '',
    quantity: '',
    unit_cost: '',
    lot_code: '',
  })

  const inventory = useQuery({
    queryKey: ['inventory'],
    queryFn: () => api.get<Balance[]>('/inventory'),
  })
  const products = useQuery({
    queryKey: ['products'],
    queryFn: () => api.get<Array<{ id: string; sku: string; name: string }>>('/products'),
  })
  const warehouses = useQuery({
    queryKey: ['warehouses'],
    queryFn: () => api.get<Array<{ id: string; code: string; name: string }>>('/warehouses'),
  })

  const mutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post(receiveOpen ? '/inventory/receive' : '/inventory/adjust', payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
      queryClient.invalidateQueries({ queryKey: ['products'] })
      setReceiveOpen(false)
      setAdjustOpen(false)
      setForm({ product_id: '', warehouse_id: '', quantity: '', unit_cost: '', lot_code: '' })
    },
    onError: setError,
  })
  const movements = useQuery({
    queryKey: ['inventory', movementProduct?.id, 'movements'],
    queryFn: () =>
      api.get<
        Array<{
          id: string
          movement_type: string
          quantity: string
          reason: string | null
          occurred_at: string
        }>
      >(`/inventory/${movementProduct!.id}/movements`),
    enabled: movementProduct !== null,
  })

  return (
    <div>
      <PageHeader
        title="仓库中心"
        description="On Hand / Reserved / Available / Incoming 全量视图"
        action={
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setAdjustOpen(true)}>
              手工调整
            </Button>
            <Button onClick={() => setReceiveOpen(true)}>入库</Button>
          </div>
        }
      />
      <ErrorNote error={error} />
      <Card className="p-0">
        {inventory.isLoading ? (
          <Spinner />
        ) : !inventory.data?.length ? (
          <EmptyState text="暂无库存数据，先入库吧" />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                <th className="px-4 py-2.5">SKU</th>
                <th className="px-4 py-2.5">仓库</th>
                <th className="px-4 py-2.5 text-right">On Hand</th>
                <th className="px-4 py-2.5 text-right">Reserved</th>
                <th className="px-4 py-2.5 text-right">Available</th>
                <th className="px-4 py-2.5 text-right">Incoming</th>
                <th className="px-4 py-2.5">默认库位</th>
                <th className="px-4 py-2.5">健康状态</th>
                <th className="px-4 py-2.5">最近入库</th>
                <th className="px-4 py-2.5">最近出库</th>
                <th className="px-4 py-2.5">流水</th>
              </tr>
            </thead>
            <tbody>
              {inventory.data.map((b) => (
                <tr key={`${b.product_id}-${b.warehouse_code}`} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                  <td className="px-4 py-2.5">
                    <ProductLink id={b.product_id}>
                      {b.sku} · {b.name}
                    </ProductLink>
                  </td>
                  <td className="px-4 py-2.5 text-slate-400">{b.warehouse_code}</td>
                  <td className="tabular px-4 py-2.5 text-right text-slate-200">{fmtQty(b.on_hand)}</td>
                  <td className="tabular px-4 py-2.5 text-right text-amber-300">{fmtQty(b.reserved)}</td>
                  <td className="tabular px-4 py-2.5 text-right text-sky-300">{fmtQty(b.available)}</td>
                  <td className="tabular px-4 py-2.5 text-right text-emerald-300">{fmtQty(b.incoming)}</td>
                  <td className="px-4 py-2.5 text-slate-400">{b.default_location_code ?? '—'}</td>
                  <td className="px-4 py-2.5">
                    <Badge tone={b.health_status === 'HIGH' ? 'red' : b.health_status === 'WARN' ? 'amber' : 'green'}>
                      {b.health_status}
                    </Badge>
                  </td>
                  <td className="px-4 py-2.5 text-slate-400">{fmtDate(b.last_receipt_at)}</td>
                  <td className="px-4 py-2.5 text-slate-400">{fmtDate(b.last_shipment_at)}</td>
                  <td className="px-4 py-2.5">
                    <Button
                      variant="ghost"
                      className="text-xs"
                      onClick={() => setMovementProduct({ id: b.product_id, sku: b.sku })}
                    >
                      查看流水
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Modal open={receiveOpen} onClose={() => setReceiveOpen(false)} title="入库">
        <StockForm
          form={form}
          setForm={setForm}
          products={products.data ?? []}
          warehouses={warehouses.data ?? []}
          showCost
          onSubmit={() =>
            mutation.mutate({
              product_id: form.product_id,
              warehouse_id: form.warehouse_id,
              quantity: form.quantity,
              unit_cost: form.unit_cost || null,
              lot_code: form.lot_code || null,
            })
          }
          busy={mutation.isPending}
        />
      </Modal>
      <Modal
        open={movementProduct !== null}
        onClose={() => setMovementProduct(null)}
        title={`库存流水 · ${movementProduct?.sku ?? ''}`}
        wide
      >
        {movements.isLoading ? (
          <Spinner />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
                <th className="py-2">类型</th>
                <th className="py-2 text-right">数量</th>
                <th className="py-2">原因</th>
                <th className="py-2">时间</th>
              </tr>
            </thead>
            <tbody>
              {(movements.data ?? []).map((m) => (
                <tr key={m.id} className="border-t border-slate-800/60">
                  <td className="py-2">
                    <Badge tone={m.movement_type === 'RECEIPT' ? 'green' : 'amber'}>
                      {m.movement_type}
                    </Badge>
                  </td>
                  <td className="tabular py-2 text-right">{fmtQty(m.quantity)}</td>
                  <td className="py-2 text-slate-400">{m.reason ?? '—'}</td>
                  <td className="py-2 text-slate-400">{fmtDate(m.occurred_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Modal>
      <Modal open={adjustOpen} onClose={() => setAdjustOpen(false)} title="手工调整（正数加、负数减）">
        <StockForm
          form={form}
          setForm={setForm}
          products={products.data ?? []}
          warehouses={warehouses.data ?? []}
          onSubmit={() =>
            mutation.mutate({
              product_id: form.product_id,
              warehouse_id: form.warehouse_id,
              quantity: form.quantity,
              reason: '前端手工调整',
            })
          }
          busy={mutation.isPending}
        />
      </Modal>
    </div>
  )
}

interface StockFormState {
  product_id: string
  warehouse_id: string
  quantity: string
  unit_cost: string
  lot_code: string
}

function StockForm({
  form,
  setForm,
  products,
  warehouses,
  onSubmit,
  busy,
  showCost,
}: {
  form: StockFormState
  setForm: React.Dispatch<React.SetStateAction<StockFormState>>
  products: Array<{ id: string; sku: string; name: string }>
  warehouses: Array<{ id: string; code: string; name: string }>
  onSubmit: () => void
  busy: boolean
  showCost?: boolean
}) {
  return (
    <div className="space-y-3">
      <select
        value={form.product_id}
        onChange={(e) => setForm({ ...form, product_id: e.target.value })}
        className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
      >
        <option value="">选择商品 *</option>
        {products.map((p) => (
          <option key={p.id} value={p.id}>
            {p.sku} · {p.name}
          </option>
        ))}
      </select>
      <select
        value={form.warehouse_id}
        onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}
        className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
      >
        <option value="">选择仓库 *</option>
        {warehouses.map((w) => (
          <option key={w.id} value={w.id}>
            {w.code} · {w.name}
          </option>
        ))}
      </select>
      <input
        placeholder="数量 *"
        value={form.quantity}
        onChange={(e) => setForm({ ...form, quantity: e.target.value })}
        className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
      />
      {showCost && (
        <input
          placeholder="单位购入价"
          value={form.unit_cost}
          onChange={(e) => setForm({ ...form, unit_cost: e.target.value })}
          className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
        />
      )}
      {showCost && (
        <input
          placeholder="批次号"
          value={form.lot_code}
          onChange={(e) => setForm({ ...form, lot_code: e.target.value })}
          className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
        />
      )}
      <Button
        className="w-full"
        disabled={!form.product_id || !form.warehouse_id || !form.quantity || busy}
        onClick={onSubmit}
      >
        {busy ? '提交中…' : '提交'}
      </Button>
    </div>
  )
}
