import { useRef, useState } from 'react'
import { Camera, ScanBarcode, Type } from 'lucide-react'
import { api } from '../lib/api.ts'
import { Button, ErrorNote } from './ui.tsx'

interface ResolveCandidate {
  product_id: string
  sku: string
  name: string
  confidence: number
  reason: string
}

export default function ProductResolver({
  onSelect,
}: {
  onSelect: (candidate: { id: string; sku: string; name: string }) => void
}) {
  const [mode, setMode] = useState<'barcode' | 'text' | 'image'>('barcode')
  const [barcode, setBarcode] = useState('')
  const [text, setText] = useState('')
  const [image, setImage] = useState('')
  const [candidates, setCandidates] = useState<ResolveCandidate[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  async function resolve() {
    setBusy(true)
    setError(null)
    try {
      const data = await api.post<{ candidates: ResolveCandidate[] }>('/ai/resolve-product', {
        barcode: mode === 'barcode' ? barcode || null : null,
        text: mode === 'text' ? text || null : null,
        image_data_url: mode === 'image' ? image || null : null,
      })
      setCandidates(data.candidates)
    } catch (err) {
      setError(err)
      setCandidates([])
    } finally {
      setBusy(false)
    }
  }

  function readFile(file: File | undefined) {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => setImage(String(reader.result))
    reader.readAsDataURL(file)
  }

  return (
    <div className="rounded-lg border border-sky-500/20 bg-sky-500/5 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-sky-300">智能识别（扫码 / 文字 / 拍照）</span>
        <div className="flex gap-1">
          {(
            [
              ['barcode', ScanBarcode, '扫码'],
              ['text', Type, '文字'],
              ['image', Camera, '拍照'],
            ] as const
          ).map(([key, Icon, label]) => (
            <button
              key={key}
              onClick={() => setMode(key)}
              className={`flex items-center gap-1 rounded-md px-2 py-1 text-[11px] ${
                mode === key ? 'bg-sky-500/20 text-sky-200' : 'text-slate-400 hover:bg-slate-800'
              }`}
            >
              <Icon className="h-3 w-3" />
              {label}
            </button>
          ))}
        </div>
      </div>

      {mode === 'barcode' && (
        <input
          value={barcode}
          onChange={(e) => setBarcode(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && resolve()}
          placeholder="扫描或输入条码"
          className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none focus:border-sky-500"
        />
      )}
      {mode === 'text' && (
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && resolve()}
          placeholder="输入型号 / 名称 / SKU"
          className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none focus:border-sky-500"
        />
      )}
      {mode === 'image' && (
        <div>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => readFile(e.target.files?.[0])}
          />
          <button
            onClick={() => fileRef.current?.click()}
            className="w-full rounded-lg border border-dashed border-slate-600 px-3 py-3 text-sm text-slate-400 hover:border-sky-500"
          >
            {image ? '已选择图片，可重新选择' : '点击选择商品照片'}
          </button>
        </div>
      )}

      <div className="mt-2 flex gap-2">
        <Button
          variant="ghost"
          className="flex-1"
          disabled={busy || (mode === 'image' && !image)}
          onClick={resolve}
        >
          {busy ? '识别中…' : '识别'}
        </Button>
        {candidates.length > 0 && (
          <Button variant="outline" className="flex-1" onClick={() => setCandidates([])}>
            清除结果
          </Button>
        )}
      </div>
      <ErrorNote error={error} />

      {candidates.length > 0 && (
        <div className="mt-2 space-y-1">
          {candidates.map((c) => (
            <button
              key={c.product_id}
              onClick={() => onSelect({ id: c.product_id, sku: c.sku, name: c.name })}
              className="flex w-full items-center justify-between rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-left hover:border-sky-500"
            >
              <div>
                <div className="text-sm text-slate-200">
                  {c.sku} · {c.name}
                </div>
                <div className="text-[11px] text-slate-500">{c.reason}</div>
              </div>
              <span className="text-xs text-sky-300">{(c.confidence * 100).toFixed(0)}%</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
