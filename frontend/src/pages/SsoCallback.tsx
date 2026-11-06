import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { CheckCircle2, Loader2 } from 'lucide-react'
import { useApp } from '@/store/AppContext'
import { useI18n } from '@/i18n'
import { BrandMark } from '@/components/layout/AppShell'

export default function SsoCallback() {
  const location = useLocation()
  const navigate = useNavigate()
  const { login } = useApp()
  const { t } = useI18n()
  const [error, setError] = useState('')

  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const token = params.get('token')
    if (!token) { setError('Missing token'); return }
    login(token)
      .then(() => navigate('/', { replace: true }))
      .catch((e) => setError(String(e)))
  }, [location.search, login, navigate])

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="app-bg" />
      <div className="flex flex-col items-center gap-4 rounded-xl border bg-card/80 p-10 text-center shadow-soft backdrop-blur animate-scale-in">
        <BrandMark className="h-10 w-10 animate-float-slow" />
        {error ? (
          <><p className="text-sm text-destructive">{error}</p>
            <button className="text-xs text-primary underline" onClick={() => navigate('/login')}>{t('login.backToLogin')}</button></>
        ) : (
          <><Loader2 className="h-5 w-5 animate-spin text-primary" />
            <p className="text-sm text-muted-foreground">{t('login.signingIn')}</p>
            <p className="inline-flex items-center gap-1 text-[11px] text-success"><CheckCircle2 className="h-3 w-3" /> SSO</p></>
        )}
      </div>
    </div>
  )
}
