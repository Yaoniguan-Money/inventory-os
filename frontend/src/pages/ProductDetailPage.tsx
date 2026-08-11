import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api } from '../lib/api.ts'
import { fmtDate, fmtMoney, fmtQty } from '../lib/format.ts'
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  GsapNumber,
  Modal,
  OrderLink,
  PageHeader,
  Spinner,
  statusTone,
} from '../components/ui.tsx'
import TrendChart from '../components/TrendChart.tsx'

interface Overview {
  product: {
    id: string
    sku: string
    name: string
    category: string | null
    status: string
    unit: string
    barcode: string | null
    target_sell_price: string | null
  }
  default_warehouse_code: string | null
  default_location_code: string | null
  health: { score: number; status: string }
  inventory: {
    on_hand: string
    reserved: string
    available: string
    incoming: string
    expired_qty: string
    projected: string
    due_7d: string
    lot_count: number
  }
  prices: {
    last_purchase_price: string | null
    weighted_avg_cost: string | null
    target_sell_price: string | null
    actual_sell_price: string | null
  }
  alerts: Array<{
    id: string
    alert_type: string
    severity: string
    title: string
    evidence: Record<string, unknown>
  }>
  trends: {
    on_hand: Array<{ date: string; value: string }>
    available_projected: Array<{ date: string; value: string }>
    weighted_avg_cost: Array<{ date: string; value: string }>
    last_purchase_price: Array<{ date: string; value: string }>
    actual_sell_price: Array<{ date: string; value: string }>
    market_buy_domestic: Array<{ date: string; value: string }>
    market_sell_domestic: Array<{ date: string; value: string }>
    market_buy_international: Array<{ date: string; value: string }>
    market_sell_international: Array<{ date: string; value: string }>
  }
  timeline: Array<{
    sequence_id: number
    event_type: string
    occurred_at: string
    payload: Record<string, unknown>
  }>
}

interface MarketData {
  quotes: Array<{
    id: string
    quote_kind: string
    price: string
    currency: string
    source: string
    region: string
    basis: string | null
    observed_at: string
  }>
  events: Array<{ id: string; title: string; source: string; published_at: string }>
}

export default function ProductDetailPage() {
  const { productId } = useParams()
  const queryClient = useQueryClient()
  const [receiveOpen, setReceiveOpen] = useState(false)
  const [priceOpen, setPriceOpen] = useState(false)
  const [explain, setExplain] = useState<{ id: string; text: string } | null>(null)
  const [error, setError] = useState<unknown>(null)

  const overview = useQuery({
    queryKey: ['products', productId, 'overview'],
    queryFn: () => api.get<Overview>(`/products/${productId}/overview`),
  })
  const market = useQuery({
    queryKey: ['market', productId],
    queryFn: () => api.get<MarketData>(`/products/${productId}/market`),
  })
  const orders = useQuery({
    queryKey: ['orders', 'product', productId],
    queryFn: () => api.get<Array<Record<string, unknown>>>('/orders'),
  })
  const lots = useQuery({
    queryKey: ['inventory', productId, 'lots'],
    queryFn: () => api.get<Array<Record<string, unknown>>>(`/inventory/${productId}/lots`),
  })
  const warehouses = useQuery({
    queryKey: ['warehouses'],
    queryFn: () => api.get<Array<{ id: string; code: string; name: string }>>('/warehouses'),
  })

  const [receiveForm, setReceiveForm] = useState({
    warehouse_id: '',
    quantity: '',
    unit_cost: '',
    lot_code: '',
    expires_at: '',
    location_id: '',
    purchase_order_line_id: '',
  })
  const [priceForm, setPriceForm] = useState({ price: '' })
  const locations = useQuery({
    queryKey: ['locations', receiveForm.warehouse_id],
    queryFn: () =>
      api.get<Array<{ id: string; code: string; name: string }>>(
        `/warehouses/${receiveForm.warehouse_id}/locations`,
      ),
    enabled: !!receiveForm.warehouse_id,
  })
  const purchaseOrders = useQuery({
    queryKey: ['purchase-orders'],
    queryFn: () =>
      api.get<
        Array<{
          id: string
          po_no: string
          status: string
          lines: Array<{ id: string; product_id: string; incoming_qty: string }>
        }>
      >('/purchase-orders'),
  })

  const receiveMutation = useMutation({
    mutationFn: () =>
      api.post('/inventory/receive', {
        product_id: productId,
        warehouse_id: receiveForm.warehouse_id,
        quantity: receiveForm.quantity,
        unit_cost: receiveForm.unit_cost || null,
        lot_code: receiveForm.lot_code || null,
        expires_at: receiveForm.expires_at || null,
        location_id: receiveForm.location_id || null,
        purchase_order_line_id: receiveForm.purchase_order_line_id || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] })
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      setReceiveOpen(false)
      setReceiveForm({
        warehouse_id: '',
        quantity: '',
        unit_cost: '',
        lot_code: '',
        expires_at: '',
        location_id: '',
        purchase_order_line_id: '',
      })
    },
    onError: setError,
  })

  const priceMutation = useMutation({
    mutationFn: () =>
      api.post(`/products/${productId}/target-price`, {
        price: priceForm.price,
        currency: 'CNY',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] })
      setPriceOpen(false)
    },
    onError: setError,
  })

  const explainMutation = useMutation({
    mutationFn: (alertId: string) =>
      api.post<{ explanation: string }>(`/ai/explain-alert/${alertId}`),
    onSuccess: (data, alertId) => setExplain({ id: alertId, text: data.explanation }),
    onError: setError,
  })

  if (overview.isLoading) return <Spinner />
  const data = overview.data!

  return (
    <div>
      <PageHeader
        title={`${data.product.sku} · ${data.product.name}`}
        description={`${data.product.category ?? '未分类'} · ${data.product.unit}`}
        action={
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setPriceOpen(true)}>
              设置目标售价
            </Button>
            <Button onClick={() => setReceiveOpen(true)}>入库</Button>
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
        <Badge tone={statusTone(data.product.status)}>状态 {data.product.status}</Badge>
        <span className="rounded-full border border-slate-700 px-2 py-0.5 text-slate-400">
          条码 {data.product.barcode ?? '—'}
        </span>
        <span className="rounded-full border border-slate-700 px-2 py-0.5 text-slate-400">
          默认仓库 {data.default_warehouse_code ?? '—'}
        </span>
        <span className="rounded-full border border-slate-700 px-2 py-0.5 text-slate-400">
          默认库位 {data.default_location_code ?? '—'}
        </span>
        <Badge tone={data.health.score < 70 ? 'red' : data.health.score < 90 ? 'amber' : 'green'}>
          健康状态 {data.health.status}（{data.health.score}）
        </Badge>
      </div>

      <ErrorNote error={error} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Card>
          <div className="text-xs text-slate-400">On Hand</div>
          <div className="tabular mt-1 text-2xl font-semibold text-slate-100">
            <GsapNumber value={Number(data.inventory.on_hand)} />
          </div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">Reserved</div>
          <div className="tabular mt-1 text-2xl font-semibold text-amber-300">
            <GsapNumber value={Number(data.inventory.reserved)} />
          </div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">Available</div>
          <div className="tabular mt-1 text-2xl font-semibold text-sky-300">
            <GsapNumber value={Number(data.inventory.available)} />
          </div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">Incoming</div>
          <div className="tabular mt-1 text-2xl font-semibold text-emerald-300">
            <GsapNumber value={Number(data.inventory.incoming)} />
          </div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">Projected</div>
          <div className="tabular mt-1 text-2xl font-semibold text-violet-300">
            <GsapNumber value={Number(data.inventory.projected)} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">Available + Incoming</div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">未来 7 日待交付</div>
          <div className="tabular mt-1 text-2xl font-semibold text-red-300">
            <GsapNumber value={Number(data.inventory.due_7d)} />
          </div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">库存健康分</div>
          <div className="tabular mt-1 text-2xl font-semibold text-slate-100">
            <GsapNumber value={data.health.score} />
          </div>
          <div className="mt-1 text-[11px] text-slate-500">后端权威分 / 100</div>
        </Card>
        <Card>
          <div className="text-xs text-slate-400">批次数量</div>
          <div className="tabular mt-1 text-2xl font-semibold text-slate-100">
            <GsapNumber value={data.inventory.lot_count} />
          </div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="企业价格（内部）">
          <div className="grid grid-cols-2 gap-3">
            <PriceCell label="最近采购价" value={fmtMoney(data.prices.last_purchase_price)} />
            <PriceCell label="移动平均成本" value={fmtMoney(data.prices.weighted_avg_cost)} />
            <PriceCell label="目标售价" value={fmtMoney(data.prices.target_sell_price)} />
            <PriceCell label="最近成交价" value={fmtMoney(data.prices.actual_sell_price)} />
          </div>
        </Card>
        <Card
          title="市场价格（外部 · 国内 / 国际）"
          action={
            <Button
              variant="outline"
              className="text-xs"
              onClick={() => queryClient.invalidateQueries({ queryKey: ['market'] })}
            >
              刷新
            </Button>
          }
        >
          <div className="grid grid-cols-2 gap-3">
            {(['DOMESTIC', 'INTERNATIONAL'] as const).map((region) => (
              <div key={region} className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
                <div className="mb-2 text-xs text-slate-400">
                  {region === 'DOMESTIC' ? '国内' : '国际'}
                </div>
                {['MARKET_BUY', 'MARKET_SELL'].map((kind) => {
                  const quote = market.data?.quotes.find(
                    (q) => q.quote_kind === kind && q.region === region,
                  )
                  return (
                    <div key={kind} className="mb-2 last:mb-0">
                      <div className="text-[11px] text-slate-500">
                        {quote?.basis === 'FX'
                          ? '汇率参考'
                          : kind === 'MARKET_BUY'
                            ? '市场采购价'
                            : '常见售价'}
                      </div>
                      <div className="tabular text-lg font-semibold text-slate-100">
                        {quote ? fmtMoney(quote.price, quote.currency) : '—'}
                      </div>
                      <div className="text-[10px] text-slate-600">
                        {quote ? `${quote.source} · ${fmtDate(quote.observed_at)}` : '暂无'}
                      </div>
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
          {market.data?.events.length ? (
            <div className="mt-3 space-y-1">
              {market.data.events.slice(0, 3).map((e) => (
                <div key={e.id} className="text-xs text-slate-400">
                  <span className="text-slate-300">{e.title}</span> · {e.source} · {fmtDate(e.published_at)}
                </div>
              ))}
            </div>
          ) : null}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="订单履约">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="py-2">订单</th>
                <th className="py-2">客户</th>
                <th className="py-2 text-right">数量</th>
                <th className="py-2 text-right">Reserved</th>
                <th className="py-2 text-right">已交付</th>
                <th className="py-2 text-right">剩余</th>
                <th className="py-2">要求交付</th>
                <th className="py-2 text-right">成交价</th>
                <th className="py-2">状态</th>
              </tr>
            </thead>
            <tbody>
              {(orders.data ?? [])
                .filter((o) =>
                  (o.lines as Array<{ product_id: string }>).some((l) => l.product_id === productId),
                )
                .map((o) => {
                  const line = (o.lines as Array<Record<string, unknown>>).find(
                    (l) => l.product_id === productId,
                  )
                  return (
                    <tr key={String(o.id)} className="border-t border-slate-800/60">
                      <td className="py-2">
                        <OrderLink id={String(o.id)}>{String(o.order_no)}</OrderLink>
                      </td>
                      <td className="py-2 text-slate-300">{String(o.customer_name)}</td>
                      <td className="tabular py-2 text-right">{fmtQty(String(line?.ordered_qty ?? 0))}</td>
                      <td className="tabular py-2 text-right text-amber-300">
                        {fmtQty(String(line?.reserved_qty ?? 0))}
                      </td>
                      <td className="tabular py-2 text-right">{fmtQty(String(line?.delivered_qty ?? 0))}</td>
                      <td className="tabular py-2 text-right">{fmtQty(String(line?.remaining_qty ?? 0))}</td>
                      <td className="py-2 text-slate-400">{fmtDate(String(o.required_at ?? ''))}</td>
                      <td className="tabular py-2 text-right">
                        {fmtMoney(String(line?.unit_sell_price ?? ''))}
                      </td>
                      <td className="py-2">
                        <Badge tone={statusTone(String(o.status))}>{String(o.status)}</Badge>
                      </td>
                    </tr>
                  )
                })}
            </tbody>
          </table>
        </Card>

        <Card title="批次库存">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="py-2">批次</th>
                <th className="py-2">位置</th>
                <th className="py-2 text-right">余量</th>
                <th className="py-2 text-right">单位成本</th>
                <th className="py-2">入库时间</th>
                <th className="py-2">有效期</th>
              </tr>
            </thead>
            <tbody>
              {(lots.data ?? []).map((lot) => (
                <tr key={String(lot.id)} className="border-t border-slate-800/60">
                  <td className="py-2 text-slate-300">{String(lot.lot_code)}</td>
                  <td className="py-2 text-slate-400">{String(lot.location_code ?? '—')}</td>
                  <td className="tabular py-2 text-right">{fmtQty(String(lot.quantity_remaining))}</td>
                  <td className="tabular py-2 text-right">{fmtMoney(String(lot.unit_cost ?? ''))}</td>
                  <td className="py-2 text-slate-400">{fmtDate(String(lot.received_at ?? ''))}</td>
                  <td className="py-2 text-slate-400">
                    {lot.expires_at ? (
                      <span className="text-amber-300">{fmtDate(String(lot.expires_at))}</span>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="库存 / 可用趋势">
          <TrendChart
            series={[
              { name: 'On Hand', data: data.trends.on_hand, color: '#38bdf8' },
              {
                name: 'Available（按当前预留推算）',
                data: data.trends.available_projected,
                color: '#34d399',
              },
            ]}
          />
        </Card>
        <Card title="成本与成交价趋势">
          <TrendChart
            series={[
              {
                name: '加权平均成本',
                data: data.trends.weighted_avg_cost,
                color: '#f59e0b',
              },
              {
                name: '最近采购价',
                data: data.trends.last_purchase_price,
                color: '#94a3b8',
              },
              {
                name: '实际成交价',
                data: data.trends.actual_sell_price,
                color: '#34d399',
              },
            ]}
          />
        </Card>
      </div>
      <div className="mt-4">
        <Card title="市场价格趋势">
          <TrendChart
            series={[
              {
                name: '国内采购价',
                data: data.trends.market_buy_domestic,
                color: '#60a5fa',
              },
              {
                name: '国内售价',
                data: data.trends.market_sell_domestic,
                color: '#f472b6',
              },
              {
                name: '国际采购价',
                data: data.trends.market_buy_international,
                color: '#c084fc',
              },
              {
                name: '国际售价',
                data: data.trends.market_sell_international,
                color: '#fb923c',
              },
            ]}
          />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="风险与告警">
          {data.alerts.length ? (
            <div className="space-y-2">
              {data.alerts.map((a) => (
                <div key={a.id} className="rounded-lg border border-red-500/20 bg-red-500/5 p-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium text-red-300">{a.title}</div>
                    <Badge tone={statusTone(a.severity)}>{a.severity}</Badge>
                  </div>
                  <div className="mt-1 text-xs text-slate-400">
                    类型：{a.alert_type} · 证据：{JSON.stringify(a.evidence)}
                  </div>
                  <Button
                    variant="ghost"
                    className="mt-2 text-xs"
                    onClick={() => explainMutation.mutate(a.id)}
                  >
                    为什么标红？
                  </Button>
                  {explain?.id === a.id && (
                    <div className="mt-2 rounded-lg bg-slate-800/70 p-3 text-sm text-slate-200">
                      {explain.text}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="py-6 text-center text-sm text-slate-500">当前无开放告警</div>
          )}
        </Card>

        <Card title="商品时间线">
          <div className="space-y-1">
            {data.timeline.map((e) => (
              <div key={e.sequence_id} className="flex items-start gap-2 text-xs">
                <span className="tabular mt-0.5 shrink-0 text-slate-600">
                  #{e.sequence_id}
                </span>
                <Badge tone={statusTone('CONFIRMED')}>{e.event_type}</Badge>
                <div className="min-w-0 flex-1 truncate text-slate-400">
                  {JSON.stringify(e.payload)}
                </div>
                <span className="tabular shrink-0 text-slate-600">{fmtDate(e.occurred_at)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Modal open={receiveOpen} onClose={() => setReceiveOpen(false)} title={`入库 ${data.product.sku}`}>
        <div className="space-y-3">
          <select
            value={receiveForm.warehouse_id}
            onChange={(e) => setReceiveForm({ ...receiveForm, warehouse_id: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          >
            <option value="">选择仓库 *</option>
            {warehouses.data?.map((w) => (
              <option key={w.id} value={w.id}>
                {w.code} · {w.name}
              </option>
            ))}
          </select>
          <input
            placeholder="数量 *"
            value={receiveForm.quantity}
            onChange={(e) => setReceiveForm({ ...receiveForm, quantity: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <input
            placeholder="单位购入价"
            value={receiveForm.unit_cost}
            onChange={(e) => setReceiveForm({ ...receiveForm, unit_cost: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <input
            placeholder="批次号"
            value={receiveForm.lot_code}
            onChange={(e) => setReceiveForm({ ...receiveForm, lot_code: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <input
            type="datetime-local"
            value={receiveForm.expires_at}
            onChange={(e) => setReceiveForm({ ...receiveForm, expires_at: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <select
            value={receiveForm.location_id}
            onChange={(e) => setReceiveForm({ ...receiveForm, location_id: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          >
            <option value="">选择库位（可选）</option>
            {locations.data?.map((l) => (
              <option key={l.id} value={l.id}>
                {l.code} · {l.name}
              </option>
            ))}
          </select>
          <select
            value={receiveForm.purchase_order_line_id}
            onChange={(e) =>
              setReceiveForm({ ...receiveForm, purchase_order_line_id: e.target.value })
            }
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          >
            <option value="">关联采购订单（可选）</option>
            {(purchaseOrders.data ?? [])
              .filter((po) => ['CONFIRMED', 'PARTIAL'].includes(po.status))
              .flatMap((po) =>
                po.lines
                  .filter((l) => l.product_id === productId && Number(l.incoming_qty) > 0)
                  .map((l) => ({ po_no: po.po_no, line_id: l.id, incoming: l.incoming_qty })),
              )
              .map((item) => (
                <option key={item.line_id} value={item.line_id}>
                  {item.po_no}（在途 {item.incoming}）
                </option>
              ))}
          </select>
          <Button
            className="w-full"
            disabled={!receiveForm.warehouse_id || !receiveForm.quantity || receiveMutation.isPending}
            onClick={() => receiveMutation.mutate()}
          >
            {receiveMutation.isPending ? '入库中…' : '确认入库'}
          </Button>
        </div>
      </Modal>

      <Modal open={priceOpen} onClose={() => setPriceOpen(false)} title="设置目标售价">
        <div className="space-y-3">
          <input
            placeholder="价格（CNY）"
            value={priceForm.price}
            onChange={(e) => setPriceForm({ price: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <Button className="w-full" disabled={!priceForm.price} onClick={() => priceMutation.mutate()}>
            保存
          </Button>
        </div>
      </Modal>
    </div>
  )
}

function PriceCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="text-xs text-slate-400">{label}</div>
      <div className="tabular mt-1 text-lg font-semibold text-slate-100">{value}</div>
    </div>
  )
}
