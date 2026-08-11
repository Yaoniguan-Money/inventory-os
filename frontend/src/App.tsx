import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './lib/auth.tsx'
import Layout from './components/Layout.tsx'
import LoginPage from './pages/LoginPage.tsx'
import DashboardPage from './pages/DashboardPage.tsx'
import ProductsPage from './pages/ProductsPage.tsx'
import ProductDetailPage from './pages/ProductDetailPage.tsx'
import OrdersPage from './pages/OrdersPage.tsx'
import OrderDetailPage from './pages/OrderDetailPage.tsx'
import InventoryPage from './pages/InventoryPage.tsx'
import PurchasingPage from './pages/PurchasingPage.tsx'
import MarketPage from './pages/MarketPage.tsx'
import HealthPage from './pages/HealthPage.tsx'
import EquipmentPage from './pages/EquipmentPage.tsx'
import EquipmentDetailPage from './pages/EquipmentDetailPage.tsx'
import KnowledgePage from './pages/KnowledgePage.tsx'
import AssistantPage from './pages/AssistantPage.tsx'
import SettingsPage from './pages/SettingsPage.tsx'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-400">
        加载中…
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="products" element={<ProductsPage />} />
        <Route path="products/:productId" element={<ProductDetailPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="orders/:orderId" element={<OrderDetailPage />} />
        <Route path="inventory" element={<InventoryPage />} />
        <Route path="purchasing" element={<PurchasingPage />} />
        <Route path="market" element={<MarketPage />} />
        <Route path="health" element={<HealthPage />} />
        <Route path="equipment" element={<EquipmentPage />} />
        <Route path="equipment/:equipmentId" element={<EquipmentDetailPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="assistant" element={<AssistantPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}
