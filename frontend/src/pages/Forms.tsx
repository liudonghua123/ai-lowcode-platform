import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  AlignLeft, CalendarDays, CheckSquare, ChevronDown, Copy, FileText, GripVertical,
  Hash, ListFilter, Paperclip, Plus, Save, Send, Settings2, Table2, ToggleLeft,
  Trash2, Type, UserRound, Users, Eye, PencilRuler, Minus, RefreshCw, CircleDot, Layers,
  Calculator, Braces, ShieldCheck, Smartphone, Monitor, History, Printer, Download,
  UploadCloud, PenLine, MapPin, CreditCard, IdCard, Banknote, ScanLine, LayoutGrid,
  Info, Sigma, GitBranch, X, ChevronUp,
} from 'lucide-react'
import { PageHeader, SectionTitle } from '@/components/PageHeader'
import {
  Badge, Button, Card, CardContent, EmptyState, Field, Input, Label, Segmented,
  Select, Switch, Textarea,
} from '@/components/ui/basic'
import { ConfirmDialog, Dialog, useToast } from '@/components/ui/overlay'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { del, get, post, put, download } from '@/lib/api'
import { cn, formatDate, uid } from '@/lib/utils'
import type {
  FormCatalog, FormDef, FormEvalResult, FormField, FormFieldItem, FormRule,
  FormSubmission, FormVersion, PrintView,
} from '@/types'

const FIELD_ICONS: Record<string, typeof Type> = {
  text: Type, textarea: AlignLeft, number: Hash, select: ListFilter,
  multiselect: ListFilter, date: CalendarDays, datetime: CalendarDays, time: CalendarDays,
  switch: ToggleLeft, radio: CircleDot, checkbox: CheckSquare, slider: Hash, rate: CircleDot,
  color: Type, email: Type, url: Type,
  idcard: IdCard, mobile: Smartphone, tel: Smartphone, bankcard: CreditCard,
  uscc: ScanLine, amount: Banknote, region: MapPin, cascader: ListFilter,
  signature: PenLine, qrcode: ScanLine,
  user: UserRound, multi_user: Users, department: Users, role: ShieldCheck,
  table: Table2, formula: Sigma, serial: Hash, relation: GitBranch,
  attachment: Paperclip, image: Paperclip, location: MapPin, richtext: AlignLeft, ocr: ScanLine,
  divider: Minus, description: Info, grid: LayoutGrid, tabs: Layers, collapse: ChevronDown,
}
const GROUP_ICONS: Record<string, typeof Type> = {
  basic: Type, china: IdCard, org: Users, business: Braces, layout: LayoutGrid,
}
const FALLBACK_GROUPS = [
  { code: 'basic', label: 'Basic', fields: ['text', 'textarea', 'number', 'select', 'date', 'switch'] },
  { code: 'china', label: 'China-local', fields: ['idcard', 'mobile', 'amount', 'region', 'signature'] },
  { code: 'org', label: 'Organization', fields: ['user', 'department', 'role'] },
  { code: 'business', label: 'Business', fields: ['table', 'formula', 'serial', 'attachment', 'image'] },
  { code: 'layout', label: 'Layout', fields: ['divider', 'description', 'grid'] },
]

function defaultField(type: string, index: number, item?: FormFieldItem): FormField {
  return {
    id: uid('f'), key: `field_${index + 1}`, type,
    label: item?.label || type.charAt(0).toUpperCase() + type.slice(1),
    required: false, width: item?.width ?? 50, placeholder: '', description: '',
    group: item?.group, caps: item?.caps || [],
    options: ['select', 'multiselect', 'radio', 'checkbox', 'cascader'].includes(type)
      ? ['Option A', 'Option B'] : undefined,
    validation: ['number', 'amount', 'slider', 'rate'].includes(type) ? { min: 0 } : undefined,
    formula: type === 'formula' ? '0' : undefined,
    serial: type === 'serial' ? { prefix: 'BX', date: true, digits: 4 } : undefined,
    show_upper: type === 'amount',
    region_level: type === 'region' ? 3 : undefined,
    columns: type === 'table' ? [
      { key: 'item', label: 'Item', type: 'text' },
      { key: 'qty', label: 'Qty', type: 'number' },
      { key: 'price', label: 'Price', type: 'number' },
      { key: 'subtotal', label: 'Subtotal', type: 'formula', formula: 'qty * price' },
    ] : undefined,
    summary: type === 'table'
      ? [{ key: 'total', label: 'Total', column: 'subtotal', op: 'sum' }] : undefined,
  }
}

const emptyRule = (): FormRule => ({ logic: 'and', conditions: [{ field: '', operator: 'eq', value: '' }] })

/** Compact condition-group editor used by display / required rules. */
function RuleEditor({ rule, fields, onChange, label }: {
  rule?: FormRule; fields: FormField[]; onChange: (r?: FormRule) => void; label: string
}) {
  const { t } = useI18n()
  const current = rule || emptyRule()
  const patch = (next: FormRule) => onChange(next)
  return (
    <div className="space-y-2 rounded-lg border bg-muted/20 p-2.5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold">{label}</span>
        <div className="flex items-center gap-1">
          {rule && <button className="text-[10px] text-muted-foreground hover:text-destructive"
            onClick={() => onChange(undefined)}><X className="h-3 w-3" /></button>}
          {!rule && <button className="text-[10px] text-primary hover:underline"
            onClick={() => patch(emptyRule())}>+ {t('forms.addRule')}</button>}
        </div>
      </div>
      {rule && <>
        <Segmented value={current.logic} onChange={(v) => patch({ ...current, logic: v as 'and' | 'or' })}
          options={[{ value: 'and', label: t('forms.and') }, { value: 'or', label: t('forms.or') }]} />
        {current.conditions.map((c, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_1fr_auto] gap-1">
            <Select className="h-7 text-[10px]" value={c.field}
              onValueChange={(v) => patch({ ...current, conditions: current.conditions.map((x, j) =>
                j === i ? { ...x, field: v } : x) })}
              options={fields.filter((f) => f.key).map((f) => ({ value: f.key, label: f.label }))}
              placeholder={t('forms.field')} />
            <Select className="h-7 text-[10px]" value={c.operator}
              onValueChange={(v) => patch({ ...current, conditions: current.conditions.map((x, j) =>
                j === i ? { ...x, operator: v } : x) })}
              options={['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'in', 'empty', 'not_empty']
                .map((o) => ({ value: o, label: o }))} />
            <Input className="h-7 px-1.5 text-[10px]" value={String(c.value ?? '')}
              onChange={(e) => patch({ ...current, conditions: current.conditions.map((x, j) =>
                j === i ? { ...x, value: e.target.value } : x) })} />
            <button className="text-muted-foreground hover:text-destructive" onClick={() =>
              patch({ ...current, conditions: current.conditions.filter((_, j) => j !== i) })}>
              <X className="h-3 w-3" /></button>
          </div>
        ))}
        <button className="text-[10px] text-primary hover:underline" onClick={() =>
          patch({ ...current, conditions: [...current.conditions, { field: '', operator: 'eq', value: '' }] })}>
          + {t('forms.addCondition')}</button>
      </>}
    </div>
  )
}

export default function Forms() {
  const { t, locale } = useI18n()
  const { can, bootstrap } = useApp()
  const { toast } = useToast()
  const [searchParams] = useSearchParams()
  const [forms, setForms] = useState<FormDef[]>([])
  const [selected, setSelected] = useState<FormDef | null>(null)
  const [fields, setFields] = useState<FormField[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [mode, setMode] = useState<'design' | 'preview'>('design')
  const [platform, setPlatform] = useState<'desktop' | 'mobile'>('desktop')
  const [propTab, setPropTab] = useState<'basic' | 'rules' | 'advanced'>('basic')
  const [search, setSearch] = useState('')
  const [saving, setSaving] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [metaOpen, setMetaOpen] = useState(false)
  const [subsOpen, setSubsOpen] = useState(false)
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [printOpen, setPrintOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [submissions, setSubmissions] = useState<FormSubmission[]>([])
  const [versions, setVersions] = useState<FormVersion[]>([])
  const [printView, setPrintView] = useState<PrintView | null>(null)
  const [preview, setPreview] = useState<Record<string, any>>({})
  const [evaluation, setEvaluation] = useState<FormEvalResult | null>(null)
  const [catalog, setCatalog] = useState<FormCatalog | null>(null)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [newForm, setNewForm] = useState({ code: '', name: '', description: '' })
  const [meta, setMeta] = useState({ name: '', description: '', status: 'draft' })
  const [versionNote, setVersionNote] = useState('')

  const groups = useMemo(() => catalog?.groups || FALLBACK_GROUPS, [catalog])
  const typeItems = useMemo(() => catalog?.fields || [], [catalog])
  const fieldTypes = useMemo(() => catalog?.field_types || bootstrap?.form.field_types ||
    FALLBACK_GROUPS.flatMap((g) => g.fields), [catalog, bootstrap])
  const activeField = fields.find((f) => f.id === activeId) || null

  const load = async () => {
    try {
      const r = await get<{ forms: FormDef[] }>('/forms')
      setForms(r.forms || [])
      return r.forms || []
    } catch { return [] }
  }
  const loadCatalog = async () => {
    try { setCatalog(await get<FormCatalog>(`/forms/meta?lang=${locale}`)) } catch { /* optional */ }
  }
  useEffect(() => { void load(); void loadCatalog() }, [])
  useEffect(() => { void loadCatalog() }, [locale])

  const select = (f: FormDef) => {
    setSelected(f); setFields(f.schema || []); setActiveId(f.schema?.[0]?.id || null)
    setMode('design'); setMeta({ name: f.name, description: f.description || '', status: f.status })
    setPreview({}); setEvaluation(null); setPlatform('desktop')
  }
  useEffect(() => {
    const code = searchParams.get('form')
    if (!code || !forms.length) return
    const target = forms.find((f) => f.code === code)
    if (target && selected?.id !== target.id) select(target)
  }, [forms, searchParams, selected?.id])

  const addField = (type: string) => {
    if (!selected) { toast(t('forms.emptyTitle'), 'info'); return }
    const item = typeItems.find((x) => x.type === type)
    const f = defaultField(type, fields.length, item)
    setFields((prev) => [...prev, f]); setActiveId(f.id); setPropTab('basic')
  }
  const patchField = (id: string, patch: Partial<FormField>) =>
    setFields((prev) => prev.map((f) => (f.id === id ? { ...f, ...patch } : f)))
  const removeField = (id: string) => {
    setFields((prev) => prev.filter((f) => f.id !== id))
    if (activeId === id) setActiveId(null)
  }
  const duplicateField = (f: FormField) => {
    const copy = { ...f, id: uid('f'), key: `${f.key}_copy`, label: `${f.label} Copy` }
    setFields((prev) => [...prev, copy]); setActiveId(copy.id)
  }
  const moveField = (from: number | null, to: number) => {
    if (from === null || from === to) return
    setFields((prev) => {
      const next = [...prev]; const [item] = next.splice(from, 1); next.splice(to, 0, item); return next
    })
  }

  const save = async (publish = false) => {
    if (!selected) return
    const keys = fields.map((f) => f.key)
    if (new Set(keys).size !== keys.length) { toast(t('forms.duplicateKey'), 'error'); return }
    setSaving(true)
    try {
      const payload = { name: meta.name, description: meta.description,
        status: publish ? 'published' : meta.status, schema: fields, layout: selected.layout }
      const updated = await put<FormDef>(`/forms/${selected.id}`, payload)
      setSelected(updated); setFields(updated.schema || [])
      await load(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
    finally { setSaving(false) }
  }
  const create = async () => {
    try {
      const f = await post<FormDef>('/forms', { ...newForm, status: 'draft', schema: [],
        layout: { columns: 2, labelWidth: 130 } })
      setCreateOpen(false); setNewForm({ code: '', name: '', description: '' })
      await load(); select(f); toast(t('common.createdOk'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const remove = async () => {
    if (!selected) return
    try { await del(`/forms/${selected.id}`); setSelected(null); setFields([]); await load(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmDelete(false) }
  }
  const openSubs = async () => {
    if (!selected) return
    const r = await get<{ submissions: FormSubmission[] }>(`/forms/${selected.id}/submissions`)
    setSubmissions(r.submissions || []); setSubsOpen(true)
  }
  const openVersions = async () => {
    if (!selected) return
    const r = await get<{ versions: FormVersion[] }>(`/forms/${selected.id}/versions`)
    setVersions(r.versions || []); setVersionsOpen(true)
  }
  const openPrint = async () => {
    if (!selected || !submissions.length) { toast(t('common.noData'), 'info'); return }
    try {
      const v = await get<PrintView>(`/forms/${selected.id}/print/${submissions[0].id}`)
      setPrintView(v); setPrintOpen(true)
    } catch (e: any) { toast(e.message, 'error') }
  }
  const evaluate = async (data: Record<string, any>) => {
    if (!selected) return
    try {
      const r = await post<FormEvalResult>(`/forms/${selected.id}/evaluate`, { data })
      setEvaluation(r); return r
    } catch { return null }
  }
  const submitPreview = async () => {
    if (!selected) return
    if (selected.status !== 'published') { toast(t('forms.publishedOnly'), 'info'); return }
    try {
      await post(`/forms/${selected.id}/submissions`, { data: preview })
      toast(t('forms.submitSuccess'), 'success'); setPreview({}); setEvaluation(null)
    } catch (e: any) { toast(e.message, 'error') }
  }
  const restoreVersion = async (v: number) => {
    if (!selected) return
    try {
      const f = await post<FormDef>(`/forms/${selected.id}/versions`, { version: v })
      setSelected(f); setFields(f.schema || []); await load(); await openVersions()
      toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const saveVersion = async () => {
    if (!selected) return
    try {
      await post(`/forms/${selected.id}/versions`, { note: versionNote || undefined })
      setVersionNote(''); await openVersions(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }

  const filtered = forms.filter((f) => !search ||
    `${f.name}${f.code}`.toLowerCase().includes(search.toLowerCase()))
  const hiddenKeys = new Set(evaluation?.hidden || [])
  const computed = evaluation?.computed || {}

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader icon={<FileText className="h-5 w-5" />} title={t('forms.title')} subtitle={t('forms.subtitle')}
        actions={<>
          <Button variant="outline" size="sm" onClick={() => { void load(); void loadCatalog() }}>
            <RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>
          {can('form:write') && <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />{t('forms.newForm')}</Button>}
        </>} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[15rem_minmax(0,1fr)_19rem]">
        {/* Form list + palette */}
        <div className="space-y-4">
          <Card><CardContent className="p-3">
            <Input className="h-8 text-xs" placeholder={t('common.searchPlaceholder')}
              value={search} onChange={(e) => setSearch(e.target.value)} />
            <div className="scroll-thin mt-2 max-h-48 space-y-1 overflow-y-auto">
              {filtered.map((f) => (
                <button key={f.id} onClick={() => select(f)}
                  className={cn('flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-all',
                    selected?.id === f.id ? 'bg-primary/10 text-primary' : 'hover:bg-muted')}>
                  <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-medium">{f.name}</span>
                    <span className="block truncate font-mono text-[10px] text-muted-foreground">{f.code}</span>
                  </span>
                  <Badge variant={f.status === 'published' ? 'success' : 'muted'} className="shrink-0 text-[9px]">
                    {f.status}</Badge>
                </button>
              ))}
              {!filtered.length && <p className="py-6 text-center text-xs text-muted-foreground">{t('common.noData')}</p>}
            </div>
          </CardContent></Card>

          {selected && mode === 'design' && (
            <Card><CardContent className="p-3">
              <div className="mb-2 flex items-center justify-between">
                <SectionTitle>{t('forms.fields')}</SectionTitle>
                <Badge variant="muted" className="text-[9px]">{fieldTypes.length}</Badge>
              </div>
              <div className="scroll-thin max-h-[26rem] space-y-2 overflow-y-auto pr-1">
                {groups.map((g) => {
                  const Icon = GROUP_ICONS[g.code] || Type
                  const items = g.fields.filter((x) => fieldTypes.includes(x))
                  if (!items.length) return null
                  return (
                    <div key={g.code}>
                      <button className="mb-1 flex w-full items-center gap-1.5 text-left"
                        onClick={() => setCollapsed((p) => ({ ...p, [g.code]: !p[g.code] }))}>
                        <Icon className="h-3 w-3 text-primary" />
                        <span className="flex-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                          {g.label}</span>
                        {collapsed[g.code] ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
                      </button>
                      {!collapsed[g.code] && <div className="grid grid-cols-2 gap-1.5">
                        {items.map((type) => {
                          const item = typeItems.find((x) => x.type === type)
                          const FIcon = FIELD_ICONS[type] || Type
                          return (
                            <button key={type} onClick={() => addField(type)}
                              title={item?.label || type}
                              className="flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-left text-[11px] transition-all hover:border-primary/40 hover:bg-primary/5 hover:shadow-sm">
                              <FIcon className="h-3.5 w-3.5 shrink-0 text-primary" />
                              <span className="truncate">{item?.label || t(`forms.fieldTypes.${type}`)}</span>
                            </button>
                          )
                        })}
                      </div>}
                    </div>
                  )
                })}
              </div>
              <p className="mt-2 text-[10px] text-muted-foreground">{t('forms.dropHint')}</p>
            </CardContent></Card>
          )}
        </div>

        {/* Canvas */}
        <Card className="min-h-[34rem]">
          {!selected ? (
            <EmptyState icon={<FileText className="h-5 w-5" />} title={t('forms.emptyTitle')}
              description={t('forms.emptyText')}
              action={can('form:write') ? <Button size="sm" onClick={() => setCreateOpen(true)}>
                <Plus className="h-3.5 w-3.5" />{t('forms.newForm')}</Button> : undefined} />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h2 className="truncate text-sm font-semibold">{meta.name}</h2>
                    <Badge variant={meta.status === 'published' ? 'success' : 'muted'}>{meta.status}</Badge>
                    <span className="font-mono text-[10px] text-muted-foreground">v{selected.version}</span>
                  </div>
                  <p className="truncate text-[11px] text-muted-foreground">
                    {t('forms.fieldCount', { count: fields.length })} · {selected.code}</p>
                </div>
                <Segmented value={mode} onChange={setMode} options={[
                  { value: 'design', label: t('forms.designMode'), icon: <PencilRuler className="h-3 w-3" /> },
                  { value: 'preview', label: t('forms.previewMode'), icon: <Eye className="h-3 w-3" /> },
                ]} />
                {mode === 'preview' && <Segmented value={platform} onChange={setPlatform} options={[
                  { value: 'desktop', label: t('forms.desktop'), icon: <Monitor className="h-3 w-3" /> },
                  { value: 'mobile', label: t('forms.mobile'), icon: <Smartphone className="h-3 w-3" /> },
                ]} />}
              </div>

              <div className="scroll-thin max-h-[calc(100vh-19rem)] min-h-[26rem] overflow-y-auto bg-muted/20 p-4">
                {mode === 'design' ? (
                  <div className="mx-auto max-w-3xl rounded-xl border bg-card p-5 shadow-sm">
                    <div className="mb-4 border-b pb-3">
                      <h3 className="text-base font-semibold">{meta.name || t('forms.formName')}</h3>
                      {meta.description && <p className="mt-1 text-xs text-muted-foreground">{meta.description}</p>}
                    </div>
                    {!fields.length && <div className="rounded-lg border border-dashed py-12 text-center text-xs text-muted-foreground">
                      {t('forms.dropHint')}</div>}
                    <div className="grid grid-cols-2 gap-3">
                      {fields.map((f, i) => {
                        const Icon = FIELD_ICONS[f.type] || Type
                        return (
                          <div key={f.id} draggable
                            onDragStart={() => setDragIndex(i)}
                            onDragOver={(e) => { e.preventDefault() }}
                            onDrop={() => { moveField(dragIndex, i); setDragIndex(null) }}
                            onClick={() => setActiveId(f.id)}
                            className={cn('group relative cursor-pointer rounded-lg border bg-background/60 p-3 transition-all hover:border-primary/40 hover:shadow-sm',
                              f.width === 100 && 'col-span-2',
                              activeId === f.id && 'border-primary ring-2 ring-primary/15')}>
                            <div className="mb-2 flex items-center gap-2">
                              <GripVertical className="h-3.5 w-3.5 shrink-0 cursor-grab text-muted-foreground/60" />
                              <Icon className="h-3.5 w-3.5 shrink-0 text-primary" />
                              <span className="truncate text-xs font-medium">
                                {f.label}{f.required && <span className="ml-0.5 text-destructive">*</span>}</span>
                              {f.formula && <Calculator className="h-3 w-3 shrink-0 text-amber-500" />}
                              {f.visible_when && <GitBranch className="h-3 w-3 shrink-0 text-violet-500" />}
                              {f.permission && f.permission !== 'editable' &&
                                <ShieldCheck className="h-3 w-3 shrink-0 text-sky-500" />}
                              <div className="ml-auto flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                                <Button variant="ghost" size="icon-sm" onClick={(e) => { e.stopPropagation(); duplicateField(f) }}>
                                  <Copy className="h-3 w-3" /></Button>
                                <Button variant="ghost" size="icon-sm" onClick={(e) => { e.stopPropagation(); removeField(f.id) }}>
                                  <Trash2 className="h-3 w-3 text-destructive" /></Button>
                              </div>
                            </div>
                            <PreviewField field={f} value={undefined} onChange={() => {}} disabled />
                            <span className="mt-1.5 block font-mono text-[9px] text-muted-foreground">
                              {f.key} · {f.type}{f.group ? ` · ${f.group}` : ''}</span>
                          </div>
                        )
                      })}
                    </div>
                    <p className="mt-4 text-center text-[10px] text-muted-foreground">{t('forms.dragHint')}</p>
                  </div>
                ) : (
                  <div className={cn('mx-auto rounded-xl border bg-card p-6 shadow-sm transition-all',
                    platform === 'mobile' ? 'max-w-[26rem]' : 'max-w-3xl')}>
                    <h3 className="text-base font-semibold">{meta.name}</h3>
                    <p className="mb-5 mt-1 text-xs text-muted-foreground">{t('forms.fillPreview')}</p>
                    <div className={cn('grid gap-4', platform === 'mobile' ? 'grid-cols-1' : 'grid-cols-2')}>
                      {fields.filter((f) => !hiddenKeys.has(f.key) && !(platform === 'mobile' && f.mobile_hidden)).map((f) => (
                        <div key={f.id} className={cn((f.width === 100 || platform === 'mobile') && 'col-span-2', 'space-y-1.5')}>
                          <Label className="block">{f.label}{f.required && <span className="ml-0.5 text-destructive">*</span>}
                            {computed[`${f.key}_upper`] ? <span className="ml-2 text-[10px] text-muted-foreground">
                              {String(computed[`${f.key}_upper`])}</span> : null}</Label>
                          <PreviewField field={f} value={preview[f.key]}
                            onChange={(v) => setPreview((p) => ({ ...p, [f.key]: v }))} />
                          {computed[`${f.key}_info`] ? <p className="text-[10px] text-muted-foreground">
                            {JSON.stringify(computed[`${f.key}_info`])}</p> : null}
                        </div>
                      ))}
                    </div>
                    {!!hiddenKeys.size && <p className="mt-3 text-[10px] text-muted-foreground">
                      {t('forms.hiddenFields')}: {[...hiddenKeys].join(', ')}</p>}
                    {!!Object.keys(evaluation?.summaries || {}).length && (
                      <div className="mt-3 rounded-lg bg-primary/5 p-2 text-xs">
                        {Object.entries(evaluation!.summaries).map(([k, v]) => (
                          <span key={k} className="mr-4 font-medium">{k}: {v}</span>
                        ))}
                      </div>
                    )}
                    <div className="mt-6 flex flex-wrap items-center gap-2 border-t pt-4">
                      <Button size="sm" onClick={submitPreview}><Send className="h-3.5 w-3.5" />{t('forms.submitPreview')}</Button>
                      <Button variant="outline" size="sm" onClick={() => void evaluate(preview)}>
                        <Calculator className="h-3.5 w-3.5" />{t('forms.compute')}</Button>
                      <Button variant="ghost" size="sm" onClick={() => { setPreview({}); setEvaluation(null) }}>
                        {t('common.reset')}</Button>
                      {!!evaluation?.errors.length && <span className="text-[11px] text-destructive">
                        {evaluation.errors.map((e) => e.message).join('; ')}</span>}
                      <span className="ml-auto text-[11px] text-muted-foreground">{t('forms.publishedOnly')}</span>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2 border-t px-4 py-3">
                <Button variant="outline" size="sm" onClick={() => setMetaOpen(true)}>
                  <Settings2 className="h-3.5 w-3.5" />{t('common.settings')}</Button>
                <Button variant="outline" size="sm" onClick={openSubs}>
                  <Layers className="h-3.5 w-3.5" />{t('forms.submissions')}</Button>
                <Button variant="outline" size="sm" onClick={openVersions}>
                  <History className="h-3.5 w-3.5" />{t('forms.versions')}</Button>
                <Button variant="outline" size="sm" onClick={() => void openPrint()}>
                  <Printer className="h-3.5 w-3.5" />{t('forms.print')}</Button>
                <Button variant="outline" size="sm" onClick={() => selected &&
                  download(`/forms/${selected.id}/submissions/export`, `${selected.code}.csv`)}>
                  <Download className="h-3.5 w-3.5" />CSV</Button>
                <div className="ml-auto flex flex-wrap gap-2">
                  <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)} disabled={!can('form:write')}>
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />{t('common.delete')}</Button>
                  <Button variant="outline" size="sm" loading={saving} onClick={() => save(false)} disabled={!can('form:write')}>
                    <Save className="h-3.5 w-3.5" />{t('forms.saveDraft')}</Button>
                  <Button size="sm" loading={saving} onClick={() => save(true)} disabled={!can('form:publish')}>
                    <CheckSquare className="h-3.5 w-3.5" />{t('forms.publish')}</Button>
                </div>
              </div>
            </>
          )}
        </Card>

        {/* Properties */}
        <Card className="h-fit"><CardContent className="p-4">
          <SectionTitle>{t('forms.properties')}</SectionTitle>
          {!activeField || mode !== 'design' ? (
            <p className="py-8 text-center text-xs text-muted-foreground">{t('forms.dropHint')}</p>
          ) : (
            <>
              <div className="mb-3"><Segmented value={propTab} onChange={setPropTab} options={[
                { value: 'basic', label: t('forms.tabBasic') },
                { value: 'rules', label: t('forms.tabRules') },
                { value: 'advanced', label: t('forms.tabAdvanced') },
              ]} /></div>
              {propTab === 'basic' && <div className="space-y-3">
                <Field label={t('forms.fieldLabel')}>
                  <Input value={activeField.label} onChange={(e) => patchField(activeField.id, { label: e.target.value })} />
                </Field>
                <Field label={t('forms.fieldKey')}>
                  <Input className="font-mono text-xs" value={activeField.key}
                    onChange={(e) => patchField(activeField.id, { key: e.target.value.replace(/[^a-zA-Z0-9_]/g, '') })} />
                </Field>
                <Field label={t('common.type')}>
                  <Select value={activeField.type} onValueChange={(v) => patchField(activeField.id, { type: v })}
                    options={fieldTypes.map((x) => ({ value: x,
                      label: typeItems.find((i) => i.type === x)?.label || t(`forms.fieldTypes.${x}`) }))} />
                </Field>
                <Field label={t('forms.placeholder')}>
                  <Input value={activeField.placeholder || ''}
                    onChange={(e) => patchField(activeField.id, { placeholder: e.target.value })} />
                </Field>
                {['select', 'multiselect', 'radio', 'checkbox', 'cascader'].includes(activeField.type) && (
                  <Field label={t('forms.options')} hint="one per line">
                    <Textarea rows={3} value={(activeField.options || []).join('\n')}
                      onChange={(e) => patchField(activeField.id, { options: e.target.value.split('\n') })} />
                  </Field>
                )}
                <Field label={t('forms.width')}>
                  <Segmented value={activeField.width === 100 ? 'full' : 'half'}
                    onChange={(v) => patchField(activeField.id, { width: v === 'full' ? 100 : 50 })}
                    options={[{ value: 'half', label: t('forms.half') }, { value: 'full', label: t('forms.full') }]} />
                </Field>
                <Field label={t('forms.defaultValue')}>
                  <Input value={String(activeField.defaultValue ?? '')}
                    onChange={(e) => patchField(activeField.id, { defaultValue: e.target.value })} />
                </Field>
                <div className="flex items-center justify-between rounded-lg border px-3 py-2">
                  <span className="text-xs font-medium">{t('forms.requiredField')}</span>
                  <Switch checked={!!activeField.required}
                    onCheckedChange={(v) => patchField(activeField.id, { required: v })} />
                </div>
              </div>}

              {propTab === 'rules' && <div className="space-y-3">
                <RuleEditor label={t('forms.visibleWhen')} fields={fields} rule={activeField.visible_when}
                  onChange={(r) => patchField(activeField.id, { visible_when: r })} />
                <RuleEditor label={t('forms.requiredWhen')} fields={fields} rule={activeField.required_when}
                  onChange={(r) => patchField(activeField.id, { required_when: r })} />
                <Field label={t('forms.formula')} hint="SUM / TABLE_SUM / IF / CNY_UPPER ...">
                  <Input className="font-mono text-xs" value={activeField.formula || ''}
                    placeholder="qty * price" onChange={(e) => patchField(activeField.id, { formula: e.target.value })} />
                </Field>
                {catalog && <div className="rounded-lg border bg-muted/20 p-2">
                  <p className="mb-1 text-[10px] font-semibold text-muted-foreground">{t('forms.functions')}</p>
                  <div className="flex flex-wrap gap-1">
                    {catalog.functions.map((f) => (
                      <button key={f.code} title={f.args || f.label}
                        onClick={() => patchField(activeField.id,
                          { formula: `${activeField.formula || ''}${f.code}(` })}
                        className="rounded border bg-background px-1.5 py-0.5 font-mono text-[9px] hover:border-primary/40">
                        {f.code}</button>
                    ))}
                  </div>
                </div>}
                <Field label={t('forms.fieldPermission')}>
                  <Select value={activeField.permission || 'editable'}
                    onValueChange={(v) => patchField(activeField.id, { permission: v as FormField['permission'] })}
                    options={(catalog?.permission_modes || [
                      { code: 'editable', label: 'Editable' }, { code: 'readonly', label: 'Read only' },
                      { code: 'hidden', label: 'Hidden' }]).map((m) => ({ value: m.code, label: m.label }))} />
                </Field>
              </div>}

              {propTab === 'advanced' && <div className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  <Field label={t('forms.min')}><Input type="number" value={(activeField.validation as any)?.min ?? ''}
                    onChange={(e) => patchField(activeField.id, { validation: {
                      ...(activeField.validation || {}), min: Number(e.target.value) } })} /></Field>
                  <Field label={t('forms.max')}><Input type="number" value={(activeField.validation as any)?.max ?? ''}
                    onChange={(e) => patchField(activeField.id, { validation: {
                      ...(activeField.validation || {}), max: Number(e.target.value) } })} /></Field>
                  <Field label={t('forms.minLength')}><Input type="number" value={(activeField.validation as any)?.min_length ?? ''}
                    onChange={(e) => patchField(activeField.id, { validation: {
                      ...(activeField.validation || {}), min_length: Number(e.target.value) } })} /></Field>
                  <Field label={t('forms.maxLength')}><Input type="number" value={(activeField.validation as any)?.max_length ?? ''}
                    onChange={(e) => patchField(activeField.id, { validation: {
                      ...(activeField.validation || {}), max_length: Number(e.target.value) } })} /></Field>
                </div>
                <Field label={t('forms.regex')}>
                  <Input className="font-mono text-xs" value={(activeField.validation as any)?.regex ?? ''}
                    onChange={(e) => patchField(activeField.id, { validation: {
                      ...(activeField.validation || {}), regex: e.target.value } })} />
                </Field>
                <div className="flex items-center justify-between rounded-lg border px-3 py-2">
                  <span className="text-xs font-medium">{t('forms.unique')}</span>
                  <Switch checked={!!(activeField.validation as any)?.unique}
                    onCheckedChange={(v) => patchField(activeField.id, { validation: {
                      ...(activeField.validation || {}), unique: v } })} />
                </div>
                {activeField.type === 'amount' && <div className="flex items-center justify-between rounded-lg border px-3 py-2">
                  <span className="text-xs font-medium">{t('forms.showUpper')}</span>
                  <Switch checked={!!activeField.show_upper}
                    onCheckedChange={(v) => patchField(activeField.id, { show_upper: v })} />
                </div>}
                {activeField.type === 'table' && <Field label={t('forms.detailColumns')} hint="JSON array">
                  <Textarea rows={6} className="font-mono text-[10px]"
                    value={JSON.stringify(activeField.columns || [], null, 2)}
                    onChange={(e) => { try { patchField(activeField.id,
                      { columns: JSON.parse(e.target.value) }) } catch { /* keep typing */ } }} />
                </Field>}
                <Field label={t('forms.description')}>
                  <Textarea rows={2} value={activeField.description || ''}
                    onChange={(e) => patchField(activeField.id, { description: e.target.value })} />
                </Field>
                <div className="flex items-center justify-between rounded-lg border px-3 py-2">
                  <span className="text-xs font-medium">{t('forms.mobileHidden')}</span>
                  <Switch checked={!!activeField.mobile_hidden}
                    onCheckedChange={(v) => patchField(activeField.id, { mobile_hidden: v })} />
                </div>
                <Button variant="outline" size="sm" className="w-full" onClick={() => removeField(activeField.id)}>
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />{t('common.remove')}</Button>
              </div>}
            </>
          )}
        </CardContent></Card>
      </div>

      {/* Dialogs */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen} title={t('forms.createTitle')} size="md"
        footer={<><Button variant="outline" onClick={() => setCreateOpen(false)}>{t('common.cancel')}</Button>
          <Button onClick={create}>{t('common.create')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('forms.formCode')} hint="lowercase, underscores">
            <Input value={newForm.code} onChange={(e) => setNewForm({ ...newForm, code: e.target.value })}
              placeholder="my_form" /></Field>
          <Field label={t('forms.formName')}>
            <Input value={newForm.name} onChange={(e) => setNewForm({ ...newForm, name: e.target.value })} /></Field>
          <Field label={t('common.description')}>
            <Textarea value={newForm.description}
              onChange={(e) => setNewForm({ ...newForm, description: e.target.value })} /></Field>
        </div>
      </Dialog>

      <Dialog open={metaOpen} onOpenChange={setMetaOpen} title={t('forms.editTitle')} size="md"
        footer={<><Button variant="outline" onClick={() => setMetaOpen(false)}>{t('common.cancel')}</Button>
          <Button onClick={() => { setMetaOpen(false); void save(false) }}>{t('common.save')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('forms.formName')}><Input value={meta.name}
            onChange={(e) => setMeta({ ...meta, name: e.target.value })} /></Field>
          <Field label={t('common.description')}><Textarea value={meta.description}
            onChange={(e) => setMeta({ ...meta, description: e.target.value })} /></Field>
          <Field label={t('forms.statusLabel')}>
            <Select value={meta.status} onValueChange={(v) => setMeta({ ...meta, status: v })}
              options={(bootstrap?.form.statuses || ['draft', 'published', 'archived'])
                .map((s) => ({ value: s, label: t(`common.${s}`) }))} />
          </Field>
        </div>
      </Dialog>

      <Dialog open={subsOpen} onOpenChange={setSubsOpen}
        title={t('forms.submissionsTitle', { name: selected?.name || '' })} size="xl">
        <Table><TableHeader><TableRow>
          <TableHead>ID</TableHead><TableHead>{t('forms.serial')}</TableHead>
          <TableHead>{t('audit.actor')}</TableHead><TableHead>{t('common.status')}</TableHead>
          <TableHead>{t('audit.details')}</TableHead><TableHead>{t('audit.time')}</TableHead>
        </TableRow></TableHeader><TableBody>
          {submissions.map((s) => <TableRow key={s.id}>
            <TableCell className="font-mono text-xs">#{s.id}</TableCell>
            <TableCell className="font-mono text-[10px]">{s.serial_no || '-'} / v{s.form_version || 1}</TableCell>
            <TableCell className="text-xs">{s.submitted_by}</TableCell>
            <TableCell><Badge variant={s.status === 'approved' ? 'success' : 'default'}>{s.status}</Badge></TableCell>
            <TableCell className="max-w-xs truncate font-mono text-[10px] text-muted-foreground">
              {JSON.stringify(s.data)}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{formatDate(s.created_at, locale)}</TableCell>
          </TableRow>)}
          {!submissions.length && <TableRow><TableCell colSpan={6} className="py-8 text-center text-xs text-muted-foreground">
            {t('common.noData')}</TableCell></TableRow>}
        </TableBody></Table>
      </Dialog>

      <Dialog open={versionsOpen} onOpenChange={setVersionsOpen} title={t('forms.versions')} size="md"
        footer={<><Input className="h-8 flex-1 text-xs" placeholder={t('forms.versionNote')}
          value={versionNote} onChange={(e) => setVersionNote(e.target.value)} />
          <Button size="sm" onClick={saveVersion}><Save className="h-3.5 w-3.5" />{t('forms.saveVersion')}</Button></>}>
        <div className="space-y-2">
          {versions.map((v) => (
            <div key={v.id} className="flex items-center gap-2 rounded-lg border px-3 py-2">
              <Badge variant="muted">v{v.version}</Badge>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs">{v.note || '-'}</p>
                <p className="text-[10px] text-muted-foreground">
                  {(v.schema || []).length} fields · {formatDate(v.created_at, locale)}</p>
              </div>
              {can('form:write') && <Button variant="outline" size="sm"
                onClick={() => void restoreVersion(v.version)}>{t('forms.restore')}</Button>}
            </div>
          ))}
          {!versions.length && <p className="py-6 text-center text-xs text-muted-foreground">{t('common.noData')}</p>}
        </div>
      </Dialog>

      <Dialog open={printOpen} onOpenChange={setPrintOpen} title={t('forms.printPreview')} size="lg"
        footer={<Button variant="outline" onClick={() => setPrintOpen(false)}>{t('common.close')}</Button>}>
        {printView && <div className="space-y-3">
          <div className="border-b pb-2 text-center">
            <h3 className="text-base font-semibold">{printView.form.name}</h3>
            <p className="text-[11px] text-muted-foreground">
              {printView.serial_no || '-'} · {printView.submitted_by} · {formatDate(printView.created_at, locale)}</p>
          </div>
          <Table><TableBody>
            {printView.fields.map((f, i) => <TableRow key={i}>
              <TableCell className="w-1/3 text-xs font-medium">{f.label}</TableCell>
              <TableCell className="text-xs">
                {f.value === null || f.value === undefined || f.value === '' ? '-' : String(f.value)}
                {f.upper && <div className="mt-0.5 text-[10px] text-muted-foreground">{t('forms.rmbUpper')}: {f.upper}</div>}
              </TableCell>
            </TableRow>)}
          </TableBody></Table>
          {!!Object.keys(printView.summaries || {}).length && <div className="rounded-lg bg-muted/30 p-2 text-xs">
            {Object.entries(printView.summaries).map(([k, v]) => <span key={k} className="mr-4">{k}: {v}</span>)}
          </div>}
        </div>}
      </Dialog>

      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} title={t('common.confirmDelete')}
        description={selected?.name} onConfirm={remove} />
    </div>
  )
}

/** Renderer shared by the design canvas and the fill preview. */
export function PreviewField({ field, value, onChange, disabled = false }: {
  field: FormField; value: any; onChange: (v: any) => void; disabled?: boolean
}) {
  const { t } = useI18n()
  const common = 'h-8 w-full rounded-md border border-input bg-background/60 px-2.5 text-xs disabled:opacity-60'
  const ftype = field.type
  if (ftype === 'divider') return <div className="my-1 border-t border-dashed" />
  if (ftype === 'description') return <div className="rounded-md bg-muted/40 px-2 py-1.5 text-[10px] text-muted-foreground">
    <Info className="mr-1 inline h-3 w-3" />{field.description || field.label}</div>
  if (['grid', 'tabs', 'collapse'].includes(ftype)) return <div className="rounded-md border border-dashed py-2 text-center text-[10px] text-muted-foreground">
    <LayoutGrid className="mr-1 inline h-3 w-3" />{field.label}</div>
  if (ftype === 'textarea' || ftype === 'richtext') return <Textarea className="min-h-[62px] text-xs"
    disabled={disabled} placeholder={field.placeholder} value={value ?? ''}
    onChange={(e) => onChange(e.target.value)} />
  if (['select', 'multiselect', 'radio', 'checkbox', 'cascader'].includes(ftype)) {
    if (ftype === 'checkbox' && !disabled) return <div className="flex flex-wrap gap-1.5">
      {(field.options || []).map((o) => {
        const on = Array.isArray(value) && value.includes(o)
        return <button key={o} onClick={() => onChange(on
          ? (value as string[]).filter((x) => x !== o) : [...(value || []), o])}
          className={cn('rounded-md border px-2 py-1 text-[10px] transition-colors',
            on ? 'border-primary bg-primary/10 text-primary' : 'hover:bg-muted')}>{o}</button>
      })}
    </div>
    return <Select className="h-8 text-xs" disabled={disabled} value={value ?? ''} onValueChange={onChange}
      placeholder={t('common.select')} options={(field.options || []).map((o) => ({ value: o, label: o }))} />
  }
  if (ftype === 'switch') return <div className="flex h-8 items-center">
    <Switch checked={!!value} onCheckedChange={onChange} disabled={disabled} /></div>
  if (ftype === 'slider') return <input type="range" min={Number((field.validation as any)?.min ?? 0)}
    max={Number((field.validation as any)?.max ?? 100)} disabled={disabled} value={Number(value ?? 0)}
    onChange={(e) => onChange(Number(e.target.value))} className="h-8 w-full accent-primary" />
  if (ftype === 'rate') return <div className="flex h-8 items-center gap-1">
    {[1, 2, 3, 4, 5].map((n) => <button key={n} disabled={disabled} onClick={() => onChange(n)}
      className={cn('text-base leading-none transition-colors',
        Number(value) >= n ? 'text-amber-500' : 'text-muted-foreground/40')}>★</button>)}
  </div>
  if (ftype === 'color') return <input type="color" disabled={disabled} value={value || '#6366f1'}
    onChange={(e) => onChange(e.target.value)} className="h-8 w-full rounded-md border bg-background" />
  if (ftype === 'formula' || ftype === 'serial') return <Input className={cn(common, 'font-mono')}
    value={value ?? (ftype === 'formula' ? t('forms.computed') : t('forms.serialAuto'))} disabled readOnly />
  if (ftype === 'table') {
    const rows: Record<string, any>[] = Array.isArray(value) ? value : []
    const cols = field.columns || []
    const update = (i: number, key: string, v: any) => onChange(rows.map((r, j) => j === i ? { ...r, [key]: v } : r))
    return <div className="rounded-md border">
      <div className="overflow-x-auto"><table className="w-full text-[10px]">
        <thead><tr className="border-b bg-muted/30">
          {cols.map((c) => <th key={c.key} className="px-2 py-1.5 text-left font-medium">{c.label}</th>)}
          {!disabled && <th className="w-8" />}
        </tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i} className="border-b last:border-0">
          {cols.map((c) => <td key={c.key} className="px-1 py-1">
            {c.type === 'formula' ? <span className="font-mono text-primary">
              {Number(r[c.key] ?? 0)}</span>
              : <Input className="h-6 px-1.5 text-[10px]" disabled={disabled} value={r[c.key] ?? ''}
                onChange={(e) => update(i, c.key, e.target.value)} />}
          </td>)}
          {!disabled && <td><button onClick={() => onChange(rows.filter((_, j) => j !== i))}>
            <X className="h-3 w-3 text-destructive" /></button></td>}
        </tr>)}
        {!rows.length && <tr><td colSpan={cols.length + 1} className="px-2 py-3 text-center text-muted-foreground">
          {t('common.noData')}</td></tr>}
        </tbody>
      </table></div>
      {!disabled && <button className="flex w-full items-center justify-center gap-1 border-t py-1.5 text-[10px] text-primary hover:bg-primary/5"
        onClick={() => onChange([...rows, Object.fromEntries(cols.map((c) => [c.key, '']))])}>
        <Plus className="h-3 w-3" />{t('forms.addRow')}</button>}
    </div>
  }
  if (['attachment', 'image', 'ocr'].includes(ftype)) return <label className={cn(common,
    'flex cursor-pointer items-center gap-2 text-muted-foreground')}>
    <UploadCloud className="h-3.5 w-3.5" />
    <span className="truncate">{value ? String(value) : t('forms.uploadFile')}</span>
    <input type="file" className="hidden" disabled={disabled}
      onChange={(e) => onChange(e.target.files?.[0]?.name || '')} />
  </label>
  if (ftype === 'signature') return <div className="rounded-md border border-dashed px-2 py-1.5 text-center text-[10px] text-muted-foreground">
    <PenLine className="mr-1 inline h-3 w-3" />{value ? t('forms.signed') : t('forms.signHere')}</div>
  if (ftype === 'region') return <div className="grid grid-cols-3 gap-1">
    {['Province', 'City', 'District'].map((_, i) => <Input key={i} className={cn(common, 'px-1.5 text-[10px]')}
      disabled={disabled} placeholder={['省', '市', '区'][i]}
      value={(Array.isArray(value) ? value[i] : '') || ''}
      onChange={(e) => { const arr = Array.isArray(value) ? [...value] : []
        arr[i] = e.target.value; onChange(arr) }} />)}
  </div>
  const inputType = ['date', 'datetime', 'time', 'email', 'url', 'number'].includes(ftype) ? ftype
    : ['mobile', 'tel', 'idcard', 'bankcard', 'uscc', 'amount', 'qrcode', 'location'].includes(ftype) ? 'text' : 'text'
  return <Input className={common} type={inputType} disabled={disabled}
    placeholder={field.placeholder || (ftype === 'idcard' ? '18-digit PRC ID' :
      ftype === 'uscc' ? '18-digit USCC' : ftype === 'amount' ? '0.00' : '')}
    value={value ?? ''} onChange={(e) => onChange(
      ['number', 'amount', 'slider', 'rate'].includes(ftype) && e.target.value !== ''
        ? Number(e.target.value) : e.target.value)} />
}
