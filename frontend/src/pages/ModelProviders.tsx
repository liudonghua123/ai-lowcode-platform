import { useEffect, useState } from 'react'
import {
  Activity, CheckCircle2, Cpu, Eye, KeyRound, Layers, ListFilter, Mic,
  Plus, RefreshCw, Save, Sparkles, Trash2, Volume2, Zap,
} from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { Badge, Button, Card, CardContent, Field, Input, Select, Switch, Textarea } from '@/components/ui/basic'
import { ConfirmDialog, Dialog, Tabs, useToast } from '@/components/ui/overlay'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { del, get, post, put } from '@/lib/api'
import type { AiProvider, AiProviderMeta, ModelCategoryMeta } from '@/types'

const CATEGORY_ICONS: Record<string, any> = {
  llm: Sparkles, asr: Mic, tts: Volume2, embedding: Layers, rerank: ListFilter, vision: Eye,
}

export default function ModelProviders() {
  const { t } = useI18n()
  const { can } = useApp()
  const { toast } = useToast()
  const [providers, setProviders] = useState<AiProvider[]>([])
  const [meta, setMeta] = useState<AiProviderMeta | null>(null)
  const [tab, setTab] = useState('all')
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<any>({})
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)
  const [testResult, setTestResult] = useState<any>(null)

  const load = async () => {
    try {
      const [list, m] = await Promise.all([
        get<{ providers: AiProvider[] }>('/ai/providers'),
        get<AiProviderMeta>('/ai/providers/meta'),
      ])
      setProviders(list.providers || []); setMeta(m)
    } catch (e: any) { toast(e.message, 'error') }
  }
  useEffect(() => { void load() }, [])

  const categories: ModelCategoryMeta[] = meta?.categories || []
  const label = (c: ModelCategoryMeta) => t(`models.cat.${c.code}`) || c.label
  const visible = tab === 'all' ? providers : providers.filter((p) => p.category === tab)

  const openForm = (p?: AiProvider) => {
    setForm(p ? {
      id: p.id, code: p.code, name: p.name, category: p.category, vendor: p.vendor,
      base_url: p.base_url, model: p.model, api_key: '', description: p.description || '',
      enabled: p.enabled, is_default: p.is_default,
    } : {
      id: 0, code: '', name: '', category: tab === 'all' ? 'llm' : tab,
      vendor: 'custom', base_url: '', model: '', api_key: '',
      description: '', enabled: true, is_default: false,
    })
    setOpen(true)
  }

  const applyVendor = (code: string) => {
    const vendor = meta?.vendors.find((v) => v.code === code)
    setForm((f: any) => ({ ...f, vendor: code,
      base_url: vendor?.base_url || f.base_url,
      model: vendor?.models?.[f.category] || f.model }))
  }

  const save = async () => {
    const payload: any = {
      code: form.code, name: form.name, category: form.category, vendor: form.vendor,
      base_url: form.base_url, model: form.model, description: form.description,
      enabled: form.enabled, is_default: form.is_default,
    }
    if (form.api_key) payload.api_key = form.api_key
    if (form.id) { delete payload.code; delete payload.category }
    try {
      if (form.id) await put(`/ai/providers/${form.id}`, payload)
      else await post('/ai/providers', payload)
      setOpen(false); await load(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }

  const setDefault = async (p: AiProvider) => {
    try { await post(`/ai/providers/${p.id}/default`, {}); await load(); toast(t('models.defaultSet'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
  }
  const toggle = async (p: AiProvider) => {
    try { await put(`/ai/providers/${p.id}`, { enabled: !p.enabled }); await load() }
    catch (e: any) { toast(e.message, 'error') }
  }
  const test = async (p: AiProvider) => {
    try { setTestResult(await post(`/ai/providers/${p.id}/test`, { live: false })) }
    catch (e: any) { toast(e.message, 'error') }
  }
  const remove = async () => {
    if (!confirmDelete) return
    try { await del(`/ai/providers/${confirmDelete}`); await load(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmDelete(null) }
  }

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader icon={<Cpu className="h-5 w-5" />} title={t('models.title')} subtitle={t('models.subtitle')}
        actions={<>
          <Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>
          {can('settings:write') && <Button size="sm" onClick={() => openForm()}><Plus className="h-4 w-4" />{t('models.newProvider')}</Button>}
        </>} />

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: t('models.totalProviders'), value: meta?.total ?? 0, icon: <Cpu className="h-4 w-4" /> },
          { label: t('models.categories'), value: categories.length, icon: <Layers className="h-4 w-4" /> },
          { label: t('models.effectiveLlm'), value: String(meta?.effective_llm?.model ?? '—'), icon: <Sparkles className="h-4 w-4" /> },
          { label: t('models.apiKeyReady'), value: meta?.effective_llm?.has_api_key ? t('common.yes') : t('common.no'), icon: <KeyRound className="h-4 w-4" /> },
        ].map((s, i) => <Card key={i} className="p-3"><div className="flex items-center gap-2 text-primary">{s.icon}
          <span className="mono-num truncate text-sm font-semibold text-foreground">{s.value}</span></div>
          <p className="mt-1 text-[11px] text-muted-foreground">{s.label}</p></Card>)}
      </div>

      <Card className="mb-4"><CardContent className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold">{t('models.runtimeTitle')}</p>
            <p className="mt-1 text-[11px] text-muted-foreground">{t('models.runtimeHint')}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Badge variant="outline" className="font-mono text-[9px]">provider: {String(meta?.effective_llm?.provider ?? '—')}</Badge>
              <Badge variant="outline" className="font-mono text-[9px]">model: {String(meta?.effective_llm?.model ?? '—')}</Badge>
              <Badge variant="outline" className="font-mono text-[9px]">source: {String(meta?.effective_llm?.source ?? '—')}</Badge>
              <Badge variant="secondary" className="font-mono text-[9px]">agentscope / openai-compatible / mock</Badge>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
            {categories.map((c) => {
              const d = meta?.defaults?.[c.code]
              return <div key={c.code} className="rounded-lg border px-2.5 py-1.5">
                <p className="text-[9px] text-muted-foreground">{label(c)}</p>
                <p className="truncate font-mono text-[10px] font-medium">{d?.model || '—'}</p>
              </div>
            })}
          </div>
        </div>
      </CardContent></Card>

      <Tabs value={tab} onValueChange={setTab} className="mb-4" items={[
        { value: 'all', label: t('common.all'), icon: <Layers className="h-3 w-3" />, count: providers.length },
        ...categories.map((c) => ({ value: c.code, label: label(c),
          icon: (() => { const I = CATEGORY_ICONS[c.code] || Zap; return <I className="h-3 w-3" /> })(),
          count: providers.filter((p) => p.category === c.code).length })),
      ]} />

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {visible.map((p) => {
          const Icon = CATEGORY_ICONS[p.category] || Zap
          const cat = categories.find((c) => c.code === p.category)
          return <Card key={p.id} className="card-hover"><CardContent className="p-4">
            <div className="flex items-start gap-2">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary"><Icon className="h-4 w-4" /></span>
              <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{p.name}</p>
                <p className="truncate font-mono text-[10px] text-muted-foreground">{p.code} · {p.vendor}</p></div>
              <Switch checked={p.enabled} onCheckedChange={() => void toggle(p)} disabled={!can('settings:write')} />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <Badge variant="secondary">{cat ? label(cat) : p.category}</Badge>
              {p.is_default && <Badge variant="success"><CheckCircle2 className="h-2.5 w-2.5" />{t('models.default')}</Badge>}
              <Badge variant={p.has_api_key ? 'success' : 'muted'}><KeyRound className="h-2.5 w-2.5" />{p.has_api_key ? p.api_key_masked : t('models.noKey')}</Badge>
            </div>
            <div className="mt-2 space-y-1 text-[11px]">
              <p className="truncate font-mono text-muted-foreground">{p.model || '—'}</p>
              <p className="truncate font-mono text-[10px] text-muted-foreground">{p.base_url || t('models.noEndpoint')}</p>
            </div>
            {p.description && <p className="mt-2 line-clamp-2 text-[11px] text-muted-foreground">{p.description}</p>}
            <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t pt-3">
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => void test(p)}><Activity className="h-3 w-3" />{t('models.test')}</Button>
              {can('settings:write') && <>
                {!p.is_default && <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => void setDefault(p)}><CheckCircle2 className="h-3 w-3" />{t('models.setDefault')}</Button>}
                <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => openForm(p)}><Save className="h-3 w-3" />{t('common.edit')}</Button>
                <Button variant="ghost" size="icon-sm" className="ml-auto" onClick={() => setConfirmDelete(p.id)}><Trash2 className="h-3 w-3 text-destructive" /></Button>
              </>}
            </div>
          </CardContent></Card>
        })}
        {!visible.length && <Card className="p-8 text-center text-sm text-muted-foreground md:col-span-2 xl:col-span-3">{t('common.noData')}</Card>}
      </div>

      <Dialog open={open} onOpenChange={setOpen} title={form.id ? t('models.editTitle') : t('models.createTitle')} size="lg"
        footer={<><Button variant="outline" onClick={() => setOpen(false)}>{t('common.cancel')}</Button><Button onClick={save}>{t('common.save')}</Button></>}>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('common.code')}><Input value={form.code} disabled={!!form.id} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="my_llm" /></Field>
            <Field label={t('common.name')}><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('models.category')}><Select value={form.category} disabled={!!form.id}
              onValueChange={(v) => setForm({ ...form, category: v })}
              options={categories.map((c) => ({ value: c.code, label: label(c) }))} /></Field>
            <Field label={t('models.vendor')}><Select value={form.vendor} onValueChange={applyVendor}
              options={(meta?.vendors || []).map((v) => ({ value: v.code, label: v.name }))} /></Field>
          </div>
          <Field label={t('models.baseUrl')}><Input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://api.openai.com/v1" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('models.model')}><Input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></Field>
            <Field label={t('models.apiKey')}><Input type="password" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })}
              placeholder={form.id ? t('models.apiKeyKeep') : 'sk-…'} /></Field>
          </div>
          <Field label={t('common.description')}><Textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex items-center justify-between rounded-lg border px-3 py-2"><span className="text-xs">{t('common.enabled')}</span>
              <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} /></div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2"><span className="text-xs">{t('models.default')}</span>
              <Switch checked={form.is_default} onCheckedChange={(v) => setForm({ ...form, is_default: v })} /></div>
          </div>
        </div>
      </Dialog>

      <Dialog open={!!testResult} onOpenChange={() => setTestResult(null)} title={t('models.testResult')}
        footer={<Button variant="outline" onClick={() => setTestResult(null)}>{t('common.close')}</Button>}>
        {testResult && <div className="space-y-2 text-xs">
          <Badge variant={testResult.ok ? 'success' : 'destructive'}>{testResult.ok ? t('common.success') : t('common.failed')} · {testResult.mode}</Badge>
          {(testResult.checks || []).map((c: any) => <div key={c.name} className="flex items-center justify-between rounded-md border px-2.5 py-1.5">
            <span className="font-mono text-[11px]">{c.name}</span>
            <Badge variant={c.ok ? 'success' : 'muted'}>{c.ok ? 'OK' : '—'}</Badge></div>)}
          {testResult.note && <p className="pt-1 text-[10px] text-muted-foreground">{testResult.note}</p>}
        </div>}
      </Dialog>

      <ConfirmDialog open={confirmDelete !== null} onOpenChange={() => setConfirmDelete(null)} title={t('common.confirmDelete')} onConfirm={remove} />
    </div>
  )
}
