import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api } from '../lib/api.ts'
import { fmtDate, fmtMoney, fmtQty } from '../lib/format.ts'
import {
  Button,
  Card,
  ErrorNote,
  Modal,
  PageHeader,
  ProductLink,
  Spinner,
} from '../components/ui.tsx'

export default function OrderDetailPage() {
  const { orderId } = useParams()
  const queryClient = useQueryClient()
  const [fulfillLine, setFulfillLine] = useState<{ id: string; qty: string } | null>(null)
  const [error, setError] = useState<unknown>(null)

  const order = useQuery({
    queryKey: ['orders', orderId],
    queryFn: () => api.get<Record<string, unknown>>(`/orders/${orderId}`),
  })

  const mutation = useMutation({
    mutationFn: ({ action, payload }: { action: string; payload?: unknown }) =>
      api.post(`/orders/${orderId}/${action}`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
      setFulfillLine(null)
    },
    onError: setError,
  })

  if (order.isLoading) return <Spinner />
  const data = order.data!
  const lines = (data.lines as Array<Record<string, unknown>>) ?? []

  return (
    <div>
      <PageHeader
        title={String(data.order_no)}
        description={`客户：${data.customer_name} · 要求交付：${fmtDate(String(data.required_at ?? ''))}`}
        action={
          <div className="flex gap-2">
            {data.status === 'DRAFT' && (
              <Button onClick={() => mutation.mutate({ action: 'confirm' })}>确认订单</Button>
            )}
            {['CONFIRMED', 'PARTIAL'].includes(String(data.status)) && (
              <Button variant="danger" onClick={() => mutation.mutate({ action: 'cancel' })}>
                取消订单
              </Button>
            )}
          </div>
        }
      />
      <ErrorNote error={error} />
      <Card title={`订单行（状态 ${String(data.status)}）`}>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left text-xs text-slate-500">
              <th className="py-2">SKU</th>
              <th className="py-2 text-right">下单</th>
              <th className="py-2 text-right">已预留</th>
              <th className="py-2 text-right">已交付</th>
              <th className="py-2 text-right">剩余</th>
              <th className="py-2 text-right">成交价</th>
              <th className="py-2">操作</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => (
              <tr key={String(line.id)} className="border-t border-slate-800/60">
                <td className="py-2">
                  <ProductLink id={String(line.product_id)}>{String(line.sku)}</ProductLink>
                </td>
                <td className="tabular py-2 text-right">{fmtQty(String(line.ordered_qty))}</td>
                <td className="tabular py-2 text-right">{fmtQty(String(line.reserved_qty))}</td>
                <td className="tabular py-2 text-right">{fmtQty(String(line.delivered_qty))}</td>
                <td className="tabular py-2 text-right">{fmtQty(String(line.remaining_qty))}</td>
                <td className="tabular py-2 text-right">{fmtMoney(String(line.unit_sell_price ?? ''))}</td>
                <td className="py-2">
                  {['CONFIRMED', 'PARTIAL'].includes(String(data.status)) && (
                    <Button
                      variant="ghost"
                      className="text-xs"
                      onClick={() =>
                        setFulfillLine({ id: String(line.id), qty: String(line.remaining_qty) })
                      }
                    >
                      交付
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Modal
        open={fulfillLine !== null}
        onClose={() => setFulfillLine(null)}
        title="部分/全部交付"
      >
        <div className="space-y-3">
          <input
            value={fulfillLine?.qty ?? ''}
            onChange={(e) => setFulfillLine((f) => (f ? { ...f, qty: e.target.value } : f))}
            className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none"
          />
          <Button
            className="w-full"
            disabled={!fulfillLine?.qty || mutation.isPending}
            onClick={() =>
              mutation.mutate({
                action: 'fulfill',
                payload: {
                  lines: [{ sales_order_line_id: fulfillLine!.id, quantity: fulfillLine!.qty }],
                },
              })
            }
          >
            {mutation.isPending ? '交付中…' : '确认交付'}
          </Button>
        </div>
      </Modal>
    </div>
  )
}
