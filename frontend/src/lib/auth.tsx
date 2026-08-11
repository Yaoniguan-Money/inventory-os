import { createContext, useContext, useEffect, useState } from 'react'
import { api, getToken, setToken } from './api.ts'

interface Me {
  user: { id: string; email: string; display_name: string }
  organization: { id: string; name: string; slug: string; default_currency: string }
  role: string
  scopes: string[]
}

interface AuthContextValue {
  user: Me | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  hasScope: (scope: string) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!getToken()) {
      setLoading(false)
      return
    }
    api
      .get<Me>('/auth/me')
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false))
  }, [])

  async function login(email: string, password: string) {
    const data = await api.post<{
      access_token: string
      user: Me['user']
      organization: Me['organization']
      role: string
      scopes?: string[]
    }>('/auth/login', { email, password })
    setToken(data.access_token)
    setUser({
      user: data.user,
      organization: data.organization,
      role: data.role,
      scopes: data.scopes ?? [],
    })
  }

  function logout() {
    setToken(null)
    setUser(null)
  }

  return (
    <AuthContext.Provider
      value={{ user, loading, login, logout, hasScope: (s) => user?.scopes.includes(s) ?? false }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
