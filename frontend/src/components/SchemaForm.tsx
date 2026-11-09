import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Badge, Button, Field, Input, Select, Switch, Textarea } from '@/components/ui/basic'
import { useI18n } from '@/i18n'
import { post } from '@/lib/api'
import { useApp } from '@/store/AppContext'
import { cn } from '@/lib/utils'
import type { FormEvalResult, FormField } from '@/types'

/**
 * Schema-driven form renderer shared by the workflow start dialog, the public
 * start page and the AI agent's dynamic information-collection card.
 *
 * The field list is the backend's `FormField[]` (form_rules.render_schema), so
 * validators, conditional display / required rules, formulas, detail tables
 * and field permissions all come from one single source of truth. When a
 * `formId` is supplied the component calls `/forms/{id}/evaluate` on every
 * change and applies hidden / readonly / computed / errors from the rules
 * engine.
 */
export interface SchemaFormProps {
  fields: FormField[]
  value: Record<string, unknown>
  onChange: (v: Record<string, unknown>) => void
  formId?: number | null
  disabled?: boolean
  columns?: number
  errors?: Record<string, string>
  compact?: boolean
}

const TEXT_INPUT: Record<string, string> = {
  text: 'text', number: 'number', amount: 'number', mobile: 'tel', tel: 'tel',
  email: 'email', url: 'url', date: 'date', datetime: 'datetime-local', time: 'time',
  idcard: 'text', uscc: 'text', bankcard: 'text', user: 'text', department: 'text',
  region: 'text', password: 'password', color: 'color',
}
const LAYOUT_TYPES = new Set(['description', 'divider', 'grid', 'tabs', 'collapse'])

function optionsOf(field: FormField): { value: string; label: string }[] {
  return (field.options || []).map((o) => {
    if (o && typeof o === 'object') {
      const item = o as unknown as Record<string, unknown>
      return { value: String(item.value ?? item.label ?? ''), label: String(item.label ?? item.value ?? '') }
    }
    return { value: String(o), label: String(o) }
  })
}

function rowFormula(formula: string | undefined, row: Record<string, unknown>): string {
  if (!formula) return ''
  const m = formula.match(/^\s*([A-Za-z_]\w*)\s*([*+/-])\s*([A-Za-z_]\w*)\s*$/)
  if (!m) return ''
  const a = Number(row[m[1]]), b = Number(row[m[3]])
  if (!Number.isFinite(a) || !Number.isFinite(b)) return ''
  const v = m[2] === '*' ? a * b : m[2] === '+' ? a + b : m[2] === '-' ? a - b : (b ? a / b : 0)
  return String(Math.round(v * 100) / 100)
}

function DetailTable({ field, rows, onChange, disabled }: {
  field: FormField; rows: Record<string, unknown>[]
  onChange: (v: Record<string, unknown>[]) => void; disabled?: boolean
}) {
  const { t } = useI18n()
  const cols = field.columns || []
  const patch = (i: number, key: string, val: unknown) =>
    onChange(rows.map((r, idx) => idx === i ? { ...r, [key]: val } : r))
  return (
    <div className="space-y-1.5">
      <div className="scroll-thin overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[26rem] text-xs">
          <thead className="bg-muted/50 text-muted-foreground">
            <tr>
              {cols.map((c) => <th key={c.key} className="px-2 py-1.5 text-left font-medium">{c.label}</th>)}
              <th className="w-10 px-2 py-1.5" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-t">
                {cols.map((c) => {
                  const computed = c.formula ? rowFormula(c.formula, row) : ''
                  return <td key={c.key} className="px-2 py-1">
                    {c.formula ? (
                      <span className="font-mono text-[11px] text-primary">{computed || '—'}</span>
                    ) : c.options?.length ? (
                      <Select className="h-7 text-[11px]" value={String(row[c.key] ?? '')}
                        disabled={disabled}
                        onValueChange={(v) => patch(i, c.key, v)}
                        options={[{ value: '', label: '—' }, ...c.options.map((o) => ({ value: String(o), label: String(o) }))]} />
                    ) : (
                      <Input className="h-7 text-[11px]" type={c.type === 'number' ? 'number' : 'text'}
                        disabled={disabled} value={String(row[c.key] ?? '')}
                        onChange={(e) => patch(i, c.key,
                          c.type === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value)} />
                    )}
                  </td>
                })}
                <td className="px-1 py-1 text-right">
                  <Button variant="ghost" size="icon-sm" disabled={disabled}
                    onClick={() => onChange(rows.filter((_, idx) => idx !== i))}>
                    <Trash2 className="h-3 w-3 text-destructive" />
                  </Button>
                </td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={cols.length + 1}
              className="px-2 py-3 text-center text-[11px] text-muted-foreground">—</td></tr>}
          </tbody>
        </table>
      </div>
      <Button variant="outline" size="sm" disabled={disabled}
        onClick={() => onChange([...rows, Object.fromEntries(cols.map((c) => [c.key, '']))])}>
        <Plus className="h-3 w-3" />{t('formFill.addRow')}
      </Button>
      {!!field.summary?.length && <div className="flex flex-wrap gap-1.5">
        {field.summary.map((s) => <Badge key={s.key} variant="muted" className="text-[10px]">
          {s.label}: {String(rows.reduce((acc, r) => acc + (Number(r[s.column]) || 0), 0))}
        </Badge>)}
      </div>}
    </div>
  )
}

export function SchemaForm({ fields, value, onChange, formId, disabled, columns = 2,
                             errors: externalErrors, compact }: SchemaFormProps) {
  const { t } = useI18n()
  const { user } = useApp()
  const [evaluated, setEvaluated] = useState<FormEvalResult | null>(null)
  const timer = useRef<number | null>(null)
  const lastKey = useRef('')
  const initialized = useRef(false)

  // Prefill identity / date defaults once, so a start form is never empty.
  useEffect(() => {
    if (initialized.current || Object.keys(value).length) { initialized.current = true; return }
    initialized.current = true
    const defaults: Record<string, unknown> = {}
    for (const f of fields) {
      if (!f.key || LAYOUT_TYPES.has(f.type)) continue
      if (f.type === 'user') defaults[f.key] = user?.username || ''
      else if (f.type === 'department') defaults[f.key] = user?.dept || ''
      else if (f.type === 'date' && f.required) defaults[f.key] = new Date().toISOString().slice(0, 10)
      else if (f.type === 'switch') defaults[f.key] = !!f.defaultValue
      else if (f.defaultValue !== undefined) defaults[f.key] = f.defaultValue
    }
    if (Object.keys(defaults).length) onChange({ ...defaults, ...value })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Ask the rules engine for visibility / permissions / computed values.
  useEffect(() => {
    if (!formId) return
    const key = JSON.stringify(value)
    if (key === lastKey.current) return
    lastKey.current = key
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(async () => {
      try {
        const r = await post<FormEvalResult>(`/forms/${formId}/evaluate`,
          { data: value, check_unique: false })
        setEvaluated(r)
      } catch { /* keep the last good evaluation */ }
    }, 300)
    return () => { if (timer.current) window.clearTimeout(timer.current) }
  }, [value, formId])

  const hidden = useMemo(() => new Set(evaluated?.hidden || []), [evaluated])
  const computed = evaluated?.computed || {}
  const summaries = evaluated?.summaries || {}
  const fieldErrors = useMemo(() => {
    const out: Record<string, string> = { ...(externalErrors || {}) }
    for (const e of evaluated?.errors || []) if (e?.key) out[e.key] = e.message
    return out
  }, [evaluated, externalErrors])

  const setValue = (key: string, v: unknown) => onChange({ ...value, [key]: v })
  const visible = fields.filter((f) => f.key && !LAYOUT_TYPES.has(f.type)
    && !hidden.has(f.key) && f.permission !== 'hidden'
    && (evaluated?.permissions?.[f.key] || f.permission) !== 'hidden')

  if (!visible.length) {
    return <p className="py-6 text-center text-xs text-muted-foreground">{t('formFill.noFields')}</p>
  }

  return (
    <div className={cn('grid gap-x-4 gap-y-3', columns === 1 ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2')}>
      {visible.map((f) => {
        const key = f.key!
        const perm = evaluated?.permissions?.[key] || f.permission
        const ro = disabled || perm === 'readonly'
        const v = value[key]
        const err = fieldErrors[key]
        const width = f.width && f.width <= 50 ? '' : 'md:col-span-2'
        const label = <span className="flex items-center gap-1">
          {f.label || key}{f.required && <span className="text-destructive">*</span>}
          {f.formula && <Badge variant="muted" className="ml-1 text-[9px]">{t('formFill.auto')}</Badge>}
        </span>
        const common = { disabled: ro, className: compact ? 'h-8 text-xs' : '' }
        let control: ReactNode

        if (f.type === 'textarea') {
          control = <Textarea rows={compact ? 2 : 3} disabled={ro} value={String(v ?? '')}
            placeholder={f.placeholder}
            onChange={(e) => setValue(key, e.target.value)} />
        } else if (f.type === 'switch') {
          control = <Switch checked={!!v} disabled={ro} onCheckedChange={(x) => setValue(key, x)} />
        } else if (f.type === 'select' || f.type === 'radio' || f.type === 'cascader') {
          control = <Select {...common} value={String(v ?? '')} placeholder={t('common.select')}
            onValueChange={(x) => setValue(key, x)}
            options={[{ value: '', label: t('common.none') }, ...optionsOf(f)]} />
        } else if (f.type === 'multiselect' || f.type === 'checkbox') {
          const arr = Array.isArray(v) ? v as unknown[] : []
          control = <div className="flex flex-wrap gap-1.5">
            {optionsOf(f).map((o) => <label key={o.value}
              className="flex items-center gap-1 rounded-md border px-2 py-1 text-[11px]">
              <input type="checkbox" className="h-3 w-3 accent-[hsl(var(--primary))]" disabled={ro}
                checked={arr.includes(o.value)}
                onChange={(e) => setValue(key, e.target.checked ? [...arr, o.value]
                  : arr.filter((x) => x !== o.value))} />{o.label}</label>)}
          </div>
        } else if (f.type === 'table') {
          const rows = Array.isArray(v) ? v as Record<string, unknown>[] : []
          control = <DetailTable field={f} rows={rows} disabled={ro}
            onChange={(x) => setValue(key, x)} />
        } else if (f.type === 'formula' || f.type === 'serial' || f.formula) {
          control = <Input {...common} readOnly value={String(computed[key] ?? v ?? '')}
            placeholder={t('formFill.auto')} />
        } else if (f.type === 'rate' || f.type === 'slider') {
          control = <div className="flex items-center gap-2">
            <input type="range" min="0" max={f.type === 'rate' ? 5 : 100} step={f.type === 'rate' ? 1 : 1}
              className="w-full accent-[hsl(var(--primary))]" disabled={ro}
              value={Number(v ?? 0)} onChange={(e) => setValue(key, Number(e.target.value))} />
            <span className="w-8 text-right font-mono text-xs">{String(v ?? 0)}</span>
          </div>
        } else if (f.type === 'signature' || f.type === 'image' || f.type === 'attachment'
          || f.type === 'ocr' || f.type === 'file') {
          control = <Input {...common} value={String(v ?? '')} placeholder={f.placeholder || key}
            onChange={(e) => setValue(key, e.target.value)} />
        } else {
          const isNum = ['number', 'amount'].includes(f.type)
          control = <Input {...common} type={TEXT_INPUT[f.type] || 'text'} value={String(v ?? '')}
            placeholder={f.placeholder} onChange={(e) => setValue(key,
              isNum ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value)} />
        }

        return (
          <Field key={key} label={label} className={width}
            hint={err ? <span className="text-destructive">{err}</span> : (f.description as string) || undefined}>
            {control}
            {f.type === 'amount' && !!computed[`${key}_upper`] &&
              <p className="text-[10px] text-muted-foreground">
                {t('formFill.upper')}: {String(computed[`${key}_upper`])}</p>}
            {f.type === 'table' && Object.keys(summaries).length > 0 &&
              <p className="text-[10px] text-muted-foreground">
                {t('formFill.summary')}: {Object.entries(summaries).map(([k, x]) => `${k} ${x}`).join(' · ')}</p>}
          </Field>
        )
      })}
    </div>
  )
}

export default SchemaForm
