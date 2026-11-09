import { useEffect, useMemo, useState } from 'react'
import {
  Boxes, Download, Globe2, HardDrive, Link2, Package, Plus, RefreshCw,
  Search, Server, Star, Trash2, Zap,
} from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { Badge, Button, Card, CardContent, Field, Input, Label, Select, Switch } from '@/components/ui/basic'
import { ConfirmDialog, Dialog, Tabs, useToast } from '@/components/ui/overlay'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { del, get, post, put } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import type { HubSearchResult, HubSkill, SkillHub } from '@/types'

export default function SkillHubs() {
  const { t, locale } = useI18n()
  const { can } = useApp()
  const { toast } = useToast()
  const [tab, setTab] = useState('discover')
  const [hubs, setHubs] = useState<SkillHub[]>([])
  const [stats, setStats] = useState<Record<string, number>>({})
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [categories, setCategories] = useState<string[]>([])
  const [results, setResults] = useState<HubSkill[]>([])
  const [errors, setErrors] = useState<string[]>([])
  const [searched, setSearched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [hubOpen, setHubOpen] = useState(false)
  const [hubForm, setHubForm] = useState<any>({})
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)

  const loadHubs = async () => {
    try {
      const d = await get<{ hubs: SkillHub[]; stats: Record<string, number> }>('/skill-hubs')
      setHubs(d.hubs || []); setStats(d.stats || {})
    } catch (e: any) { toast(e.message, 'error') }
  }
  const search = async (q = query, cat = category) => {
    setBusy(true); setSearched(true)
    try {
      const params = new URLSearchParams()
      if (q.trim()) params.set('q', q.trim())
      if (cat) params.set('category', cat)
      const d = await get<HubSearchResult>(`/skill-hubs/search?${params}`)
      setResults(d.skills || []); setErrors(d.errors || [])
      if (d.categories?.length) setCategories(d.categories)
    } catch (e: any) { toast(e.message, 'error') }
    finally { setBusy(false) }
  }
  useEffect(() => { void loadHubs(); void search('', '') }, [])

  const categoryOptions = useMemo(() => [
    { value: '', label: t('hubs.allCategories') },
    ...categories.map((c) => ({ value: c, label: c })),
  ], [categories, locale])

  const sync = async (h: SkillHub) => {
    try {
      const r: any = await post(`/skill-hubs/${h.id}/sync`, {})
      toast(r.ok ? `${h.code}: ${r.count}` : r.error || 'Sync failed', r.ok ? 'success' : 'error')
      await loadHubs()
    } catch (e: any) { toast(e.message, 'error') }
  }
  const toggle = async (h: SkillHub, enabled: boolean) => {
    try { await put(`/skill-hubs/${h.id}`, { enabled }); await loadHubs() }
    catch (e: any) { toast(e.message, 'error') }
  }
  const remove = async () => {
    if (!confirmDelete) return
    try { await del(`/skill-hubs/${confirmDelete}`); await loadHubs(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmDelete(null) }
  }
  const openHub = (h?: SkillHub) => {
    setHubForm(h ? { id: h.id, code: h.code, name: h.name, description: h.description,
      kind: h.kind, url: h.url || '', enabled: h.enabled,
      sync_interval_min: h.sync_interval_min || 60 } :
      { id: 0, code: '', name: '', description: '', kind: 'remote', url: '',
        enabled: true, sync_interval_min: 60 })
    setHubOpen(true)
  }
  const saveHub = async () => {
    const payload: any = { code: hubForm.code, name: hubForm.name,
      description: hubForm.description, kind: hubForm.kind,
      url: hubForm.url || null, enabled: hubForm.enabled,
      sync_interval_min: Number(hubForm.sync_interval_min) || 60 }
    try {
      if (hubForm.id) await put(`/skill-hubs/${hubForm.id}`, payload)
      else await post('/skill-hubs', payload)
      setHubOpen(false); await loadHubs(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const addSkill = async (s: HubSkill) => {
    try {
      await post(`/skill-hubs/${s.hub_id}/install`, { code: s.code })
      toast(`${t('hubs.added')}: ${s.code}`, 'success')
      await search(); await loadHubs()
    } catch (e: any) { toast(e.message, 'error') }
  }

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader icon={<Boxes className="h-5 w-5" />} title={t('hubs.title')} subtitle={t('hubs.subtitle')}
        actions={<>
          <Button variant="outline" size="sm" onClick={() => { void loadHubs(); void search() }}>
            <RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>
          {can('skill:write') && <Button size="sm" variant="outline" onClick={() => openHub()}>
            <Plus className="h-4 w-4" />{t('hubs.newHub')}</Button>}
        </>} />

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          { label: t('hubs.hub'), value: stats.total ?? 0, icon: <Boxes className="h-4 w-4" /> },
          { label: t('common.enabled'), value: stats.enabled ?? 0, icon: <Zap className="h-4 w-4" /> },
          { label: t('hubs.builtin'), value: stats.builtin ?? 0, icon: <HardDrive className="h-4 w-4" /> },
          { label: t('hubs.installedCount'), value: stats.installed_from_hub ?? 0, icon: <Download className="h-4 w-4" /> },
        ].map((s, i) => <Card key={i} className="p-3"><div className="flex items-center gap-2 text-primary">{s.icon}
          <span className="mono-num text-sm font-semibold text-foreground">{s.value}</span></div>
          <p className="mt-1 truncate text-[11px] text-muted-foreground">{s.label}</p></Card>)}
      </div>

      <Tabs value={tab} onValueChange={setTab} className="mb-4" items={[
        { value: 'discover', label: t('hubs.discover'), icon: <Search className="h-3 w-3" />, count: results.length },
        { value: 'manage', label: t('hubs.manage'), icon: <Server className="h-3 w-3" />, count: hubs.length },
      ]} />

      {tab === 'discover' && <>
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border bg-card/60 p-3">
          <div className="flex min-w-[12rem] flex-1 items-center gap-2 rounded-md border bg-background px-2.5">
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <Input className="border-0 bg-transparent px-0 focus-visible:ring-0" value={query}
              placeholder={t('hubs.searchPlaceholder')}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void search() }} />
          </div>
          <Select value={category} onValueChange={(v) => { setCategory(v); void search(query, v) }}
            options={categoryOptions} className="w-40" />
          <Button size="sm" onClick={() => void search()} loading={busy}>
            <Search className="h-3.5 w-3.5" />{t('hubs.search')}</Button>
        </div>
        {errors.length > 0 && <p className="mb-3 text-[11px] text-warning">{t('hubs.degraded')}: {errors.join('; ')}</p>}
        <p className="mb-3 text-xs text-muted-foreground">
          {searched ? `${results.length} ${t('hubs.results')}` : t('hubs.offlineHint')}
        </p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {results.map((s) => (
            <Card key={`${s.hub_code}-${s.code}`} className="card-hover"><CardContent className="p-4">
              <div className="flex items-start gap-2">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Package className="h-4 w-4" /></span>
                <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{s.name}</p>
                  <p className="truncate font-mono text-[10px] text-muted-foreground">{s.code} · v{s.version} · {s.type}</p></div>
                <Badge variant={s.installed ? 'success' : 'outline'}>{s.installed ? t('hubs.installed') : t('mcp.available')}</Badge>
              </div>
              <p className="mt-2 line-clamp-2 min-h-[2rem] text-[11px] text-muted-foreground">{s.description}</p>
              <div className="mt-2 flex flex-wrap gap-1">{(s.capabilities || []).map((c) =>
                <Badge key={c} variant="secondary" className="font-mono text-[9px]">{c}</Badge>)}</div>
              <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-muted-foreground">
                <span className="inline-flex items-center gap-1"><Boxes className="h-3 w-3" />{s.hub_name}</span>
                <span>·</span><span>{s.author}</span><span>·</span>
                <span className="inline-flex items-center gap-1"><Star className="h-3 w-3" />{s.downloads}</span>
                <span>·</span><span>{t('mcp.tools')}: {s.tool_count}</span>
              </div>
              <div className="mt-3 border-t pt-3">
                <Button size="sm" className="h-7 text-xs" disabled={!can('skill:write') || s.installed}
                  onClick={() => void addSkill(s)}><Download className="h-3 w-3" />{t('hubs.add')}</Button>
              </div>
            </CardContent></Card>
          ))}
          {!results.length && <Card className="p-8 text-center text-sm text-muted-foreground md:col-span-2 xl:col-span-3">
            {t('hubs.noResults')}</Card>}
        </div>
      </>}

      {tab === 'manage' && <>
        <p className="mb-3 text-xs text-muted-foreground">{t('hubs.offlineHint')}</p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {hubs.map((h) => (
            <Card key={h.id} className="card-hover"><CardContent className="p-4">
              <div className="flex items-start gap-2">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  {h.kind === 'builtin' ? <HardDrive className="h-4 w-4" /> : <Globe2 className="h-4 w-4" />}</span>
                <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{h.name}</p>
                  <p className="truncate font-mono text-[10px] text-muted-foreground">{h.code} · {h.kind}</p></div>
                <Switch checked={h.enabled} onCheckedChange={(v) => void toggle(h, v)} disabled={!can('skill:write')} />
              </div>
              <p className="mt-2 line-clamp-2 min-h-[2rem] text-[11px] text-muted-foreground">{h.description}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="outline"><Package className="h-2.5 w-2.5" />{h.skill_count} {t('hubs.skillCount')}</Badge>
                <Badge variant="outline"><Download className="h-2.5 w-2.5" />{h.installed_count} {t('hubs.installedCount')}</Badge>
                <Badge variant={h.kind === 'builtin' ? 'success' : 'secondary'}>{h.kind === 'builtin' ? t('hubs.builtin') : t('hubs.remote')}</Badge>
              </div>
              {h.url && <p className="mt-2 flex items-center gap-1 truncate font-mono text-[10px] text-muted-foreground"><Link2 className="h-3 w-3" />{h.url}</p>}
              <p className="mt-1 text-[10px] text-muted-foreground">{t('hubs.lastSync')}: {formatDate(h.last_sync_at, locale)}</p>
              {h.last_error && <p className="mt-1 truncate text-[10px] text-destructive">{h.last_error}</p>}
              {can('skill:write') && <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t pt-3">
                <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => void sync(h)}>
                  <RefreshCw className="h-3 w-3" />{t('hubs.sync')}</Button>
                <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => openHub(h)}>{t('common.edit')}</Button>
                <div className="ml-auto"><Button variant="ghost" size="sm" className="h-7 text-xs"
                  onClick={() => setConfirmDelete(h.id)}><Trash2 className="h-3 w-3 text-destructive" /></Button></div>
              </div>}
            </CardContent></Card>
          ))}
          {!hubs.length && <Card className="p-8 text-center text-sm text-muted-foreground md:col-span-2 xl:col-span-3">{t('hubs.empty')}</Card>}
        </div>
      </>}

      <Dialog open={hubOpen} onOpenChange={setHubOpen} title={hubForm.id ? t('hubs.editHub') : t('hubs.newHub')}
        footer={<><Button variant="outline" onClick={() => setHubOpen(false)}>{t('common.cancel')}</Button>
          <Button onClick={saveHub}>{t('hubs.save')}</Button></>}>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('hubs.code')}><Input value={hubForm.code} disabled={!!hubForm.id}
              onChange={(e) => setHubForm({ ...hubForm, code: e.target.value })} placeholder="my_hub" /></Field>
            <Field label={t('hubs.name')}><Input value={hubForm.name}
              onChange={(e) => setHubForm({ ...hubForm, name: e.target.value })} /></Field>
          </div>
          <Field label={t('hubs.description')}><Input value={hubForm.description}
            onChange={(e) => setHubForm({ ...hubForm, description: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('hubs.kind')}><Select value={hubForm.kind}
              onValueChange={(v) => setHubForm({ ...hubForm, kind: v })}
              options={[{ value: 'builtin', label: t('hubs.builtin') }, { value: 'remote', label: t('hubs.remote') }]} /></Field>
            <Field label={t('hubs.interval')}><Input type="number" value={hubForm.sync_interval_min}
              onChange={(e) => setHubForm({ ...hubForm, sync_interval_min: e.target.value })} /></Field>
          </div>
          {hubForm.kind === 'remote' && <Field label={t('hubs.url')}><Input value={hubForm.url}
            onChange={(e) => setHubForm({ ...hubForm, url: e.target.value })} placeholder="https://registry.example.com" /></Field>}
          <div className="flex items-center justify-between rounded-lg border px-3 py-2">
            <Label className="text-xs">{t('common.enabled')}</Label>
            <Switch checked={hubForm.enabled} onCheckedChange={(v) => setHubForm({ ...hubForm, enabled: v })} /></div>
        </div>
      </Dialog>

      <ConfirmDialog open={confirmDelete !== null} onOpenChange={() => setConfirmDelete(null)}
        title={t('hubs.delete')} description={t('hubs.confirmDelete')} onConfirm={remove} />
    </div>
  )
}
