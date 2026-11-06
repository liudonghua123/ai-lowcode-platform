import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { ThemeMode } from '@/types'

interface ThemeValue {
  theme: ThemeMode
  resolved: 'light' | 'dark'
  setTheme: (t: ThemeMode) => void
}
const ThemeContext = createContext<ThemeValue>({ theme: 'system', resolved: 'light', setTheme: () => {} })
const STORAGE_KEY = 'ailp_theme'

function systemPrefersDark() {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches
}

export function ThemeProvider({ children, defaultTheme = 'system' }: { children: ReactNode; defaultTheme?: ThemeMode }) {
  const [theme, setThemeState] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved === 'light' || saved === 'dark' || saved === 'system' ? saved : defaultTheme
  })
  const [systemDark, setSystemDark] = useState(systemPrefersDark)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  const resolved: 'light' | 'dark' = theme === 'system' ? (systemDark ? 'dark' : 'light') : theme

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', resolved === 'dark')
    root.style.colorScheme = resolved
    const meta = document.querySelector('meta[name="theme-color"]')
    if (meta) meta.setAttribute('content', resolved === 'dark' ? '#0d1220' : '#ffffff')
  }, [resolved])

  const setTheme = useCallback((t: ThemeMode) => {
    setThemeState(t)
    localStorage.setItem(STORAGE_KEY, t)
  }, [])

  const value = useMemo(() => ({ theme, resolved, setTheme }), [theme, resolved, setTheme])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() { return useContext(ThemeContext) }
