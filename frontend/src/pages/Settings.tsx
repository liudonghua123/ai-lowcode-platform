import { useEffect, useState } from 'react'
import QRCode from 'qrcode'
import { useNavigate } from 'react-router-dom'
import {
  BookOpen, CheckCircle2, Copy, ExternalLink, Fingerprint, KeyRound, Languages,
  LockKeyhole, LogOut, Monitor, Moon, RefreshCw, Save, Settings2, ShieldCheck,
  Sun, Trash2, UserRound, UsersRound,
} from 'lucide-react'
import { PageHeader, SectionTitle } from '@/components/PageHeader'
import {
  Avatar, Badge, Button, Card, CardContent, Field, Input, Label, Segmented,
  Switch,
} from '@/components/ui/basic'
import { ConfirmDialog, Dialog, useToast } from '@/components/ui/overlay'
import { useI18n } from '@/i18n'
import { useTheme } from '@/theme/ThemeProvider'
import { useApp } from '@/store/AppContext'
import { del, get, post, put } from '@/lib/api'
import { copyText } from '@/lib/utils'
import { registerPasskey } from '@/lib/webauthn'

export default function Settings() {
  const { t, locale, setLocale } = useI18n()
  const { theme, setTheme } = useTheme()
  const { user, can, logout } = useApp()
  const { toast } = useToast()
  const navigate = useNavigate()

  const [oldPwd, setOldPwd] = useState(''), [newPwd, setNewPwd] = useState('')
  const [otpSetup, setOtpSetup] = useState<any>(null), [qr, setQr] = useState(''), [otpCode, setOtpCode] = useState('')
  const [otpOpen, setOtpOpen] = useState(false), [otpDisableOpen, setOtpDisableOpen] = useState(false)
  const [credentials, setCredentials] = useState<any[]>([])
  const [platformSettings, setPlatformSettings] = useState<any>(null)
  const [health, setHealth] = useState<any>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const load = async () => {
    try {
      const [c, s, h] = await Promise.all([
        get<{ credentials: any[] }>('/auth/passkey/credentials'),
        get<{ settings: any }>('/settings'),
        get<any>('/meta/health', { auth: false }),
      ])
      setCredentials(c.credentials || []); setPlatformSettings(s.settings || null); setHealth(h)
    } catch { /* optional */ }
  }
  useEffect(() => { void load() }, [])

  const changePassword = async () => {
    try { await post('/auth/change-password', { old_password: oldPwd, new_password: newPwd })
      setOldPwd(''); setNewPwd(''); toast(t('settings.passwordChanged'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
  }
  const startOtp = async () => {
    try { const s: any = await post('/auth/otp/setup', {})
      setOtpSetup(s); setQr(await QRCode.toDataURL(s.otpauth_uri, { width: 190, margin: 1,
        color: { dark: '#0f172a', light: '#ffffff' } })); setOtpOpen(true); setOtpCode('') }
    catch (e: any) { toast(e.message, 'error') }
  }
  const enableOtp = async () => {
    try { await post('/auth/otp/enable', { secret: otpSetup.secret, code: otpCode })
      setOtpOpen(false); toast(t('settings.otpEnabled'), 'success'); window.location.reload() }
    catch (e: any) { toast(e.message, 'error') }
  }
  const disableOtp = async () => {
    try { await post('/auth/otp/disable', { code: otpCode })
      setOtpDisableOpen(false); setOtpCode(''); toast(t('settings.otpDisabled'), 'success'); window.location.reload() }
    catch (e: any) { toast(e.message, 'error') }
  }
  const addPasskey = async () => {
    try {
      const opts: any = await post('/auth/passkey/register/options', {})
      const credential = await registerPasskey(opts.options)
      await post('/auth/passkey/register/verify', { challenge: opts.challenge, credential })
      toast(t('settings.passkeyEnabled'), 'success'); void load()
    } catch (e: any) { toast(e.message || 'Passkey registration failed', 'error') }
  }
  const removeCredential = async () => {
    if (!confirmDelete) return
    try { await del(`/auth/passkey/credentials/${encodeURIComponent(confirmDelete)}`); void load(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmDelete(null) }
  }
  const savePlatform = async () => {
    try { await put('/settings', platformSettings); toast(t('common.saved'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
  }

  const appearance = [
    { value: 'system' as const, label: t('common.system'), icon: <Monitor className="h-3 w-3" /> },
    { value: 'light' as const, label: t('common.light'), icon: <Sun className="h-3 w-3" /> },
    { value: 'dark' as const, label: t('common.dark'), icon: <Moon className="h-3 w-3" /> },
  ]

  return (
    <div className="mx-auto max-w-[1200px]">
      <PageHeader icon={<Settings2 className="h-5 w-5" />} title={t('settings.title')} subtitle={t('settings.subtitle')}
        actions={<Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>} />

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <Card><CardContent className="p-5">
            <SectionTitle>{t('settings.appearance')}</SectionTitle>
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div><p className="text-xs font-medium">{t('settings.locale')}</p><p className="text-[11px] text-muted-foreground">{t('settings.localeHint')}</p></div>
                <Segmented value={locale} onChange={setLocale} options={[
                  { value: 'en', label: 'English', icon: <Languages className="h-3 w-3" /> },
                  { value: 'zh', label: '中文' },
                ]} />
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div><p className="text-xs font-medium">{t('common.theme')}</p><p className="text-[11px] text-muted-foreground">{t('settings.themeHint')}</p></div>
                <Segmented value={theme} onChange={setTheme} options={appearance} />
              </div>
            </div>
          </CardContent></Card>

          <Card><CardContent className="p-5">
            <SectionTitle>{t('settings.profile')}</SectionTitle>
            <div className="flex items-center gap-3">
              <Avatar name={user?.display_name || user?.username} className="h-12 w-12 text-base" />
              <div className="min-w-0"><p className="text-sm font-medium">{user?.display_name || user?.username}</p>
                <p className="text-xs text-muted-foreground">{user?.email || '—'} · {user?.dept || '—'}</p></div>
              <Badge variant="secondary" className="ml-auto">{user?.provider || 'local'}</Badge>
            </div>
            <div className="mt-4 space-y-2">
              <p className="text-[11px] font-medium text-muted-foreground">{t('settings.userRoles')}</p>
              <div className="flex flex-wrap gap-1">{(user?.role_codes || []).map((r) => <Badge key={r} variant="default" className="capitalize">{r}</Badge>)}</div>
              <p className="mt-3 text-[11px] font-medium text-muted-foreground">{t('settings.userPermissions')} ({user?.permissions?.length ?? 0})</p>
              <div className="scroll-thin flex max-h-24 flex-wrap gap-1 overflow-y-auto">
                {(user?.permissions || []).map((p) => <Badge key={p} variant="outline" className="font-mono text-[9px]">{p}</Badge>)}
              </div>
            </div>
          </CardContent></Card>

          <Card><CardContent className="p-5">
            <SectionTitle>{t('settings.about')}</SectionTitle>
            <div className="space-y-2 text-xs">
              {[
                [t('common.version'), '0.1.0'], [t('settings.license'), 'MIT'],
                [t('settings.stack'), 'FastAPI · fastmcp · AgentScope · Vite'],
                [t('dashboard.api'), '/api/v1'], [t('dashboard.mcp'), health?.mcp?.mode || '/mcp'],
              ].map(([k, v]) => <div key={k} className="flex items-center justify-between gap-2 border-b pb-1.5 last:border-0">
                <span className="text-muted-foreground">{k}</span><span className="font-mono text-[10px]">{v}</span></div>)}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <a href="/docs" target="_blank" rel="noreferrer"><Button variant="outline" size="sm"><BookOpen className="h-3.5 w-3.5" />{t('settings.docs')}<ExternalLink className="h-3 w-3" /></Button></a>
              <Button variant="outline" size="sm" onClick={() => void load()}><ShieldCheck className="h-3.5 w-3.5" />{t('settings.health')}</Button>
              <Button variant="ghost" size="sm" className="ml-auto text-destructive"
                onClick={() => { logout(); navigate('/login') }}><LogOut className="h-3.5 w-3.5" />{t('settings.signOut')}</Button>
            </div>
          </CardContent></Card>
        </div>

        <div className="space-y-4">
          <Card><CardContent className="p-5">
            <SectionTitle>{t('settings.account')}</SectionTitle>
            <div className="space-y-3">
              <p className="text-xs font-medium">{t('settings.changePassword')}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                <Input type="password" placeholder={t('settings.oldPassword')} value={oldPwd} onChange={(e) => setOldPwd(e.target.value)} />
                <Input type="password" placeholder={t('settings.newPassword')} value={newPwd} onChange={(e) => setNewPwd(e.target.value)} />
              </div>
              <Button size="sm" onClick={changePassword} disabled={!oldPwd || newPwd.length < 8}><KeyRound className="h-3.5 w-3.5" />{t('settings.changePassword')}</Button>
            </div>
            <div className="my-4 border-t" />
            <div className="flex items-start gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary"><LockKeyhole className="h-4 w-4" /></span>
              <div className="min-w-0 flex-1"><p className="text-xs font-medium">{t('settings.otp')}</p>
                <p className="text-[11px] text-muted-foreground">{user?.otp_enabled ? t('settings.otpEnabled') : t('settings.otpDisabled')}</p></div>
              {user?.otp_enabled
                ? <Button variant="outline" size="sm" onClick={() => { setOtpCode(''); setOtpDisableOpen(true) }}>{t('settings.otpDisable')}</Button>
                : <Button size="sm" onClick={startOtp}>{t('settings.otpEnable')}</Button>}
            </div>
            <div className="mt-3 flex items-start gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary"><Fingerprint className="h-4 w-4" /></span>
              <div className="min-w-0 flex-1"><p className="text-xs font-medium">{t('settings.passkey')}</p>
                <p className="text-[11px] text-muted-foreground">{user?.passkey_enabled
                  ? t('settings.passkeyCount', { count: credentials.length }) : t('settings.passkeyDisabled')}</p></div>
              <Button size="sm" onClick={addPasskey}>{t('settings.addPasskey')}</Button>
            </div>
            {!!credentials.length && <div className="mt-3 space-y-1.5">
              {credentials.map((c: any) => <div key={c.id} className="flex items-center gap-2 rounded-md border px-2.5 py-1.5">
                <Fingerprint className="h-3.5 w-3.5 text-primary" />
                <span className="min-w-0 flex-1 truncate font-mono text-[10px]">{String(c.id).slice(0, 26)}…</span>
                <span className="text-[9px] text-muted-foreground">{c.created_at?.slice(0, 10)}</span>
                <Button variant="ghost" size="icon-sm" onClick={() => setConfirmDelete(c.id)}><Trash2 className="h-3 w-3 text-destructive" /></Button>
              </div>)}
            </div>}
            <p className="mt-3 text-[10px] leading-relaxed text-muted-foreground">{t('settings.passkeyNote')}</p>
          </CardContent></Card>

          {can('settings:write') && platformSettings && <Card><CardContent className="p-5">
            <SectionTitle>{t('settings.platform')}</SectionTitle>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t('settings.defaultLocale')}><Segmented value={platformSettings.default_locale || 'en'}
                onChange={(v) => setPlatformSettings({ ...platformSettings, default_locale: v })}
                options={[{ value: 'en', label: 'EN' }, { value: 'zh', label: '中文' }]} /></Field>
              <Field label={t('settings.defaultTheme')}><Segmented value={platformSettings.default_theme || 'system'}
                onChange={(v) => setPlatformSettings({ ...platformSettings, default_theme: v })} options={appearance} /></Field>
              <Field label={t('settings.auditRetention')}><Input type="number" value={platformSettings.audit_retention_days}
                onChange={(e) => setPlatformSettings({ ...platformSettings, audit_retention_days: Number(e.target.value) })} /></Field>
              <Field label={t('settings.passwordMin')}><Input type="number" value={platformSettings.password_min_length}
                onChange={(e) => setPlatformSettings({ ...platformSettings, password_min_length: Number(e.target.value) })} /></Field>
              <Field label={t('settings.sessionIdle')}><Input type="number" value={platformSettings.session_idle_minutes}
                onChange={(e) => setPlatformSettings({ ...platformSettings, session_idle_minutes: Number(e.target.value) })} /></Field>
              <div className="flex items-center justify-between rounded-lg border px-3 py-2"><span className="text-xs">{t('settings.allowSignup')}</span>
                <Switch checked={!!platformSettings.allow_signup} onCheckedChange={(v) => setPlatformSettings({ ...platformSettings, allow_signup: v })} /></div>
            </div>
            <Button size="sm" className="mt-3" onClick={savePlatform}><Save className="h-3.5 w-3.5" />{t('common.save')}</Button>
          </CardContent></Card>}
        </div>
      </div>

      <Dialog open={otpOpen} onOpenChange={setOtpOpen} title={t('settings.otpEnable')}
        description={t('settings.otpHint')} size="sm"
        footer={<><Button variant="outline" onClick={() => setOtpOpen(false)}>{t('common.cancel')}</Button>
          <Button onClick={enableOtp} disabled={otpCode.length !== 6}>{t('login.verify')}</Button></>}>
        {otpSetup && <div className="space-y-3">
          <div className="flex items-center gap-4">
            {qr && <img src={qr} alt="OTP QR" className="h-32 w-32 rounded-lg border bg-white p-1" />}
            <div className="min-w-0"><p className="text-[11px] text-muted-foreground">{t('settings.otpSecret')}</p>
              <p className="break-all font-mono text-xs">{otpSetup.secret}</p>
              <Button variant="ghost" size="sm" className="mt-2 h-7 text-xs" onClick={() => void copyText(otpSetup.otpauth_uri)}><Copy className="h-3 w-3" />{t('common.copy')}</Button></div>
          </div>
          <Field label={t('settings.otpCode')}><Input value={otpCode} onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ''))}
            inputMode="numeric" maxLength={6} className="text-center font-mono tracking-[.4em]" placeholder="000000" /></Field>
        </div>}
      </Dialog>

      <Dialog open={otpDisableOpen} onOpenChange={setOtpDisableOpen} title={t('settings.otpDisable')} size="sm"
        footer={<><Button variant="outline" onClick={() => setOtpDisableOpen(false)}>{t('common.cancel')}</Button><Button variant="destructive" onClick={disableOtp}>{t('common.confirm')}</Button></>}>
        <Field label={t('settings.otpCode')}><Input value={otpCode} onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ''))}
          inputMode="numeric" maxLength={6} className="text-center font-mono tracking-[.4em]" /></Field>
      </Dialog>
      <ConfirmDialog open={!!confirmDelete} onOpenChange={() => setConfirmDelete(null)}
        title={t('common.confirmDelete')} onConfirm={removeCredential} />
    </div>
  )
}
