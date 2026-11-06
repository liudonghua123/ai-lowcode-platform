import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import QRCode from 'qrcode'
import {
  ArrowRight, Bot, CheckCircle2, Fingerprint, GitBranch, KeyRound, Languages,
  LockKeyhole, Monitor, Moon, ShieldCheck, Sun, UserRound, Workflow,
} from 'lucide-react'
import { BrandMark } from '@/components/layout/AppShell'
import { Button, Input, Label, Separator } from '@/components/ui/basic'
import { useToast } from '@/components/ui/overlay'
import { useI18n } from '@/i18n'
import { useTheme } from '@/theme/ThemeProvider'
import { useApp } from '@/store/AppContext'
import { get, post } from '@/lib/api'
import { authenticatePasskey } from '@/lib/webauthn'
import { cn } from '@/lib/utils'

const DEMO = [
  { user: 'admin', pass: 'admin123', role: 'admin' },
  { user: 'alice', pass: 'demo1234', role: 'developer' },
  { user: 'bob', pass: 'demo1234', role: 'operator' },
  { user: 'carol', pass: 'demo1234', role: 'viewer' },
]

type Step = 'login' | 'mfa' | 'enroll'
interface Provider { code: string; name: string; demo: boolean; type: string }

export default function Login() {
  const { t, locale, setLocale } = useI18n()
  const { theme, setTheme } = useTheme()
  const { login } = useApp()
  const { toast } = useToast()
  const navigate = useNavigate()

  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('admin123')
  const [otpInline, setOtpInline] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [step, setStep] = useState<Step>('login')
  const [mfaToken, setMfaToken] = useState('')
  const [enrollToken, setEnrollToken] = useState('')
  const [methods, setMethods] = useState<string[]>([])
  const [code, setCode] = useState('')
  const [providers, setProviders] = useState<Provider[]>([])
  const [otpSetup, setOtpSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [qr, setQr] = useState('')

  useEffect(() => {
    get<{ providers: Provider[] }>('/auth/providers', { auth: false })
      .then((r) => setProviders(r.providers || []))
      .catch(() => setProviders([]))
  }, [])

  const finish = async (token?: string) => {
    if (!token) throw new Error('No token returned')
    await login(token)
    navigate('/', { replace: true })
  }
  const authHeader = (token: string) => ({ auth: false, headers: { Authorization: `Bearer ${token}` } })

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(''); setLoading(true)
    try {
      const r: any = await post('/auth/login',
        { username, password, otp_code: otpInline || undefined }, { auth: false })
      if (r.access_token) return await finish(r.access_token)
      if (r.mfa_required) {
        setMfaToken(r.mfa_token); setMethods(r.methods || [])
        setEnrollToken(r.enroll_token || '')
        setStep(r.enrollment_required ? 'enroll' : 'mfa')
        if (r.enrollment_required) void prepareEnroll(r.enroll_token)
        return
      }
      setError(t('login.invalid'))
    } catch (err: any) {
      setError(err?.message || t('login.invalid'))
    } finally { setLoading(false) }
  }

  const prepareEnroll = async (token: string) => {
    try {
      const s: any = await post('/auth/otp/setup', {}, authHeader(token))
      setOtpSetup({ secret: s.secret, otpauth_uri: s.otpauth_uri })
      setQr(await QRCode.toDataURL(s.otpauth_uri, { width: 180, margin: 1,
        color: { dark: '#0f172a', light: '#ffffff' } }))
    } catch (err: any) { setError(err?.message || 'Setup failed') }
  }

  const verifyMfa = async (method: 'otp' | 'passkey') => {
    setError(''); setLoading(true)
    try {
      let payload: any = { mfa_token: mfaToken, method }
      if (method === 'otp') payload.code = code
      else {
        const opts: any = await post('/auth/passkey/authenticate/options', { username }, { auth: false })
        const credential = await authenticatePasskey(opts.options)
        payload = { ...payload, challenge: opts.challenge, credential }
      }
      const r: any = await post('/auth/mfa/verify', payload, { auth: false })
      await finish(r.access_token)
    } catch (err: any) { setError(err?.message || t('login.mfaFailed')) }
    finally { setLoading(false) }
  }

  const confirmEnroll = async () => {
    if (!otpSetup) return
    setError(''); setLoading(true)
    try {
      await post('/auth/otp/enable', { secret: otpSetup.secret, code }, authHeader(enrollToken))
      toast(t('common.saved'), 'success', t('login.backToLogin'))
      setStep('login'); setCode(''); setOtpSetup(null); setQr(''); setPassword('')
    } catch (err: any) { setError(err?.message || 'Verification failed') }
    finally { setLoading(false) }
  }

  const passkeyLogin = async () => {
    setError(''); setLoading(true)
    try {
      const opts: any = await post('/auth/passkey/authenticate/options', { username }, { auth: false })
      const credential = await authenticatePasskey(opts.options)
      const r: any = await post('/auth/passkey/authenticate/verify',
        { challenge: opts.challenge, credential, username }, { auth: false })
      await finish(r.access_token)
    } catch (err: any) { setError(err?.message || 'Passkey sign-in failed') }
    finally { setLoading(false) }
  }

  const ssoLogin = async (p: Provider) => {
    setError(''); setLoading(true)
    try {
      const r: any = await get(`/auth/sso/${p.code}/authorize`, { auth: false })
      if (r.demo) {
        const cb: any = await post(`/auth/sso/${p.code}/callback`,
          { state: r.state, code: 'demo-code' }, { auth: false })
        await finish(cb.access_token)
      } else {
        window.location.href = r.url
      }
    } catch (err: any) { setError(err?.message || 'SSO failed'); setLoading(false) }
  }

  const features = [
    { icon: <Workflow className="h-4 w-4" />, text: t('login.feature1') },
    { icon: <ShieldCheck className="h-4 w-4" />, text: t('login.feature2') },
    { icon: <Bot className="h-4 w-4" />, text: t('login.feature3') },
  ]

  return (
    <div className="relative flex min-h-screen items-stretch">
      <div className="app-bg" />
      {/* Hero */}
      <div className="relative hidden w-1/2 flex-col justify-between overflow-hidden border-r bg-card/40 px-12 py-10 lg:flex">
        <div className="pointer-events-none absolute -left-24 top-1/3 h-80 w-80 rounded-full bg-primary/10 blur-3xl animate-float-slow" />
        <div className="pointer-events-none absolute right-0 top-10 h-72 w-72 rounded-full bg-cyan-400/10 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <BrandMark className="h-10 w-10" />
          <div>
            <p className="font-semibold tracking-tight">{t('nav.platform')}</p>
            <p className="text-xs text-muted-foreground">{t('nav.version')} · MIT</p>
          </div>
        </div>
        <div className="relative max-w-lg animate-fade-up">
          <div className="mb-6 inline-flex items-center gap-1.5 rounded-full border bg-background/60 px-3 py-1 text-[11px] text-muted-foreground backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full bg-success" /> {t('nav.online')}
          </div>
          <h1 className="text-4xl font-semibold leading-tight tracking-tight xl:text-5xl">
            {(() => {
              const [before, after] = t('login.heroTitle').split('AI')
              return <>{before}<span className="gradient-text">AI</span>{after}</>
            })()}
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-muted-foreground">{t('login.heroSubtitle')}</p>
          <div className="mt-8 space-y-3">
            {features.map((f, i) => (
              <div key={i} className="flex items-center gap-3 rounded-lg border bg-background/50 px-3 py-2.5 text-sm backdrop-blur transition-transform hover:translate-x-1">
                <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">{f.icon}</span>
                {f.text}
                <CheckCircle2 className="ml-auto h-3.5 w-3.5 text-success" />
              </div>
            ))}
          </div>
          <svg viewBox="0 0 420 120" className="mt-10 w-full opacity-70" aria-hidden="true">
            <defs><linearGradient id="flowGrad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="hsl(var(--primary))" /><stop offset="100%" stopColor="hsl(190 85% 50%)" />
            </linearGradient></defs>
            <g stroke="url(#flowGrad)" strokeWidth="2" fill="none" strokeDasharray="5 5">
              <path d="M20 60 H110 M110 60 C140 60 140 25 170 25 H250 M110 60 C140 60 140 95 170 95 H250 M250 25 C280 25 280 60 310 60 H400 M250 95 C280 95 280 60 310 60" />
            </g>
            {[[20, 60], [110, 60], [250, 25], [250, 95], [310, 60], [400, 60]].map(([x, y], i) => (
              <g key={i}>
                <circle cx={x} cy={y} r="10" fill="hsl(var(--card))" stroke="url(#flowGrad)" strokeWidth="2.5" />
                <circle cx={x} cy={y} r="3" fill="hsl(var(--primary))" />
              </g>
            ))}
          </svg>
        </div>
        <p className="relative text-xs text-muted-foreground">© 2026 · {t('settings.license')} · FastAPI + Vite</p>
      </div>

      {/* Form */}
      <div className="relative flex flex-1 flex-col items-center justify-center px-4 py-10">
        <div className="absolute right-4 top-4 flex items-center gap-1.5">
          <Button variant="ghost" size="sm" className="gap-1.5" onClick={() => setLocale(locale === 'en' ? 'zh' : 'en')}>
            <Languages className="h-4 w-4" />{locale === 'en' ? 'EN' : '中文'}
          </Button>
          <Button variant="ghost" size="icon" title={t('common.theme')}
            onClick={() => setTheme(theme === 'system' ? 'light' : theme === 'light' ? 'dark' : 'system')}>
            {theme === 'light' ? <Sun className="h-4 w-4" /> : theme === 'dark' ? <Moon className="h-4 w-4" /> : <Monitor className="h-4 w-4" />}
          </Button>
        </div>

        <div className="w-full max-w-[26rem] animate-fade-up">
          <div className="mb-7 flex items-center gap-2.5 lg:hidden">
            <BrandMark /><span className="font-semibold">{t('nav.platform')}</span>
          </div>

          {step === 'login' && (
            <>
              <h2 className="text-2xl font-semibold tracking-tight">{t('login.title')}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{t('login.subtitle')}</p>
              <form onSubmit={handleSubmit} className="mt-6 space-y-4">
                <div className="space-y-1.5">
                  <Label>{t('login.username')}</Label>
                  <div className="relative">
                    <UserRound className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input className="pl-9" value={username} onChange={(e) => setUsername(e.target.value)} required autoComplete="username" />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label>{t('login.password')}</Label>
                  <div className="relative">
                    <LockKeyhole className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input className="pl-9" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
                  </div>
                </div>
                {error && <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">{error}</p>}
                <Button type="submit" className="w-full" loading={loading}>
                  {!loading && <ArrowRight className="h-4 w-4" />}{loading ? t('login.signingIn') : t('login.signIn')}
                </Button>
              </form>

              <div className="mt-5">
                <p className="mb-2 text-[11px] font-medium text-muted-foreground">{t('login.demoAccounts')}</p>
                <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
                  {DEMO.map((d) => (
                    <button key={d.user} type="button" onClick={() => { setUsername(d.user); setPassword(d.pass); setError('') }}
                      className={cn('rounded-md border px-2 py-2 text-center transition-all hover:border-primary/40 hover:bg-primary/5',
                        username === d.user && 'border-primary/50 bg-primary/10')}>
                      <span className="block text-xs font-medium">{d.user}</span>
                      <span className="block text-[10px] text-muted-foreground">{d.role}</span>
                    </button>
                  ))}
                </div>
              </div>

              {providers.length > 0 && (
                <>
                  <div className="my-5 flex items-center gap-3"><Separator /><span className="shrink-0 text-[11px] text-muted-foreground">{t('login.ssoTitle')}</span><Separator /></div>
                  <div className="flex flex-wrap gap-2">
                    {providers.map((p) => (
                      <Button key={p.code} type="button" variant="outline" size="sm" className="flex-1" onClick={() => ssoLogin(p)} disabled={loading}>
                        <KeyRound className="h-3.5 w-3.5" />{p.name.split(' / ')[0]}
                        {p.demo && <span className="text-[9px] text-muted-foreground">· {t('login.ssoDemo')}</span>}
                      </Button>
                    ))}
                  </div>
                </>
              )}

              <div className="mt-4 flex items-center justify-between">
                <Button type="button" variant="ghost" size="sm" className="gap-1.5 text-xs" onClick={passkeyLogin} disabled={loading}>
                  <Fingerprint className="h-3.5 w-3.5" />{t('login.passkeyBtn')}
                </Button>
                <div className="relative w-28">
                  <Input className="h-8 text-xs" placeholder="OTP (optional)" inputMode="numeric" maxLength={6}
                    value={otpInline} onChange={(e) => setOtpInline(e.target.value.replace(/\D/g, ''))} />
                </div>
              </div>
              <p className="mt-5 text-center text-[11px] text-muted-foreground">{t('login.secure')}</p>
            </>
          )}

          {step === 'mfa' && (
            <div className="rounded-xl border bg-card/80 p-6 shadow-soft backdrop-blur animate-scale-in">
              <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 text-primary"><ShieldCheck className="h-5 w-5" /></div>
              <h2 className="text-xl font-semibold">{t('login.mfaTitle')}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{t('login.mfaSubtitle')}</p>
              {methods.includes('otp') && (
                <div className="mt-5 space-y-2">
                  <Label>{t('login.otpCode')}</Label>
                  <Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                    inputMode="numeric" maxLength={6} className="text-center font-mono text-lg tracking-[.5em]" placeholder="000000" />
                  <Button className="w-full" loading={loading} onClick={() => verifyMfa('otp')} disabled={code.length !== 6}>{t('login.verify')}</Button>
                </div>
              )}
              {methods.includes('passkey') && (
                <Button variant="outline" className="mt-3 w-full" onClick={() => verifyMfa('passkey')} disabled={loading}>
                  <Fingerprint className="h-4 w-4" />{t('login.passkeyBtn')}
                </Button>
              )}
              {error && <p className="mt-3 text-xs text-destructive">{error}</p>}
              <Button variant="link" className="mt-4 w-full" onClick={() => { setStep('login'); setError(''); setCode('') }}>{t('login.backToLogin')}</Button>
            </div>
          )}

          {step === 'enroll' && (
            <div className="rounded-xl border bg-card/80 p-6 shadow-soft backdrop-blur animate-scale-in">
              <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-warning/15 text-warning"><KeyRound className="h-5 w-5" /></div>
              <h2 className="text-xl font-semibold">{t('login.enrollmentTitle')}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{t('login.enrollmentSubtitle')}</p>
              {otpSetup && (
                <div className="mt-5 space-y-3">
                  <div className="flex items-center gap-4">
                    {qr && <img src={qr} alt="OTP QR code" className="h-28 w-28 rounded-lg border bg-white p-1" />}
                    <div className="min-w-0 flex-1">
                      <p className="text-[11px] text-muted-foreground">{t('settings.otpSecret')}</p>
                      <p className="break-all font-mono text-xs">{otpSetup.secret}</p>
                    </div>
                  </div>
                  <Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                    inputMode="numeric" maxLength={6} placeholder={t('login.otpCode')} className="text-center font-mono tracking-[.4em]" />
                  <Button className="w-full" loading={loading} onClick={confirmEnroll} disabled={code.length !== 6}>{t('login.setupOtp')}</Button>
                </div>
              )}
              {error && <p className="mt-3 text-xs text-destructive">{error}</p>}
              <Button variant="link" className="mt-4 w-full" onClick={() => { setStep('login'); setError('') }}>{t('login.backToLogin')}</Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
