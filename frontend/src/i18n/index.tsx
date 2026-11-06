import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Locale } from '@/types'
import { translate } from './locales'

interface I18nValue {
  locale: Locale
  setLocale: (l: Locale) => void
  t: (key: string, vars?: Record<string, string | number>) => string
}

const I18nContext = createContext<I18nValue>({
  locale: 'en', setLocale: () => {}, t: (k) => k,
})

const STORAGE_KEY = 'ailp_locale'

export function I18nProvider({ children, defaultLocale = 'en' }: { children: ReactNode; defaultLocale?: Locale }) {
  const [locale, setLocaleState] = useState<Locale>(() => {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved === 'zh' || saved === 'en' ? saved : defaultLocale
  })

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l)
    localStorage.setItem(STORAGE_KEY, l)
  }, [])

  useEffect(() => {
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en'
  }, [locale])

  const t = useCallback((key: string, vars?: Record<string, string | number>) =>
    translate(locale, key, vars), [locale])

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() { return useContext(I18nContext) }
