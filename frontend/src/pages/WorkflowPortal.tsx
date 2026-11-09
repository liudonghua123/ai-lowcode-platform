import { useEffect, useState } from 'react'
import {
  ArrowRight, CheckCircle2, ClipboardList, Copy, GitBranch, LayoutGrid,
  Link2, ListTodo, RefreshCw, Search, Send, ShieldCheck, Timer, XCircle,
} from 'lucide-react'
import {
  Badge, Button, Card, CardContent, EmptyState, Field, Input, Select, Textarea,
} from '@/components/ui/basic'
import { Dialog, Tabs, useToast } from '@/components/ui/overlay'
import { SectionTitle } from '@/components/PageHeader'
import { SchemaForm } from '@/components/SchemaForm'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { get, post } from '@/lib/api'
import { cn, formatDate } from '@/lib/utils'
import type {
  FlowTask, MyInstance, PortalStats, StartSchema, WorkflowCatalogItem, WorkflowInstance,
} from '@/types'

/**
 * Workflow portal — the redesigned workflow home page.
 *
 *  • startable catalog with one-click launch and copyable, auth-gated URLs
 *  • "my launched workflows" with status / keyword / workflow / date filters
 *  • pending approvals with inline approve / reject
 *
 * Business data always comes from the data-scoped REST endpoints, so a normal
 * user only ever sees their own instances while an auditor sees all of them.
 */
export default function WorkflowPortal({ onDesign }: { onDesign: (code: string) => void }) {
  const { t, locale } = useI18n()
  const { can, user } = useApp()
  const { toast } = useToast()
  const [tab, setTab] = useState('start')
  const [catalog, setCatalog] = useState<WorkflowCatalogItem[]>([])
  const [stats, setStats] = useState<PortalStats | null>(null)
  const [instances, setInstances] = useState<MyInstance[]>([])
  const [tasks, setTasks] = useState<FlowTask[]>([])
  const [loading, setLoading] = useState(false)

  const [status, setStatus] = useState('all')
  const [q, setQ] = useState('')
  const [workflowId, setWorkflowId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const [startTarget, setStartTarget] = useState<WorkflowCatalogItem | null>(null)
  const [startSchema, setStartSchema] = useState<StartSchema | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [detail, setDetail] = useState<WorkflowInstance | null>(null)
  const [actTask, setActTask] = useState<{ task: FlowTask; action: string } | null>(null)
  const [comment, setComment] = useState('')

  const loadCatalog = async () => {
    try { const r = await get<{ workflows: WorkflowCatalogItem[] }>('/workflows/catalog')
      setCatalog(r.workflows || []) } catch { setCatalog([]) }
  }
  const loadStats = async () => {
    try { setStats(await get<PortalStats>('/workflows/mine/stats')) } catch { /* optional */ }
  }
  const loadTasks = async () => {
    try { const r = await get<{ tasks: FlowTask[] }>('/workflows/tasks?status=pending')
      setTasks(r.tasks || []) } catch { setTasks([]) }
  }
  const loadInstances = async () => {
    setLoading(true)
    // Only send non-empty filters: an empty `workflow_id=` would be rejected
    // by FastAPI's int|None query validation with a 422.
    const params = new URLSearchParams({ limit: '100' })
    if (status) params.set('status', status)
    if (q) params.set('q', q)
    if (workflowId) params.set('workflow_id', workflowId)
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    try {
      const r = await get<{ instances: MyInstance[] }>(`/workflows/mine/instances?${params}`)
      setInstances(r.instances || [])
    } catch { setInstances([]) }
    finally { setLoading(false) }
  }
  useEffect(() => { void loadCatalog(); void loadStats(); void loadTasks() }, [])
  useEffect(() => {
    const timer = window.setTimeout(() => void loadInstances(), 250)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, q, workflowId, dateFrom, dateTo])

  const shareUrl = (wf: WorkflowCatalogItem) =>
    `${window.location.origin}${window.location.pathname}${wf.start_path}`
  const copyLink = async (wf: WorkflowCatalogItem) => {
    const url = shareUrl(wf)
    try { await navigator.clipboard.writeText(url); toast(t('portal.linkCopied'), 'success', url) }
    catch { toast(url, 'info') }
  }
  const openStart = async (wf: WorkflowCatalogItem) => {
    setStartTarget(wf); setValues({}); setFormErrors({}); setStartSchema(null)
    try {
      setStartSchema(await get<StartSchema>(`/workflows/${wf.id}/start-schema`))
    } catch (e: any) { toast(e.message, 'error') }
  }
  const launch = async () => {
    if (!startTarget) return
    setSubmitting(true)
    try {
      await post(`/workflows/${startTarget.id}/start`, { form_data: values, create_submission: true })
      setStartTarget(null)
      toast(t('workflows.startSuccess'), 'success')
      void loadStats(); void loadTasks(); void loadInstances()
    } catch (e: any) {
      const msg = String(e.message || '')
      const errs: Record<string, string> = {}
      for (const part of msg.split('; ')) {
        const i = part.indexOf(':')
        if (i > 0) errs[part.slice(0, i).trim()] = part.slice(i + 1).trim()
      }
      setFormErrors(errs); toast(msg, 'error')
    } finally { setSubmitting(false) }
  }
  const openDetail = async (id: number) => {
    try { setDetail(await get<WorkflowInstance>(`/workflows/instances/${id}`)) }
    catch (e: any) { toast(e.message, 'error') }
  }
  const doAct = async () => {
    if (!actTask) return
    try {
      await post(`/workflows/instances/${actTask.task.instance_id}/tasks/${actTask.task.id}/act`,
        { action: actTask.action, comment: comment || undefined })
      setActTask(null); setComment(''); toast(t('common.saved'), 'success')
      void loadTasks(); void loadStats(); void loadInstances()
    } catch (e: any) { toast(e.message, 'error') }
  }

  const cards = [
    { label: t('portal.statsStartable'), value: stats?.startable_workflows ?? 0,
      icon: <LayoutGrid className="h-4 w-4" />, tone: 'text-primary' },
    { label: t('portal.statsMine'), value: stats?.total ?? 0,
      icon: <ClipboardList className="h-4 w-4" />, tone: 'text-cyan-600' },
    { label: t('portal.statsRunning'), value: stats?.running ?? 0,
      icon: <Timer className="h-4 w-4" />, tone: 'text-amber-600' },
    { label: t('portal.statsPending'), value: stats?.pending_approvals ?? 0,
      icon: <ListTodo className="h-4 w-4" />, tone: 'text-violet-600' },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Tabs value={tab} onValueChange={setTab} items={[
          { value: 'start', label: t('portal.tabStart'), icon: <LayoutGrid className="h-3 w-3" />,
            count: catalog.filter((w) => w.startable).length },
          { value: 'mine', label: t('portal.tabMine'), icon: <ClipboardList className="h-3 w-3" />,
            count: instances.length },
          { value: 'approvals', label: t('portal.tabApprovals'), icon: <ListTodo className="h-3 w-3" />,
            count: tasks.length },
        ]} />
        <Badge variant="outline" className="ml-auto gap-1 text-[10px]">
          <ShieldCheck className="h-3 w-3" />{t('portal.scope')}: {user?.data_scope || 'self'}
        </Badge>
        <Button variant="outline" size="sm" onClick={() => { void loadCatalog(); void loadStats(); void loadTasks(); void loadInstances() }}>
          <RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((c) => <Card key={c.label}><CardContent className="flex items-center gap-3 p-4">
          <span className={cn('flex h-9 w-9 items-center justify-center rounded-lg bg-muted', c.tone)}>{c.icon}</span>
          <div><p className="text-[11px] text-muted-foreground">{c.label}</p>
            <p className="text-xl font-semibold tabular-nums">{c.value}</p></div>
        </CardContent></Card>)}
      </div>

      {tab === 'start' && (
        catalog.length ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {catalog.map((wf) => (
            <Card key={wf.id} className="group flex flex-col transition-all hover:border-primary/40 hover:shadow-soft">
              <CardContent className="flex flex-1 flex-col p-4">
                <div className="flex items-start gap-2.5">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <GitBranch className="h-4 w-4" /></span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">{wf.name}</p>
                    <p className="font-mono text-[10px] text-muted-foreground">{wf.code}</p>
                  </div>
                  <Badge variant={wf.startable ? 'success' : 'muted'} className="text-[9px]">{wf.status}</Badge>
                </div>
                <p className="mt-2.5 line-clamp-2 min-h-[2.5rem] text-[11px] leading-relaxed text-muted-foreground">
                  {wf.description || '—'}</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {wf.form_name && <Badge variant="secondary" className="text-[9px]">{wf.form_name}</Badge>}
                  <Badge variant="muted" className="text-[9px]">{t('portal.formFields')}: {wf.field_count}</Badge>
                  <Badge variant="muted" className="text-[9px]">{t('portal.nodes')}: {wf.node_count}</Badge>
                  <Badge variant="outline" className="gap-1 text-[9px]"><Link2 className="h-2.5 w-2.5" />{t('portal.authRequired')}</Badge>
                </div>
                <div className="mt-auto flex flex-wrap gap-1.5 pt-3">
                  <Button size="sm" disabled={!wf.startable || !can('workflow:run')}
                    onClick={() => void openStart(wf)}><Send className="h-3.5 w-3.5" />{t('portal.launch')}</Button>
                  <Button variant="outline" size="sm" onClick={() => void copyLink(wf)}>
                    <Copy className="h-3.5 w-3.5" />{t('portal.copyLink')}</Button>
                  {can('workflow:write') && <Button variant="ghost" size="sm" className="ml-auto"
                    onClick={() => onDesign(wf.code)}>{t('portal.openDesigner')}<ArrowRight className="h-3 w-3" /></Button>}
                </div>
              </CardContent>
            </Card>
          ))}
        </div> : <Card><EmptyState icon={<GitBranch className="h-5 w-5" />}
          title={t('portal.noStartable')} description={t('portal.noStartableHint')} /></Card>
      )}

      {tab === 'mine' && (
        <Card><CardContent className="p-4 space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t('common.status')} className="w-32">
              <Select value={status} onValueChange={setStatus} options={[
                { value: 'all', label: t('common.all') },
                { value: 'running', label: t('common.running') },
                { value: 'approved', label: t('workflows.approvedTasks') },
                { value: 'rejected', label: t('workflows.reject') },
                { value: 'canceled', label: 'canceled' },
                { value: 'completed', label: t('common.completed') },
              ]} /></Field>
            <Field label={t('portal.filterWorkflow')} className="w-44">
              <Select value={workflowId} onValueChange={setWorkflowId} options={[
                { value: '', label: t('common.all') },
                ...catalog.map((w) => ({ value: String(w.id), label: w.name })),
              ]} /></Field>
            <Field label={t('portal.dateFrom')} className="w-36">
              <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /></Field>
            <Field label={t('portal.dateTo')} className="w-36">
              <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></Field>
            <Field label={t('common.search')} className="min-w-[12rem] flex-1">
              <div className="relative"><Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input className="pl-8" value={q} placeholder={t('portal.filterKeyword')}
                  onChange={(e) => setQ(e.target.value)} /></div>
            </Field>
            <Button variant="outline" size="sm" onClick={() => { setStatus('all'); setQ(''); setWorkflowId(''); setDateFrom(''); setDateTo('') }}>
              {t('common.reset')}</Button>
          </div>
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <span>{t('common.total')}: {instances.length}</span>{loading && <span>{t('common.loading')}</span>}
          </div>
          <div className="scroll-thin max-h-[30rem] space-y-1.5 overflow-y-auto">
            {instances.map((ins) => (
              <button key={ins.id} onClick={() => void openDetail(ins.id)}
                className="flex w-full flex-wrap items-center gap-2 rounded-lg border px-3 py-2.5 text-left transition-all hover:border-primary/40 hover:bg-primary/5">
                <span className="font-mono text-xs">#{ins.id}</span>
                <span className="min-w-[10rem] flex-1 truncate text-xs font-medium">
                  {ins.workflow_name || ins.workflow_code || `workflow #${ins.workflow_id}`}</span>
                <Badge variant={ins.status === 'approved' || ins.status === 'completed' ? 'success'
                  : ins.status === 'rejected' || ins.status === 'canceled' ? 'destructive' : 'warning'}
                  className="text-[9px]">{ins.status}</Badge>
                {!!ins.pending_count && <Badge variant="muted" className="text-[9px]">
                  {ins.pending_count} {t('workflows.pendingTasks').toLowerCase()}</Badge>}
                <span className="text-[10px] text-muted-foreground">{formatDate(ins.started_at, locale)}</span>
                <span className="text-[10px] text-muted-foreground">{ins.started_by}</span>
                <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
              </button>
            ))}
            {!instances.length && <p className="py-10 text-center text-xs text-muted-foreground">{t('common.noData')}</p>}
          </div>
        </CardContent></Card>
      )}

      {tab === 'approvals' && (
        <Card><CardContent className="p-4">
          <SectionTitle>{t('portal.tabApprovals')} · {tasks.length}</SectionTitle>
          <div className="space-y-2">
            {tasks.map((task) => (
              <div key={task.id} className="flex flex-wrap items-center gap-2 rounded-lg border p-3">
                <CheckCircle2 className="h-4 w-4 text-primary" />
                <span className="font-mono text-xs">#{task.id}</span>
                <span className="min-w-[8rem] flex-1 truncate text-xs font-medium">{task.node_name}</span>
                <Badge variant="warning" className="text-[9px]">{task.status}</Badge>
                <span className="text-[10px] text-muted-foreground">
                  {t('workflows.instance')} #{task.instance_id} · {task.initiator || task.assignee}</span>
                <div className="ml-auto flex gap-1.5">
                  <Button size="sm" variant="outline" onClick={() => { setActTask({ task, action: 'approve' }); setComment('') }}>
                    <CheckCircle2 className="h-3 w-3" />{t('workflows.approve')}</Button>
                  <Button size="sm" variant="outline" onClick={() => { setActTask({ task, action: 'reject' }); setComment('') }}>
                    <XCircle className="h-3 w-3" />{t('workflows.reject')}</Button>
                </div>
              </div>
            ))}
            {!tasks.length && <p className="py-10 text-center text-xs text-muted-foreground">{t('workflows.noTasks')}</p>}
          </div>
        </CardContent></Card>
      )}

      {/* Launch dialog — dynamic form, never raw JSON */}
      <Dialog open={!!startTarget} onOpenChange={(v) => !v && setStartTarget(null)}
        title={startTarget ? t('workflows.startTitle', { name: startTarget.name }) : ''} size="lg"
        footer={<><Button variant="outline" onClick={() => setStartTarget(null)}>{t('common.cancel')}</Button>
          <Button loading={submitting} onClick={launch}><Send className="h-3.5 w-3.5" />{t('portal.launch')}</Button></>}>
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">{t('workflows.startHint')}</p>
          {startSchema?.form && <Badge variant="muted">{startSchema.form.name} · v{startSchema.form.version}</Badge>}
          <SchemaForm fields={startSchema?.fields || []} value={values} onChange={setValues}
            formId={startSchema?.form?.id} errors={formErrors} />
          {!startSchema?.fields?.length && <p className="py-4 text-center text-xs text-muted-foreground">
            {startSchema?.hint || t('common.noData')}</p>}
        </div>
      </Dialog>

      {/* Instance detail */}
      <Dialog open={!!detail} onOpenChange={(v) => !v && setDetail(null)}
        title={t('portal.instanceDetail', { id: detail?.id || 0 })} size="lg"
        footer={<Button variant="outline" size="sm" onClick={() => setDetail(null)}>{t('common.close')}</Button>}>
        {detail && <div className="space-y-3 text-xs">
          <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/20 p-2.5">
            <Badge variant={detail.status === 'approved' ? 'success'
              : detail.status === 'rejected' || detail.status === 'canceled' ? 'destructive' : 'warning'}>
              {detail.status}</Badge>
            <span>{detail.form_code || '—'}</span>
            <span className="ml-auto text-[10px] text-muted-foreground">
              v{detail.workflow_version} · {detail.started_by} · {formatDate(detail.started_at, locale)}</span>
          </div>
          {!!detail.current_nodes?.length && <p>{t('workflows.currentNodes')}:
            <span className="font-mono"> {detail.current_nodes.join(', ')}</span></p>}
          <div className="grid gap-3 md:grid-cols-2">
            <div><p className="mb-1.5 font-semibold">{t('workflows.tasks')} ({detail.tasks?.length || 0})</p>
              <div className="scroll-thin max-h-48 space-y-1 overflow-y-auto">
                {(detail.tasks || []).map((x) => <div key={x.id} className="flex items-center gap-2 rounded border px-2 py-1.5 text-[10px]">
                  <span className={cn('h-1.5 w-1.5 rounded-full', x.status === 'pending' ? 'bg-amber-500'
                    : x.status === 'approved' ? 'bg-emerald-500' : 'bg-muted-foreground')} />
                  <span className="min-w-0 flex-1 truncate">{x.node_name}</span>
                  <span className="font-mono">{x.assignee}</span><Badge variant="muted" className="text-[9px]">{x.status}</Badge>
                </div>)}
              </div></div>
            <div><p className="mb-1.5 font-semibold">{t('workflows.timeline')}</p>
              <div className="scroll-thin max-h-48 space-y-1 overflow-y-auto">
                {(detail.logs || []).slice().reverse().map((l: any, i: number) =>
                  <div key={i} className="rounded border px-2 py-1.5 text-[10px]">
                    <span className="font-mono text-primary">{String(l.event || l.node)}</span>
                    {l.actor && <span className="ml-1 text-muted-foreground">· {l.actor}</span>}
                    {l.comment && <span className="ml-1 text-muted-foreground">· {l.comment}</span>}
                  </div>)}
              </div></div>
          </div>
          <details className="rounded-lg border p-2"><summary className="cursor-pointer font-medium">
            {t('workflows.formData')}</summary>
            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-muted-foreground">
              {JSON.stringify(detail.form_data || {}, null, 2)}</pre></details>
        </div>}
      </Dialog>

      {/* Approve / reject */}
      <Dialog open={!!actTask} onOpenChange={(v) => !v && setActTask(null)}
        title={actTask ? `${t('workflows.approve')} / ${t('workflows.reject')} · #${actTask.task.id}` : ''} size="sm"
        footer={<><Button variant="outline" onClick={() => setActTask(null)}>{t('common.cancel')}</Button>
          <Button onClick={doAct}>{t('common.confirm')}</Button></>}>
        <div className="space-y-3">
          <p className="text-xs">{actTask?.task.node_name} · {t('workflows.instance')} #{actTask?.task.instance_id}</p>
          <Field label={t('workflows.comment')}><Textarea rows={3} value={comment}
            onChange={(e) => setComment(e.target.value)} /></Field>
        </div>
      </Dialog>
    </div>
  )
}
