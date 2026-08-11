import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth.tsx'
import { ErrorNote } from '../components/ui.tsx'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('admin@inventoryos.dev')
  const [password, setPassword] = useState('Demo@12345')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-2xl">
        <div className="mb-6 text-center">
          <div className="text-lg font-semibold text-slate-100">InventoryOS</div>
          <div className="mt-1 text-xs text-slate-500">库存 · 订单 · 采购 · 市场 · 设备 · 知识</div>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <ErrorNote error={error} />
          <label className="block">
            <span className="mb-1 block text-xs text-slate-400">邮箱</span>
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-400">密码</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500"
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-sky-600 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50"
          >
            {busy ? '登录中…' : '登录'}
          </button>
        </form>
        <p className="mt-4 text-center text-[11px] text-slate-600">
          默认 Demo 用户：admin@inventoryos.dev / Demo@12345
        </p>
      </div>
    </div>
  )
}
