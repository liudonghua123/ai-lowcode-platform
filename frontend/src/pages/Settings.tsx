import { useEffect, useState, type ReactNode } from 'react'
import QRCode from 'qrcode'
import { useNavigate } from 'react-router-dom'
import {
  ArrowRight, BookOpen, CheckCircle2, Copy, DownloadCloud, ExternalLink, Eye,
  Fingerprint, KeyRound, Languages, Layers, ListFilter, LockKeyhole, LogOut,
  Mic, Monitor, Moon, RefreshCw, Save, Settings2, ShieldCheck, Sparkles, Sun,
  Trash2, UserRound, UsersRound, Volume2,
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
import type { AiSettingsView, ModelCategory } from '@/types'

type AiDraft = { base_url: string; model: string; api_key: string; enabled: boolean }

const CATEGORY_ICONS: Record<ModelCategory, ReactNode> = {
  llm: <Sparkles className="h-3.5 w-3.5" />,
  asr: <Mic className="h-3.5 w-3.5" />,
  tts: <Volume2 className="h-3.5 w-3.5" />,
  embedding: <Layers className="h-3.5 w-3.5" />,
  rerank: <ListFilter className="h-3.5 w-3.5" />,
  vision: <Eye className="h-3.5 w-3.5" />,
}

function draftOf(view: AiSettingsView): Record<string, AiDraft> {
  return Object.fromEntries(view.categories.map((c) => [c.category, {
    base_url: c.base_url, model: c.model, api_key: '', enabled: c.enabled,
  }])) as Record<string, AiDraft>
}

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
  const [ai, setAi] = useState<AiSettingsView | null>(null)
  const [aiDraft, setAiDraft] = useState<Record<string, AiDraft>>({})
  const [aiSaving, setAiSaving] = useState(false)
  const canWrite = can('settings:write')

  const load = async () => {
    try {
      const [c, s, h] = await Promise.all([
        get<{ credentials: any[] }>('/auth/passkey/credentials'),
        get<{ settings: any }>('/settings'),
        get<any>('/meta/health', { auth: false }),
      ])
      setCredentials(c.credentials || []); setPlatformSettings(s.settings || null); setHealth(h)
    } catch { /* optional */ }
    try {
      const r = await get<AiSettingsView>('/settings/ai')
      setAi(r); setAiDraft(draftOf(r))
    } catch { /* requires settings:read */ }
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
  const saveAi = async () => {
    if (!ai) return
    setAiSaving(true)
    try {
      const r = await put<AiSettingsView>('/settings/ai', {
        items: ai.categories.map((c) => ({ category: c.category, ...(aiDraft[c.category] || {}) })),
      })
      setAi(r); setAiDraft(draftOf(r)); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
    finally { setAiSaving(false) }
  }
  const loadAiEnv = () => {
    if (!ai) return
    setAiDraft(Object.fromEntries(ai.categories.map((c) => [c.category, {
      base_url: c.env.base_url || c.base_url,
      model: c.env.model || c.model,
      api_key: '',
      enabled: c.env.configured ? true : c.enabled,
    }])) as Record<string, AiDraft>)
    toast(t('settings.aiEnvLoaded'), 'success')
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

      {ai && <Card className="mt-4"><CardContent className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <SectionTitle>{t('settings.aiTitle')}</SectionTitle>
            <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-muted-foreground">{t('settings.aiHint')}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="font-mono text-[9px]">
              {t('settings.aiRuntime')}: {ai.runtime.provider} · {ai.runtime.model}
            </Badge>
            <Button variant="outline" size="sm" onClick={loadAiEnv} disabled={!canWrite}>
              <DownloadCloud className="h-3.5 w-3.5" />{t('settings.aiLoadEnv')}
            </Button>
            <Button size="sm" onClick={saveAi} disabled={!canWrite || aiSaving}>
              <Save className="h-3.5 w-3.5" />{t('common.save')}
            </Button>
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {ai.categories.map((c) => {
            const draft: AiDraft = aiDraft[c.category] || {
              base_url: c.base_url, model: c.model, api_key: '', enabled: c.enabled,
            }
            const set = (patch: Partial<AiDraft>) =>
              setAiDraft((prev) => ({ ...prev, [c.category]: { ...draft, ...patch } }))
            return (
              <div key={c.category} className="rounded-xl border p-3">
                <div className="flex items-center gap-1.5">
                  <span className="text-primary">{CATEGORY_ICONS[c.category]}</span>
                  <p className="text-xs font-medium">{locale === 'zh' ? c.label_zh : c.label}</p>
                  <Badge variant={c.source === 'env' ? 'secondary' : c.source === 'manual' ? 'default' : 'outline'}
                    className="ml-auto text-[9px]">
                    {c.source === 'env' ? t('settings.aiSourceEnv')
                      : c.source === 'manual' ? t('settings.aiSourceManual') : t('settings.aiSourceNone')}
                  </Badge>
                  <Switch checked={draft.enabled} disabled={!canWrite}
                    onCheckedChange={(v) => set({ enabled: v })} />
                </div>
                <div className="mt-2 space-y-1.5">
                  <Input className="h-8 font-mono text-[10px]"
                    placeholder={c.vendor === 'local' ? 'n/a' : (c.env.base_url || 'https://api.openai.com/v1')}
                    value={draft.base_url} disabled={!canWrite}
                    onChange={(e) => set({ base_url: e.target.value })} />
                  <Input className="h-8 font-mono text-[10px]" placeholder={c.env.model || c.default_model}
                    value={draft.model} disabled={!canWrite}
                    onChange={(e) => set({ model: e.target.value })} />
                  <Input className="h-8 font-mono text-[10px]" type="password" autoComplete="new-password"
                    placeholder={c.has_api_key
                      ? `${t('settings.aiKeySet')} · ${c.api_key_masked}`
                      : t('settings.aiKeyMissing')}
                    value={draft.api_key} disabled={!canWrite}
                    onChange={(e) => set({ api_key: e.target.value })} />
                </div>
                <div className="mt-1.5 flex items-center justify-between gap-2">
                  {c.env.configured
                    ? <p className="truncate text-[10px] text-muted-foreground">
                      {t('settings.aiEnvConfigured', { model: c.env.model || c.env.base_url })}</p>
                    : <span />}
                  {c.source === 'manual' && !c.ready && (
                    <span className="shrink-0 text-[10px] text-amber-600 dark:text-amber-400">
                      {t('settings.aiIncomplete')}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <p className="font-mono text-[10px] text-muted-foreground">backend/.env → {ai.runtime.config_source}</p>
          <Button variant="ghost" size="sm" onClick={() => navigate('/models')}>
            {t('settings.aiManage')}<ArrowRight className="h-3 w-3" />
          </Button>
        </div>
      </CardContent></Card>}

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
