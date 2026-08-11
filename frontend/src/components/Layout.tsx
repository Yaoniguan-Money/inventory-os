import {
  Boxes,
  ClipboardList,
  FileText,
  Gauge,
  LayoutDashboard,
  LogOut,
  Package,
  Settings,
  ShoppingCart,
  Sparkles,
  TrendingUp,
  Wrench,
} from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../lib/auth.tsx'
import { useEventStream } from '../lib/sse.ts'

const NAV = [
  { to: '/', label: '经营驾驶舱', icon: LayoutDashboard, end: true },
  { to: '/products', label: '商品中心', icon: Package },
  { to: '/orders', label: '订单中心', icon: ShoppingCart },
  { to: '/inventory', label: '仓库中心', icon: Boxes },
  { to: '/purchasing', label: '采购中心', icon: ClipboardList },
  { to: '/market', label: '市场行情', icon: TrendingUp },
  { to: '/health', label: '风险中心', icon: Gauge },
  { to: '/equipment', label: '设备维护', icon: Wrench },
  { to: '/knowledge', label: '企业知识库', icon: FileText },
  { to: '/assistant', label: '员工助手', icon: Sparkles },
]

export default function Layout() {
  const { user, logout } = useAuth()
  useEventStream()

  return (
    <div className="flex min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-40 flex w-56 flex-col border-r border-slate-800/80 bg-[#0d1119]/95">
        <div className="flex items-center gap-2 px-4 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-600/20 text-sky-300">
            <Gauge className="h-5 w-5" />
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-100">InventoryOS</div>
            <div className="text-[11px] text-slate-500">{user?.organization.name}</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={'end' in item ? item.end : false}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? 'bg-sky-500/10 text-sky-300'
                    : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                }`
              }
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-800/80 p-3">
          <NavLink
            to="/settings"
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
          >
            <Settings className="h-4 w-4" />
            集成与设置
          </NavLink>
          <div className="mt-2 flex items-center justify-between rounded-lg bg-slate-800/40 px-3 py-2">
            <div className="min-w-0">
              <div className="truncate text-xs text-slate-300">{user?.user.display_name}</div>
              <div className="text-[11px] text-slate-500">{user?.role}</div>
            </div>
            <button onClick={logout} title="退出登录" className="text-slate-500 hover:text-red-300">
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>
      <main className="ml-56 flex-1 px-6 py-5">
        <div className="mx-auto max-w-7xl">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
