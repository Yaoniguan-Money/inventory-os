import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api.ts'
import { fmtDate, fmtMoney } from '../lib/format.ts'
import {
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Modal,
  PageHeader,
  Spinner,
} from '../components/ui.tsx'

interface MarketData {
  quotes: Array<{
    id: string
    quote_kind: string
    price: string
    currency: string
    source: string
    region: string
    observed_at: string
  }>
  events: Array<{ id: string; title: string; summary: string | null; source: string; published_at: string }>
  mappings: Array<{ id: string; provider: string; external_symbol: string; region: string; enabled: boolean }>
}

export default function MarketPage() {
  const queryClient = useQueryClient()
  const [productId, setProductId] = useState('')
  const [mappingOpen, setMappingOpen] = useState(false)
  const [mappingForm, setMappingForm] = useState({ external_symbol: '', region: 'DOMESTIC' })
  const [error, setError] = useState<unknown>(null)

  const products = useQuery({
    queryKey: ['products'],
    queryFn: () => api.get<Array<{ id: string; sku: string; name: string }>>('/products'),
  })
  const market = useQuery({
    queryKey: ['market', productId],
    queryFn: () => api.get<MarketData>(`/products/${productId}/market`),
    enabled: !!productId,
  })

  const refresh = useMutation({
    mutationFn: () => api.post('/market/refresh'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['market'] })
      queryClient.invalidateQueries({ queryKey: ['products'] })
    },
    onError: setError,
  })
  const createMapping = useMutation({
    mutationFn: () =>
      api.post(`/products/${productId}/market-mappings`, {
        provider: 'mock',
        external_symbol: mappingForm.external_symbol,
        region: mappingForm.region,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['market'] })
      setMappingOpen(false)
      setMappingForm({ external_symbol: '', region: 'DOMESTIC' })
    },
    onError: setError,
  })

  return (
    <div>
      <PageHeader
        title="市场行情"
        description="内部价格 vs 外部市场：来源、时间、币种、地区"
        action={
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setMappingOpen(true)} disabled={!productId}>
              添加映射
            </Button>
            <Button onClick={() => refresh.mutate()} disabled={refresh.isPending}>
              {refresh.isPending ? '刷新中…' : '刷新行情'}
            </Button>
          </div>
        }
      />
      <ErrorNote error={error} />
      <div className="mb-4">
        <select
          value={productId}
          onChange={(e) => setProductId(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
        >
          <option value="">选择商品</option>
          {products.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.sku} · {p.name}
            </option>
          ))}
        </select>
      </div>

      {!productId ? (
        <Card>
          <EmptyState text="选择一个商品查看行情" />
        </Card>
      ) : market.isLoading ? (
        <Spinner />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="市场报价">
            {market.data?.quotes.length ? (
              <div className="space-y-2">
                {market.data.quotes.map((q) => (
                  <div key={q.id} className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
                    <div>
                      <div className="text-sm text-slate-300">
                        {q.quote_kind === 'MARKET_BUY' ? '市场采购价' : '市场常见售价'} · {q.region}
                      </div>
                      <div className="text-xs text-slate-500">
                        {q.source} · {fmtDate(q.observed_at)}
                      </div>
                    </div>
                    <div className="tabular text-lg font-semibold text-slate-100">
                      {fmtMoney(q.price, q.currency)}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState text="暂无报价，先添加映射并刷新" />
            )}
          </Card>
          <Card title="行情事件">
            {market.data?.events.length ? (
              <div className="space-y-2">
                {market.data.events.map((e) => (
                  <div key={e.id} className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
                    <div className="text-sm text-slate-200">{e.title}</div>
                    {e.summary && <div className="mt-1 text-xs text-slate-400">{e.summary}</div>}
                    <div className="mt-1 text-[11px] text-slate-600">
                      {e.source} · {fmtDate(e.published_at)}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState text="暂无行情事件" />
            )}
          </Card>
        </div>
      )}

      <Modal open={mappingOpen} onClose={() => setMappingOpen(false)} title="添加商品市场映射">
        <div className="space-y-3">
          <input
            placeholder="外部符号（如 AL-99.7）"
            value={mappingForm.external_symbol}
            onChange={(e) => setMappingForm({ ...mappingForm, external_symbol: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <select
            value={mappingForm.region}
            onChange={(e) => setMappingForm({ ...mappingForm, region: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          >
            <option value="DOMESTIC">国内</option>
            <option value="INTERNATIONAL">国际</option>
          </select>
          <Button className="w-full" disabled={!mappingForm.external_symbol} onClick={() => createMapping.mutate()}>
            添加（Mock Provider）
          </Button>
        </div>
      </Modal>
    </div>
  )
}
