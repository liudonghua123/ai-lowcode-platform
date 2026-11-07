import { useEffect, useState } from 'react'
import {
  CheckCircle2, Copy, Fingerprint, KeyRound, LockKeyhole, RefreshCw,
  Save, Settings2, ShieldCheck, XCircle,
} from 'lucide-react'
import { PageHeader, SectionTitle } from '@/components/PageHeader'
import {
  Badge, Button, Card, CardContent, Field, Input, Label, Switch,
} from '@/components/ui/basic'
import { Dialog, Tabs, useToast } from '@/components/ui/overlay'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { get, put } from '@/lib/api'
import { copyText } from '@/lib/utils'
import type { AuthProvider, MfaPolicy, Role } from '@/types'

const FIELDS: Record<string, { key: string; label: string; secret?: boolean }[]> = {
  cas: [{ key: 'server_url', label: 'authSettings.serverUrl' }, { key: 'version', label: 'authSettings.version' }],
  oauth2: [
    { key: 'client_id', label: 'authSettings.clientId' }, { key: 'client_secret', label: 'authSettings.clientSecret', secret: true },
    { key: 'authorize_url', label: 'authSettings.authorizeUrl' }, { key: 'token_url', label: 'authSettings.tokenUrl' },
    { key: 'userinfo_url', label: 'authSettings.userinfoUrl' }, { key: 'scope', label: 'authSettings.scope' },
  ],
  oidc: [
    { key: 'issuer', label: 'authSettings.issuer' }, { key: 'discovery_url', label: 'authSettings.discoveryUrl' },
    { key: 'client_id', label: 'authSettings.clientId' }, { key: 'client_secret', label: 'authSettings.clientSecret', secret: true },
    { key: 'scope', label: 'authSettings.scope' },
  ],
  wecom: [
    { key: 'corp_id', label: 'authSettings.corpId' }, { key: 'agent_id', label: 'authSettings.agentId' },
    { key: 'secret', label: 'authSettings.secret', secret: true },
  ],
  dingtalk: [
    { key: 'app_key', label: 'authSettings.appKey' }, { key: 'app_secret', label: 'authSettings.appSecret', secret: true },
  ],
}

export default function AuthSettings() {
  const { t } = useI18n()
  const { can } = useApp()
  const { toast } = useToast()
  const [tab, setTab] = useState('sso')
  const [providers, setProviders] = useState<AuthProvider[]>([])
  const [policy, setPolicy] = useState<MfaPolicy | null>(null)
  const [roles, setRoles] = useState<Role[]>([])
  const [configOpen, setConfigOpen] = useState(false)
  const [editing, setEditing] = useState<AuthProvider | null>(null)
  const [configDraft, setConfigDraft] = useState<Record<string, string>>({})
  const [enabledDraft, setEnabledDraft] = useState(false)
  const [userText, setUserText] = useState('')

  const load = async () => {
    try {
      const [p, m, r] = await Promise.all([
        get<{ providers: AuthProvider[] }>('/auth/sso/providers'),
        get<MfaPolicy>('/auth/mfa-policy'),
        get<{ roles: Role[] }>('/rbac/roles'),
      ])
      setProviders(p.providers || []); setPolicy(m); setRoles(r.roles || [])
      setUserText((m.enforced_users || []).join(', '))
    } catch (e: any) { toast(e.message, 'error') }
  }
  useEffect(() => { void load() }, [])

  const toggleProvider = async (p: AuthProvider) => {
    try { await put(`/auth/sso/providers/${p.code}`, { enabled: !p.enabled }); await load() }
    catch (e: any) { toast(e.message, 'error') }
  }
  const openConfig = (p: AuthProvider) => {
    setEditing(p); setConfigDraft({ ...(p.config || {}) } as Record<string, string>); setEnabledDraft(p.enabled); setConfigOpen(true)
  }
  const saveConfig = async () => {
    if (!editing) return
    try { await put(`/auth/sso/providers/${editing.code}`, { enabled: enabledDraft, config: configDraft })
      setConfigOpen(false); await load(); toast(t('common.saved'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
  }
  const savePolicy = async () => {
    if (!policy) return
    try {
      const updated = await put<MfaPolicy>('/auth/mfa-policy', { ...policy,
        enforced_users: userText.split(',').map((x) => x.trim()).filter(Boolean) })
      setPolicy(updated); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const callback = (code: string) => `${import.meta.env.VITE_BACKEND_URL || window.location.origin}/api/v1/auth/sso/${code}/callback`

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader icon={<ShieldCheck className="h-5 w-5" />} title={t('authSettings.title')} subtitle={t('authSettings.subtitle')}
        actions={<Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>} />

      <Tabs value={tab} onValueChange={setTab} className="mb-4" items={[
        { value: 'sso', label: t('authSettings.ssoProviders'), icon: <KeyRound className="h-3 w-3" />, count: providers.length },
        { value: 'mfa', label: t('authSettings.mfaPolicy'), icon: <LockKeyhole className="h-3 w-3" /> },
        { value: 'factors', label: t('authSettings.security'), icon: <Fingerprint className="h-3 w-3" /> },
      ]} />

      {tab === 'sso' && <>
        <Card className="mb-4"><CardContent className="flex flex-wrap items-center gap-2 py-3 text-xs text-muted-foreground">
          <Settings2 className="h-3.5 w-3.5 text-primary" />{t('authSettings.ssoHint')}
        </CardContent></Card>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {providers.map((p) => {
            const configured = Object.values(p.config || {}).some((v) => !!v)
            return <Card key={p.code} className="card-hover"><CardContent className="p-4">
              <div className="flex items-start gap-2.5">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary"><KeyRound className="h-4 w-4" /></span>
                <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{p.name}</p>
                  <p className="font-mono text-[10px] uppercase text-muted-foreground">{p.type}</p></div>
                <Switch checked={p.enabled} onCheckedChange={() => void toggleProvider(p)} disabled={!can('auth:config')} />
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <Badge variant={p.enabled ? 'success' : 'muted'}>{p.enabled ? t('common.enabled') : t('common.disabled')}</Badge>
                <Badge variant={configured ? 'secondary' : 'warning'}>{configured ? t('authSettings.configured') : t('authSettings.demoMode')}</Badge>
              </div>
              <div className="mt-3 rounded-md border bg-muted/30 px-2 py-1.5">
                <div className="flex items-center gap-1"><span className="text-[9px] uppercase tracking-wide text-muted-foreground">{t('authSettings.callbackHint')}</span>
                  <Button variant="ghost" size="icon-sm" className="ml-auto h-5 w-5"
                    onClick={() => void copyText(callback(p.code)).then(() => toast(t('common.copied'), 'success'))}><Copy className="h-2.5 w-2.5" /></Button></div>
                <p className="truncate font-mono text-[9px] text-muted-foreground">…/api/v1/auth/sso/{p.code}/callback</p>
              </div>
              <Button variant="outline" size="sm" className="mt-3 w-full" onClick={() => openConfig(p)} disabled={!can('auth:config')}>
                <Settings2 className="h-3.5 w-3.5" />{t('authSettings.configure')}</Button>
            </CardContent></Card>
          })}
        </div>
      </>}

      {tab === 'mfa' && policy && <div className="grid gap-4 lg:grid-cols-2">
        <Card><CardContent className="p-4">
          <SectionTitle>{t('authSettings.mfaPolicy')}</SectionTitle>
          <p className="mb-4 text-xs text-muted-foreground">{t('authSettings.policyHint')}</p>
          <div className="space-y-3">
            <PolicyRow label={t('authSettings.requireMfa')} checked={policy.required}
              onChange={(v) => setPolicy({ ...policy, required: v })} />
            <PolicyRow label={t('authSettings.otpFactor')} checked={policy.otp}
              onChange={(v) => setPolicy({ ...policy, otp: v })} />
            <PolicyRow label={t('authSettings.passkeyFactor')} checked={policy.passkey}
              onChange={(v) => setPolicy({ ...policy, passkey: v })} />
            <div className="rounded-lg border p-3"><p className="mb-2 text-xs font-medium">{t('authSettings.enforceRoles')}</p>
              <div className="flex flex-wrap gap-2">{roles.map((r) => (
                <label key={r.id} className="flex cursor-pointer items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs hover:bg-muted/50">
                  <input type="checkbox" className="h-3 w-3 accent-[hsl(var(--primary))]" checked={policy.enforced_roles.includes(r.code)}
                    onChange={() => setPolicy({ ...policy, enforced_roles: policy.enforced_roles.includes(r.code)
                      ? policy.enforced_roles.filter((x) => x !== r.code) : [...policy.enforced_roles, r.code] })} />{r.code}</label>
              ))}</div></div>
            <Field label={t('authSettings.enforceUsers')} hint="comma separated usernames">
              <Input value={userText} onChange={(e) => setUserText(e.target.value)} placeholder="alice, bob" /></Field>
            <Button size="sm" onClick={savePolicy} disabled={!can('auth:config')}><Save className="h-3.5 w-3.5" />{t('common.save')}</Button>
          </div>
        </CardContent></Card>
        <Card><CardContent className="p-4">
          <SectionTitle>{t('authSettings.security')}</SectionTitle>
          <div className="space-y-3">
            <div className="flex items-center gap-3 rounded-lg border p-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary"><LockKeyhole className="h-4 w-4" /></span>
              <div className="flex-1"><p className="text-xs font-medium">TOTP / OTP</p>
                <p className="text-[11px] text-muted-foreground">RFC 6238 · 6 digits · 30s</p></div>
              <Badge variant={policy.otp ? 'success' : 'muted'}>{policy.otp ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}</Badge>
            </div>
            <div className="flex items-center gap-3 rounded-lg border p-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary"><Fingerprint className="h-4 w-4" /></span>
              <div className="flex-1"><p className="text-xs font-medium">WebAuthn / Passkey</p>
                <p className="text-[11px] text-muted-foreground">RP ID: localhost · HTTPS required</p></div>
              <Badge variant={policy.passkey ? 'success' : 'muted'}>{policy.passkey ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}</Badge>
            </div>
            <p className="rounded-lg border bg-muted/30 p-3 text-[11px] leading-relaxed text-muted-foreground">
              {t('authSettings.policyHint')} — {t('settings.passkeyNote')}
            </p>
          </div>
        </CardContent></Card>
      </div>}

      {tab === 'factors' && <div className="grid gap-3 sm:grid-cols-2">
        {[
          { icon: <KeyRound className="h-5 w-5" />, title: 'TOTP / OTP', text: 'Per-user 6-digit authenticator codes. Users enroll from Settings.',
            key: 'otp' },
          { icon: <Fingerprint className="h-5 w-5" />, title: 'WebAuthn / Passkey', text: 'Biometric or hardware key sign-in bound to a device credential.',
            key: 'passkey' },
        ].map((f) => <Card key={f.key} className="p-5"><div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">{f.icon}</span>
          <div><p className="text-sm font-medium">{f.title}</p><p className="mt-0.5 text-xs text-muted-foreground">{f.text}</p></div>
        </div></Card>)}
      </div>}

      <Dialog open={configOpen} onOpenChange={setConfigOpen}
        title={t('authSettings.providerConfig', { name: editing?.name || '' })} size="lg"
        footer={<><Button variant="outline" onClick={() => setConfigOpen(false)}>{t('common.cancel')}</Button><Button onClick={saveConfig}>{t('common.save')}</Button></>}>
        <div className="space-y-3">
          <div className="flex items-center justify-between rounded-lg border px-3 py-2.5">
            <span className="text-xs font-medium">{t('authSettings.enableProvider')}</span>
            <Switch checked={enabledDraft} onCheckedChange={setEnabledDraft} />
          </div>
          {(FIELDS[editing?.type || ''] || []).map((f) => <Field key={f.key} label={t(f.label)}>
            <Input type={f.secret ? 'password' : 'text'} value={configDraft[f.key] || ''}
              onChange={(e) => setConfigDraft({ ...configDraft, [f.key]: e.target.value })} />
          </Field>)}
          <p className="text-[11px] text-muted-foreground">{t('authSettings.demoMode')}: {t('authSettings.ssoHint')}</p>
        </div>
      </Dialog>
    </div>
  )
}

function PolicyRow({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return <div className="flex items-center justify-between rounded-lg border px-3 py-2.5">
    <span className="text-xs font-medium">{label}</span><Switch checked={checked} onCheckedChange={onChange} />
  </div>
}
