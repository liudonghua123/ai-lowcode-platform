import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { get as apiGet, getToken, setToken } from '@/lib/api'
import type { Bootstrap, User } from '@/types'

interface AppValue {
  user: User | null
  bootstrap: Bootstrap | null
  loading: boolean
  login: (token: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
  can: (permission: string) => boolean
}

const AppContext = createContext<AppValue>({
  user: null, bootstrap: null, loading: true,
  login: async () => {}, logout: () => {}, refresh: async () => {}, can: () => false,
})

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null)
  const [loading, setLoading] = useState(true)

  const clear = useCallback(() => {
    setToken('')
    setUser(null)
    setBootstrap(null)
  }, [])

  const refresh = useCallback(async () => {
    if (!getToken()) { setLoading(false); return }
    try {
      const [me, boot] = await Promise.all([
        apiGet<User>('/auth/me'),
        apiGet<Bootstrap>('/meta/bootstrap'),
      ])
      setUser(me)
      setBootstrap(boot)
    } catch {
      clear()
    } finally {
      setLoading(false)
    }
  }, [clear])

  const login = useCallback(async (token: string) => {
    setToken(token)
    setLoading(true)
    await refresh()
  }, [refresh])

  const logout = useCallback(() => { clear(); setLoading(false) }, [clear])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    const handler = () => clear()
    window.addEventListener('ailp:unauthorized', handler)
    return () => window.removeEventListener('ailp:unauthorized', handler)
  }, [clear])

  const can = useCallback((permission: string) => {
    if (!user) return false
    const perms = user.permissions || []
    if (perms.includes('*')) return true
    if (perms.includes(permission)) return true
    return perms.includes(`${permission.split(':')[0]}:*`)
  }, [user])

  const value = useMemo(() => ({ user, bootstrap, loading, login, logout, refresh, can }),
    [user, bootstrap, loading, login, logout, refresh, can])
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() { return useContext(AppContext) }
