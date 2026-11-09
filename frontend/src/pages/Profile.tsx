import { useEffect, useState } from 'react'
import {
  Bell, CheckCheck, ClipboardList, Fingerprint, FileText, KeyRound, Loader2,
  Mail, ShieldCheck, UserCog, UsersRound, Workflow,
} from 'lucide-react'
import { useI18n } from '@/i18n'
import { get, post, put } from '@/lib/api'
import { useApp } from '@/store/AppContext'
import { useToast } from '@/components/ui/overlay'
import {
  Avatar, Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle,
  Field, Input, Separator, Switch,
} from '@/components/ui/basic'
import type { MeOverview, NotificationChannelMeta, NotificationPrefs } from '@/types'

interface PrefsPayload {
  events: NotificationPrefs
  catalog: { events: { code: string; en: string; zh: string }[]
             channels: NotificationChannelMeta[] }
}

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: number | string }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">{icon}</div>
        <div className="min-w-0">
          <p className="text-lg font-semibold leading-tight">{value}</p>
          <p className="truncate text-[11px] text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  )
}

export default function Profile() {
  const { t, locale } = useI18n()
  const { user } = useApp()
  const { toast } = useToast()
  const [overview, setOverview] = useState<MeOverview | null>(null)
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [prefs, setPrefs] = useState<PrefsPayload | null>(null)
  const [savingProfile, setSavingProfile] = useState(false)
  const [savingPassword, setSavingPassword] = useState(false)
  const [savingPrefs, setSavingPrefs] = useState(false)

  const load = async () => {
    const r = await get<MeOverview>('/auth/me/overview')
    setOverview(r)
    setDisplayName(r.profile.display_name || '')
    setEmail(r.profile.email || '')
    const p = await get<PrefsPayload>('/notifications/prefs')
    setPrefs(p)
  }

  useEffect(() => { load().catch(() => toast(t('common.operationFailed'), 'error')) }, []) // eslint-disable-line

  const saveProfile = async () => {
    setSavingProfile(true)
    try {
      await put('/auth/me', { display_name: displayName, email: email || null })
      toast(t('common.saved'), 'success')
      await load()
    } catch (e: any) { toast(e?.message || t('common.operationFailed'), 'error') }
    setSavingProfile(false)
  }

  const savePassword = async () => {
    if (!oldPassword || !newPassword) { toast(t('profile.passwordRequired'), 'error'); return }
    setSavingPassword(true)
    try {
      await post('/auth/change-password', { old_password: oldPassword, new_password: newPassword })
      toast(t('profile.passwordChanged'), 'success')
      setOldPassword(''); setNewPassword('')
    } catch (e: any) { toast(e?.message || t('common.operationFailed'), 'error') }
    setSavingPassword(false)
  }

  const savePrefs = async () => {
    if (!prefs) return
    setSavingPrefs(true)
    try {
      const r = await put<{ events: NotificationPrefs }>('/notifications/prefs', { events: prefs.events })
      setPrefs((prev) => prev ? { ...prev, events: r.events } : prev)
      toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e?.message || t('common.operationFailed'), 'error') }
    setSavingPrefs(false)
  }

  const togglePref = (event: string, channel: string) => {
    setPrefs((prev) => {
      if (!prev) return prev
      const current = prev.events[event] || []
      const next = current.includes(channel)
        ? current.filter((c) => c !== channel)
        : [...current, channel]
      return { ...prev, events: { ...prev.events, [event]: next } }
    })
  }

  const label = (item: { code: string; en: string; zh: string }) => locale === 'zh' ? item.zh : item.en

  if (!overview) {
    return <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
  }

  const p = overview.profile
  return (
    <div className="mx-auto max-w-6xl space-y-5">
      {/* identity banner */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-4 p-5">
          <Avatar name={p.display_name || p.username} className="h-14 w-14 text-lg" />
          <div className="min-w-0">
            <p className="text-lg font-semibold tracking-tight">{p.display_name || p.username}</p>
            <p className="text-xs text-muted-foreground">
              {p.username} · {p.dept || '—'} · {p.email || '—'}
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {(p.role_codes || []).map((r) => <Badge key={r} variant="secondary">{r}</Badge>)}
              <Badge variant="outline" className="gap-1"><ShieldCheck className="h-3 w-3" />
                {t('profile.dataScope')}: {overview.data_scope}</Badge>
              {(Array.isArray(p.tags) ? p.tags : []).map((tg) => <Badge key={tg} variant="outline">{tg}</Badge>)}
              {p.otp_enabled ? <Badge className="bg-success/10 text-success"><Fingerprint className="h-3 w-3" />OTP</Badge> : null}
              {p.passkey_enabled ? <Badge className="bg-success/10 text-success"><KeyRound className="h-3 w-3" />Passkey</Badge> : null}
            </div>
          </div>
          <div className="ml-auto flex flex-wrap gap-1.5">
            {overview.groups.length > 0 && overview.groups.map((g) => (
              <Badge key={g.code} variant="outline" className="gap-1"><UsersRound className="h-3 w-3" />{g.name}</Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* stats */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatCard icon={<ClipboardList className="h-4 w-4" />} label={t('profile.pendingTasks')} value={overview.tasks.pending} />
        <StatCard icon={<CheckCheck className="h-4 w-4" />} label={t('profile.doneTasks')} value={overview.tasks.done} />
        <StatCard icon={<Workflow className="h-4 w-4" />} label={t('profile.running')} value={overview.instances.running} />
        <StatCard icon={<FileText className="h-4 w-4" />} label={t('profile.submissions')} value={overview.submissions} />
        <StatCard icon={<Bell className="h-4 w-4" />} label={t('profile.unread')} value={overview.notifications_unread} />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* basic info */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base"><UserCog className="h-4 w-4 text-primary" />{t('profile.basicInfo')}</CardTitle>
            <CardDescription>{t('profile.basicInfoHint')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Field label={t('profile.displayName')}>
              <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></Field>
            <Field label={t('profile.email')}>
              <Input type="email" value={email} placeholder="name@example.com"
                onChange={(e) => setEmail(e.target.value)} /></Field>
            <Separator />
            <Button onClick={saveProfile} loading={savingProfile} className="w-full sm:w-auto">{t('common.save')}</Button>
          </CardContent>
        </Card>

        {/* password */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base"><KeyRound className="h-4 w-4 text-primary" />{t('profile.password')}</CardTitle>
            <CardDescription>{t('profile.passwordHint')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Field label={t('profile.oldPassword')}>
              <Input type="password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} /></Field>
            <Field label={t('profile.newPassword')} hint={t('profile.passwordMinLength')}>
              <Input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} /></Field>
            <Separator />
            <Button onClick={savePassword} loading={savingPassword} className="w-full sm:w-auto">{t('profile.changePassword')}</Button>
          </CardContent>
        </Card>
      </div>

      {/* notification preferences */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><Bell className="h-4 w-4 text-primary" />{t('profile.prefs')}</CardTitle>
          <CardDescription>{t('profile.prefsHint')}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[30rem] text-sm">
              <thead>
                <tr className="border-b text-left text-[11px] text-muted-foreground">
                  <th className="pb-2 pr-2 font-medium">{t('profile.event')}</th>
                  {prefs?.catalog.channels.map((c) => (
                    <th key={c.code} className="pb-2 text-center font-medium">
                      {label(c)}{c.ready === false && c.editable ? ' ·' : ''}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {prefs?.catalog.events.map((ev) => (
                  <tr key={ev.code} className="border-b last:border-0">
                    <td className="py-2 pr-2 text-xs">{label(ev)}</td>
                    {prefs.catalog.channels.map((c) => (
                      <td key={c.code} className="py-2 text-center">
                        <Switch
                          checked={(prefs.events[ev.code] || []).includes(c.code)}
                          disabled={c.code === 'inapp'}
                          onCheckedChange={() => togglePref(ev.code, c.code)} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">{t('profile.prefsChannelsHint')}</p>
          <Button onClick={savePrefs} loading={savingPrefs} className="mt-3 w-full sm:w-auto">{t('common.save')}</Button>
        </CardContent>
      </Card>

      {/* delegations */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><UsersRound className="h-4 w-4 text-primary" />{t('profile.delegations')}</CardTitle>
          <CardDescription>{t('profile.delegationsHint')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div>
            <p className="mb-1.5 text-[11px] font-semibold text-muted-foreground">{t('profile.delegationsOut')}</p>
            {overview.delegations.outgoing.length === 0
              ? <p className="text-xs text-muted-foreground">{t('profile.noDelegations')}</p>
              : overview.delegations.outgoing.map((d, i) => (
                <p key={i} className="text-xs">{d.principal} → <Badge variant="secondary">{d.agent}</Badge>
                  <span className="ml-2 font-mono text-[10px] text-muted-foreground">
                    {(d.starts_at || '').slice(0, 10)} ~ {(d.ends_at || '').slice(0, 10)}
                  </span></p>
              ))}
          </div>
          <Separator />
          <div>
            <p className="mb-1.5 text-[11px] font-semibold text-muted-foreground">{t('profile.delegationsIn')}</p>
            {overview.delegations.incoming.length === 0
              ? <p className="text-xs text-muted-foreground">{t('profile.noDelegations')}</p>
              : overview.delegations.incoming.map((d, i) => (
                <p key={i} className="text-xs"><Mail className="mr-1 inline h-3 w-3" />{d.principal} → <Badge variant="secondary">{d.agent}</Badge></p>
              ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
