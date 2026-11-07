import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  AlignLeft, CalendarDays, CheckSquare, ChevronDown, Copy, FileText, GripVertical,
  Hash, ListFilter, Paperclip, Plus, Save, Send, Settings2, Table2, ToggleLeft,
  Trash2, Type, UserRound, Users, Eye, PencilRuler, Minus, RefreshCw, CircleDot, Layers,
} from 'lucide-react'
import { PageHeader, SectionTitle } from '@/components/PageHeader'
import {
  Badge, Button, Card, CardContent, EmptyState, Field, Input, Label, Segmented,
  Select, Switch, Textarea,
} from '@/components/ui/basic'
import { ConfirmDialog, Dialog, useToast } from '@/components/ui/overlay'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { del, get, post, put } from '@/lib/api'
import { cn, formatDate, uid } from '@/lib/utils'
import type { FormDef, FormField, FormSubmission } from '@/types'

const FIELD_ICONS: Record<string, typeof Type> = {
  text: Type, textarea: AlignLeft, number: Hash, select: ListFilter, multiselect: ListFilter,
  date: CalendarDays, datetime: CalendarDays, switch: ToggleLeft, radio: CircleDot,
  user: UserRound, department: Users, table: Table2, attachment: Paperclip, divider: Minus,
}
const BASIC = ['text', 'textarea', 'number', 'select', 'date', 'switch']
const ADVANCED = ['multiselect', 'datetime', 'radio', 'user', 'department', 'table', 'attachment']
const LAYOUT = ['divider']

function defaultField(type: string, index: number): FormField {
  return {
    id: uid('f'), key: `field_${index + 1}`, type,
    label: type.charAt(0).toUpperCase() + type.slice(1), required: false,
    width: type === 'divider' ? 100 : 50, placeholder: '',
    options: ['select', 'multiselect', 'radio'].includes(type) ? ['Option A', 'Option B'] : undefined,
  }
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
  const [search, setSearch] = useState('')
  const [saving, setSaving] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [metaOpen, setMetaOpen] = useState(false)
  const [subsOpen, setSubsOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [submissions, setSubmissions] = useState<FormSubmission[]>([])
  const [preview, setPreview] = useState<Record<string, any>>({})
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [newForm, setNewForm] = useState({ code: '', name: '', description: '' })
  const [meta, setMeta] = useState({ name: '', description: '', status: 'draft' })

  const fieldTypes = useMemo(() => bootstrap?.form.field_types || [...BASIC, ...ADVANCED, ...LAYOUT], [bootstrap])
  const activeField = fields.find((f) => f.id === activeId) || null

  const load = async () => {
    try {
      const r = await get<{ forms: FormDef[] }>('/forms')
      setForms(r.forms || [])
      return r.forms || []
    } catch { return [] }
  }
  useEffect(() => { void load() }, [])

  const select = (f: FormDef) => {
    setSelected(f); setFields(f.schema || []); setActiveId(f.schema?.[0]?.id || null)
    setMode('design'); setMeta({ name: f.name, description: f.description || '', status: f.status })
    setPreview({})
  }

  // Deep link: /#/forms?form=leave_request opens a specific designer directly.
  useEffect(() => {
    const code = searchParams.get('form')
    if (!code || !forms.length) return
    const target = forms.find((f) => f.code === code)
    if (target && selected?.id !== target.id) select(target)
  }, [forms, searchParams, selected?.id])

  const addField = (type: string) => {
    if (!selected) { toast(t('forms.emptyTitle'), 'info'); return }
    const f = defaultField(type, fields.length)
    setFields((prev) => [...prev, f]); setActiveId(f.id)
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
      await load()
      toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
    finally { setSaving(false) }
  }

  const create = async () => {
    try {
      const f = await post<FormDef>('/forms', { ...newForm, status: 'draft', schema: [], layout: { columns: 2, labelWidth: 130 } })
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

  const submitPreview = async () => {
    if (!selected) return
    if (selected.status !== 'published') { toast(t('forms.publishedOnly'), 'info'); return }
    try {
      await post(`/forms/${selected.id}/submissions`, { data: preview })
      toast(t('forms.submitSuccess'), 'success'); setPreview({})
    } catch (e: any) { toast(e.message, 'error') }
  }

  const filtered = forms.filter((f) => !search ||
    `${f.name}${f.code}`.toLowerCase().includes(search.toLowerCase()))

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader icon={<FileText className="h-5 w-5" />} title={t('forms.title')} subtitle={t('forms.subtitle')}
        actions={<>
          <Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>
          {can('form:write') && <Button size="sm" onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" />{t('forms.newForm')}</Button>}
        </>} />

      <div className="grid gap-4 lg:grid-cols-[15rem_minmax(0,1fr)_18rem]">
        {/* Form list + palette */}
        <div className="space-y-4">
          <Card>
            <CardContent className="p-3">
              <Input className="h-8 text-xs" placeholder={t('common.searchPlaceholder')} value={search} onChange={(e) => setSearch(e.target.value)} />
              <div className="scroll-thin mt-2 max-h-56 space-y-1 overflow-y-auto">
                {filtered.map((f) => (
                  <button key={f.id} onClick={() => select(f)}
                    className={cn('flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-all',
                      selected?.id === f.id ? 'bg-primary/10 text-primary' : 'hover:bg-muted')}>
                    <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-medium">{f.name}</span>
                      <span className="block truncate font-mono text-[10px] text-muted-foreground">{f.code}</span>
                    </span>
                    <Badge variant={f.status === 'published' ? 'success' : 'muted'} className="shrink-0 text-[9px]">{f.status}</Badge>
                  </button>
                ))}
                {!filtered.length && <p className="py-6 text-center text-xs text-muted-foreground">{t('common.noData')}</p>}
              </div>
            </CardContent>
          </Card>

          {selected && mode === 'design' && (
            <Card>
              <CardContent className="p-3">
                <SectionTitle>{t('forms.fields')}</SectionTitle>
                {[
                  { key: 'forms.basic', types: BASIC },
                  { key: 'forms.advanced', types: ADVANCED },
                  { key: 'forms.layout', types: LAYOUT },
                ].map((group) => (
                  <div key={group.key} className="mb-3">
                    <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{t(group.key)}</p>
                    <div className="grid grid-cols-2 gap-1.5">
                      {group.types.filter((x) => fieldTypes.includes(x)).map((type) => {
                        const Icon = FIELD_ICONS[type] || Type
                        return (
                          <button key={type} onClick={() => addField(type)}
                            className="flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-left text-[11px] transition-all hover:border-primary/40 hover:bg-primary/5 hover:shadow-sm">
                            <Icon className="h-3.5 w-3.5 shrink-0 text-primary" />
                            <span className="truncate">{t(`forms.fieldTypes.${type}`)}</span>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ))}
                <p className="text-[10px] text-muted-foreground">{t('forms.dropHint')}</p>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Canvas */}
        <Card className="min-h-[34rem]">
          {!selected ? (
            <EmptyState icon={<FileText className="h-5 w-5" />} title={t('forms.emptyTitle')} description={t('forms.emptyText')}
              action={can('form:write') ? <Button size="sm" onClick={() => setCreateOpen(true)}><Plus className="h-3.5 w-3.5" />{t('forms.newForm')}</Button> : undefined} />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h2 className="truncate text-sm font-semibold">{meta.name}</h2>
                    <Badge variant={meta.status === 'published' ? 'success' : 'muted'}>{meta.status}</Badge>
                    <span className="font-mono text-[10px] text-muted-foreground">v{selected.version}</span>
                  </div>
                  <p className="truncate text-[11px] text-muted-foreground">{t('forms.fieldCount', { count: fields.length })} · {selected.code}</p>
                </div>
                <Segmented value={mode} onChange={setMode} options={[
                  { value: 'design', label: t('forms.designMode'), icon: <PencilRuler className="h-3 w-3" /> },
                  { value: 'preview', label: t('forms.previewMode'), icon: <Eye className="h-3 w-3" /> },
                ]} />
              </div>

              <div className="scroll-thin max-h-[calc(100vh-19rem)] min-h-[26rem] overflow-y-auto bg-muted/20 p-4">
                {mode === 'design' ? (
                  <div className="mx-auto max-w-3xl rounded-xl border bg-card p-5 shadow-sm">
                    <div className="mb-4 border-b pb-3">
                      <h3 className="text-base font-semibold">{meta.name || t('forms.formName')}</h3>
                      {meta.description && <p className="mt-1 text-xs text-muted-foreground">{meta.description}</p>}
                    </div>
                    {!fields.length && (
                      <div className="rounded-lg border border-dashed py-12 text-center text-xs text-muted-foreground">{t('forms.dropHint')}</div>
                    )}
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
                              <span className="truncate text-xs font-medium">{f.label}{f.required && <span className="ml-0.5 text-destructive">*</span>}</span>
                              <div className="ml-auto flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                                <Button variant="ghost" size="icon-sm" onClick={(e) => { e.stopPropagation(); duplicateField(f) }}><Copy className="h-3 w-3" /></Button>
                                <Button variant="ghost" size="icon-sm" onClick={(e) => { e.stopPropagation(); removeField(f.id) }}><Trash2 className="h-3 w-3 text-destructive" /></Button>
                              </div>
                            </div>
                            <PreviewField field={f} value={undefined} onChange={() => {}} disabled />
                            <span className="mt-1.5 block font-mono text-[9px] text-muted-foreground">{f.key} · {f.type}</span>
                          </div>
                        )
                      })}
                    </div>
                    <p className="mt-4 text-center text-[10px] text-muted-foreground">{t('forms.dragHint')}</p>
                  </div>
                ) : (
                  <div className="mx-auto max-w-3xl rounded-xl border bg-card p-6 shadow-sm">
                    <h3 className="text-base font-semibold">{meta.name}</h3>
                    <p className="mb-5 mt-1 text-xs text-muted-foreground">{t('forms.fillPreview')}</p>
                    <div className="grid grid-cols-2 gap-4">
                      {fields.map((f) => (
                        <div key={f.id} className={cn(f.width === 100 && 'col-span-2', 'space-y-1.5')}>
                          <Label className="block">{f.label}{f.required && <span className="ml-0.5 text-destructive">*</span>}</Label>
                          <PreviewField field={f} value={preview[f.key]}
                            onChange={(v) => setPreview((p) => ({ ...p, [f.key]: v }))} />
                        </div>
                      ))}
                    </div>
                    <div className="mt-6 flex items-center gap-2 border-t pt-4">
                      <Button size="sm" onClick={submitPreview}><Send className="h-3.5 w-3.5" />{t('forms.submitPreview')}</Button>
                      <Button variant="ghost" size="sm" onClick={() => setPreview({})}>{t('common.reset')}</Button>
                      <span className="ml-auto text-[11px] text-muted-foreground">{t('forms.publishedOnly')}</span>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2 border-t px-4 py-3">
                <Button variant="outline" size="sm" onClick={() => setMetaOpen(true)}><Settings2 className="h-3.5 w-3.5" />{t('common.settings')}</Button>
                <Button variant="outline" size="sm" onClick={openSubs}><Layers className="h-3.5 w-3.5" />{t('forms.submissions')}</Button>
                <div className="ml-auto flex flex-wrap gap-2">
                  <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)} disabled={!can('form:write')}><Trash2 className="h-3.5 w-3.5 text-destructive" />{t('common.delete')}</Button>
                  <Button variant="outline" size="sm" loading={saving} onClick={() => save(false)} disabled={!can('form:write')}><Save className="h-3.5 w-3.5" />{t('forms.saveDraft')}</Button>
                  <Button size="sm" loading={saving} onClick={() => save(true)} disabled={!can('form:publish')}><CheckSquare className="h-3.5 w-3.5" />{t('forms.publish')}</Button>
                </div>
              </div>
            </>
          )}
        </Card>

        {/* Properties */}
        <Card className="h-fit">
          <CardContent className="p-4">
            <SectionTitle>{t('forms.properties')}</SectionTitle>
            {!activeField || mode !== 'design' ? (
              <p className="py-8 text-center text-xs text-muted-foreground">{t('forms.dropHint')}</p>
            ) : (
              <div className="space-y-3">
                <Field label={t('forms.fieldLabel')}>
                  <Input value={activeField.label} onChange={(e) => patchField(activeField.id, { label: e.target.value })} />
                </Field>
                <Field label={t('forms.fieldKey')}>
                  <Input className="font-mono text-xs" value={activeField.key} onChange={(e) => patchField(activeField.id, { key: e.target.value.replace(/[^a-zA-Z0-9_]/g, '') })} />
                </Field>
                <Field label={t('common.type')}>
                  <Select value={activeField.type} onValueChange={(v) => patchField(activeField.id, { type: v })}
                    options={fieldTypes.map((x) => ({ value: x, label: t(`forms.fieldTypes.${x}`) }))} />
                </Field>
                <Field label={t('forms.placeholder')}>
                  <Input value={activeField.placeholder || ''} onChange={(e) => patchField(activeField.id, { placeholder: e.target.value })} />
                </Field>
                {['select', 'multiselect', 'radio'].includes(activeField.type) && (
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
                <div className="flex items-center justify-between rounded-lg border px-3 py-2">
                  <span className="text-xs font-medium">{t('forms.requiredField')}</span>
                  <Switch checked={!!activeField.required} onCheckedChange={(v) => patchField(activeField.id, { required: v })} />
                </div>
                {activeField.type === 'number' && (
                  <div className="grid grid-cols-2 gap-2">
                    <Field label={t('forms.min')}><Input type="number" value={(activeField.validation as any)?.min ?? ''}
                      onChange={(e) => patchField(activeField.id, { validation: { ...(activeField.validation || {}), min: Number(e.target.value) } })} /></Field>
                    <Field label={t('forms.max')}><Input type="number" value={(activeField.validation as any)?.max ?? ''}
                      onChange={(e) => patchField(activeField.id, { validation: { ...(activeField.validation || {}), max: Number(e.target.value) } })} /></Field>
                  </div>
                )}
                <Field label={t('forms.defaultValue')}>
                  <Input value={String(activeField.defaultValue ?? '')} onChange={(e) => patchField(activeField.id, { defaultValue: e.target.value })} />
                </Field>
                <Button variant="outline" size="sm" className="w-full" onClick={() => removeField(activeField.id)}>
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />{t('common.remove')}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Dialogs */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen} title={t('forms.createTitle')} size="md"
        footer={<><Button variant="outline" onClick={() => setCreateOpen(false)}>{t('common.cancel')}</Button><Button onClick={create}>{t('common.create')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('forms.formCode')} hint="lowercase, underscores"><Input value={newForm.code} onChange={(e) => setNewForm({ ...newForm, code: e.target.value })} placeholder="my_form" /></Field>
          <Field label={t('forms.formName')}><Input value={newForm.name} onChange={(e) => setNewForm({ ...newForm, name: e.target.value })} /></Field>
          <Field label={t('common.description')}><Textarea value={newForm.description} onChange={(e) => setNewForm({ ...newForm, description: e.target.value })} /></Field>
        </div>
      </Dialog>

      <Dialog open={metaOpen} onOpenChange={setMetaOpen} title={t('forms.editTitle')} size="md"
        footer={<><Button variant="outline" onClick={() => setMetaOpen(false)}>{t('common.cancel')}</Button><Button onClick={() => { setMetaOpen(false); void save(false) }}>{t('common.save')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('forms.formName')}><Input value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} /></Field>
          <Field label={t('common.description')}><Textarea value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })} /></Field>
          <Field label={t('forms.statusLabel')}>
            <Select value={meta.status} onValueChange={(v) => setMeta({ ...meta, status: v })}
              options={(bootstrap?.form.statuses || ['draft', 'published', 'archived']).map((s) => ({ value: s, label: t(`common.${s}`) }))} />
          </Field>
        </div>
      </Dialog>

      <Dialog open={subsOpen} onOpenChange={setSubsOpen} title={t('forms.submissionsTitle', { name: selected?.name || '' })} size="xl">
        <Table><TableHeader><TableRow>
          <TableHead>ID</TableHead><TableHead>{t('audit.actor')}</TableHead><TableHead>{t('common.status')}</TableHead>
          <TableHead>{t('audit.details')}</TableHead><TableHead>{t('audit.time')}</TableHead>
        </TableRow></TableHeader><TableBody>
          {submissions.map((s) => <TableRow key={s.id}>
            <TableCell className="font-mono text-xs">#{s.id}</TableCell>
            <TableCell className="text-xs">{s.submitted_by}</TableCell>
            <TableCell><Badge variant={s.status === 'approved' ? 'success' : 'default'}>{s.status}</Badge></TableCell>
            <TableCell className="max-w-xs truncate font-mono text-[10px] text-muted-foreground">{JSON.stringify(s.data)}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{formatDate(s.created_at, locale)}</TableCell>
          </TableRow>)}
          {!submissions.length && <TableRow><TableCell colSpan={5} className="py-8 text-center text-xs text-muted-foreground">{t('common.noData')}</TableCell></TableRow>}
        </TableBody></Table>
      </Dialog>

      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} title={t('common.confirmDelete')}
        description={selected?.name} onConfirm={remove} />
    </div>
  )
}

export function PreviewField({ field, value, onChange, disabled = false }: {
  field: FormField; value: any; onChange: (v: any) => void; disabled?: boolean
}) {
  const { t } = useI18n()
  const common = 'h-8 w-full rounded-md border border-input bg-background/60 px-2.5 text-xs disabled:opacity-60'
  if (field.type === 'divider') return <div className="my-1 border-t border-dashed" />
  if (field.type === 'textarea') return <Textarea className="min-h-[62px] text-xs" disabled={disabled} placeholder={field.placeholder} value={value ?? ''} onChange={(e) => onChange(e.target.value)} />
  if (field.type === 'select' || field.type === 'multiselect' || field.type === 'radio') {
    return <Select className="h-8 text-xs" disabled={disabled} value={value ?? ''} onValueChange={onChange}
      placeholder={t('common.select')} options={(field.options || []).map((o) => ({ value: o, label: o }))} />
  }
  if (field.type === 'switch') {
    return <div className="flex h-8 items-center"><Switch checked={!!value} onCheckedChange={onChange} disabled={disabled} /></div>
  }
  if (field.type === 'table' || field.type === 'attachment') {
    return <div className="flex h-8 items-center gap-1.5 rounded-md border border-dashed px-2 text-[11px] text-muted-foreground">
      {field.type === 'table' ? <Table2 className="h-3 w-3" /> : <Paperclip className="h-3 w-3" />}{t(`forms.fieldTypes.${field.type}`)}
    </div>
  }
  const type = ['number'].includes(field.type) ? 'number' : ['date'].includes(field.type) ? 'date' : ['datetime'].includes(field.type) ? 'datetime-local' : 'text'
  return <input className={common} type={type} disabled={disabled} placeholder={field.placeholder || t(`forms.fieldTypes.${field.type}`)}
    value={value ?? ''} onChange={(e) => onChange(field.type === 'number' ? Number(e.target.value) : e.target.value)} />
}
