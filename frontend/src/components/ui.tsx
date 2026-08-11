import { useEffect, useRef } from 'react'
import { gsap } from 'gsap'
import { Boxes, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { fmtQty } from '../lib/format.ts'

export function Card({
  children,
  className = '',
  title,
  action,
}: {
  children: React.ReactNode
  className?: string
  title?: string
  action?: React.ReactNode
}) {
  return (
    <section
      className={`rounded-xl border border-slate-800/80 bg-slate-900/50 p-4 shadow-sm ${className}`}
    >
      {(title || action) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold text-slate-200">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

export function Stat({
  label,
  value,
  suffix,
  tone = 'default',
  sub,
}: {
  label: string
  value: string | number | null | undefined
  suffix?: string
  tone?: 'default' | 'risk' | 'warn' | 'good' | 'accent'
  sub?: string
}) {
  const tones: Record<string, string> = {
    default: 'text-slate-100',
    risk: 'text-red-400',
    warn: 'text-amber-300',
    good: 'text-emerald-300',
    accent: 'text-sky-300',
  }
  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-900/50 p-4">
      <div className="text-xs text-slate-400">{label}</div>
      <div className={`tabular mt-1 text-2xl font-semibold ${tones[tone]}`}>
        {value ?? '—'}
        {suffix && <span className="ml-1 text-sm font-normal text-slate-400">{suffix}</span>}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

export function Badge({
  children,
  tone = 'slate',
}: {
  children: React.ReactNode
  tone?: 'slate' | 'green' | 'amber' | 'red' | 'sky' | 'violet'
}) {
  const tones: Record<string, string> = {
    slate: 'bg-slate-800 text-slate-300',
    green: 'bg-emerald-500/10 text-emerald-300',
    amber: 'bg-amber-500/10 text-amber-300',
    red: 'bg-red-500/10 text-red-300',
    sky: 'bg-sky-500/10 text-sky-300',
    violet: 'bg-violet-500/10 text-violet-300',
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  )
}

export function statusTone(status: string): 'slate' | 'green' | 'amber' | 'red' | 'sky' {
  const map: Record<string, 'slate' | 'green' | 'amber' | 'red' | 'sky'> = {
    ACTIVE: 'green',
    CONFIRMED: 'sky',
    PARTIAL: 'amber',
    FULFILLED: 'green',
    CANCELLED: 'red',
    DRAFT: 'slate',
    OVERDUE: 'red',
    RECEIVED: 'green',
    OPEN: 'red',
    RESOLVED: 'green',
    OPERATIONAL: 'green',
    HIGH: 'red',
    CRITICAL: 'red',
    MEDIUM: 'amber',
    LOW: 'slate',
    INFO: 'slate',
  }
  return map[status] ?? 'slate'
}

export function severityTone(severity: string): 'slate' | 'green' | 'amber' | 'red' | 'sky' {
  return statusTone(severity)
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  type = 'button',
  disabled,
  className = '',
}: {
  children: React.ReactNode
  onClick?: () => void
  variant?: 'primary' | 'ghost' | 'danger' | 'outline'
  type?: 'button' | 'submit'
  disabled?: boolean
  className?: string
}) {
  const variants: Record<string, string> = {
    primary: 'bg-sky-600 text-white hover:bg-sky-500 disabled:bg-slate-700 disabled:text-slate-400',
    ghost: 'bg-slate-800 text-slate-200 hover:bg-slate-700',
    danger: 'bg-red-600/90 text-white hover:bg-red-500',
    outline: 'border border-slate-700 text-slate-300 hover:bg-slate-800',
  }
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  )
}

export function Modal({
  open,
  title,
  onClose,
  children,
  wide,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: React.ReactNode
  wide?: boolean
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div
        role="dialog"
        aria-modal="true"
        className={`max-h-[90vh] w-full overflow-y-auto rounded-xl border border-slate-700 bg-slate-900 p-5 shadow-2xl ${
          wide ? 'max-w-3xl' : 'max-w-md'
        }`}
      >
        <header className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-slate-100">{title}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
            ✕
          </button>
        </header>
        {children}
      </div>
    </div>
  )
}

export function Spinner() {
  return (
    <div className="flex items-center justify-center py-10 text-sm text-slate-500">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-slate-600 border-t-sky-400" />
    </div>
  )
}

export function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-slate-500">
      <Boxes className="h-8 w-8 opacity-40" />
      <div className="text-sm">{text}</div>
    </div>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null
  const message = error instanceof Error ? error.message : String(error)
  return (
    <div className="mb-3 flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
      <TriangleAlert className="h-4 w-4" />
      {message}
    </div>
  )
}

export function GsapNumber({
  value,
  format,
}: {
  value: number
  format?: (v: number) => string
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const display = format ?? ((v: number) => fmtQty(v))

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const mm = gsap.matchMedia()
    mm.add('(prefers-reduced-motion: no-preference)', () => {
      const proxy = { v: Number(el.dataset.last ?? 0) }
      const tween = gsap.to(proxy, {
        v: value,
        duration: 0.45,
        ease: 'power2.out',
        onUpdate: () => {
          el.textContent = display(proxy.v)
        },
      })
      return () => {
        tween.kill()
      }
    })
    el.dataset.last = String(value)
    return () => mm.revert()
  }, [value, display])

  return <span ref={ref} className="tabular">{display(value)}</span>
}

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <header className="mb-5 flex items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-400">{description}</p>}
      </div>
      {action}
    </header>
  )
}

export function ProductLink({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <Link to={`/products/${id}`} className="text-sky-300 hover:text-sky-200 hover:underline">
      {children}
    </Link>
  )
}

export function OrderLink({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <Link to={`/orders/${id}`} className="text-sky-300 hover:text-sky-200 hover:underline">
      {children}
    </Link>
  )
}
