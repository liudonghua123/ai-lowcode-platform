import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ArrowRightLeft, Bell, BookOpen, Bot, CheckCircle2, CircleDot, Clock, FileText, GitBranch, Globe2, History, LayoutGrid, Layers, Link2, ListTodo, Minus, Network, Play, Plus, RefreshCw, Save, Settings2, ShieldCheck, Sparkles, Square, Timer, Trash2, Undo2, UserCheck, UserPlus, UsersRound, X, ZoomIn, ZoomOut, Send, Zap, Equal, Code2, Database, Search, Tags, Package, Webhook, BellRing, FilePenLine,
} from 'lucide-react'
import { PageHeader, SectionTitle } from '@/components/PageHeader'
import {
  Badge, Button, Card, CardContent, EmptyState, Field, Input, Label, Segmented,
  Select, Switch, Textarea,
} from '@/components/ui/basic'
import { ConfirmDialog, Dialog, Tabs, useToast } from '@/components/ui/overlay'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { del, get, post, put } from '@/lib/api'
import { cn, formatDate, safeParse, uid } from '@/lib/utils'
import { SchemaForm } from '@/components/SchemaForm'
import WorkflowPortal from '@/pages/WorkflowPortal'
import type { ConfigField,
  FlowMeta, FlowTask, FormDef, StartSchema, WfEdge, WfGraph, WfNode,
  WorkflowDef, WorkflowInstance, WorkflowVersion,
} from '@/types'

const NODE_ICONS: Record<string, typeof Play> = {
  trigger: Zap, assign: Equal, script: Code2, data_write: Database,
  db_query: Search, ai_classify: Tags, skill: Package, webhook: Webhook,
  message: BellRing, human_input: FilePenLine,

  start: Play, end: Square, form: FileText, condition: GitBranch, approval: ShieldCheck,
  ai: Sparkles, knowledge: BookOpen, http: Globe2, notification: Bell,
  cc: UsersRound, parallel: Network, join: Layers, delay: Clock, subflow: GitBranch,
}
const FALLBACK_TYPES = [
  { type: 'start', name: 'Start', color: '#6366f1', category: 'control', config: [] },
  { type: 'end', name: 'End', color: '#64748b', category: 'control', config: [] },
  { type: 'form', name: 'Form', color: '#0ea5e9', category: 'task', config: ['form_code', 'assignee'] },
  { type: 'condition', name: 'Condition', color: '#f59e0b', category: 'logic', config: ['field', 'operator', 'value'] },
  { type: 'approval', name: 'Approval', color: '#8b5cf6', category: 'task', config: ['approver_role', 'mode'] },
  { type: 'ai', name: 'AI', color: '#ec4899', category: 'ai', config: ['prompt', 'model'] },
  { type: 'knowledge', name: 'Knowledge', color: '#14b8a6', category: 'ai', config: ['query'] },
  { type: 'http', name: 'HTTP', color: '#22c55e', category: 'integration', config: ['method', 'url'] },
  { type: 'notification', name: 'Notification', color: '#f97316', category: 'integration', config: ['channel', 'template'] },
  { type: 'cc', name: 'CC', color: '#38bdf8', category: 'task', config: ['assignees'] },
  { type: 'parallel', name: 'Parallel', color: '#a855f7', category: 'logic', config: [] },
  { type: 'join', name: 'Join', color: '#7c3aed', category: 'logic', config: ['join_mode'] },
  { type: 'delay', name: 'Delay', color: '#f97316', category: 'logic', config: ['delay_hours'] },
  { type: 'subflow', name: 'Subflow', color: '#0d9488', category: 'logic', config: ['workflow_code'] },
]
const NODE_W = 176, NODE_H = 64

export default function Workflows() {
  const { t, locale } = useI18n()
  const { can, bootstrap } = useApp()
  const { toast } = useToast()
  const canvasRef = useRef<HTMLDivElement>(null)
  const [searchParams] = useSearchParams()

  const [view, setView] = useState<'portal' | 'designer'>(
    searchParams.get('view') === 'designer' || !!searchParams.get('workflow') ? 'designer' : 'portal')
  const [workflows, setWorkflows] = useState<WorkflowDef[]>([])
  const [selected, setSelected] = useState<WorkflowDef | null>(null)
  const [nodes, setNodes] = useState<WfNode[]>([])
  const [edges, setEdges] = useState<WfEdge[]>([])
  const [activeNode, setActiveNode] = useState<string | null>(null)
  const [activeEdge, setActiveEdge] = useState<string | null>(null)
  const [connectMode, setConnectMode] = useState(false)
  const [connectFrom, setConnectFrom] = useState<string | null>(null)
  const [drag, setDrag] = useState<{ id: string; sx: number; sy: number; ox: number; oy: number } | null>(null)
  const [zoom, setZoom] = useState(1)
  const [meta, setMeta] = useState({ name: '', description: '', status: 'draft', form_code: '' })
  const [rightTab, setRightTab] = useState('properties')
  const [saving, setSaving] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [metaOpen, setMetaOpen] = useState(false)
  const [runOpen, setRunOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [contextText, setContextText] = useState('{\n  "days": 2,\n  "leave_type": "Annual"\n}')
  const [runResult, setRunResult] = useState<any>(null)
  const [instances, setInstances] = useState<WorkflowInstance[]>([])
  const [newWf, setNewWf] = useState({ code: '', name: '', description: '', form_code: '' })
  const [forms, setForms] = useState<FormDef[]>([])
  const [startSchema, setStartSchema] = useState<StartSchema | null>(null)
  const [startValues, setStartValues] = useState<Record<string, unknown>>({})
  const [startErrors, setStartErrors] = useState<Record<string, string>>({})
  const [flowMeta, setFlowMeta] = useState<FlowMeta | null>(null)
  const [tasks, setTasks] = useState<FlowTask[]>([])
  const [taskStatus, setTaskStatus] = useState('pending')
  const [instanceDetail, setInstanceDetail] = useState<WorkflowInstance | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [startOpen, setStartOpen] = useState(false)
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [wfVersions, setWfVersions] = useState<WorkflowVersion[]>([])
  const [actDialog, setActDialog] = useState<{ task: FlowTask; action: string } | null>(null)
  const [actForm, setActForm] = useState({ comment: '', assignee: '', return_to: 'initiator' })

  const nodeTypes = bootstrap?.workflow.node_types || FALLBACK_TYPES
  const operators = bootstrap?.workflow.operators || ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'in']
  const active = nodes.find((n) => n.id === activeNode) || null
  const activeE = edges.find((e) => e.id === activeEdge) || null
  const typeOf = (type: string) => nodeTypes.find((n) => n.type === type) || FALLBACK_TYPES.find((n) => n.type === type)!

  const load = async () => {
    try { const r = await get<{ workflows: WorkflowDef[] }>('/workflows'); setWorkflows(r.workflows || []); return r.workflows || [] }
    catch { return [] }
  }
  const loadInstances = async (id: number) => {
    try { const r = await get<{ instances: WorkflowInstance[] }>(`/workflows/${id}/instances`); setInstances(r.instances || []) } catch { setInstances([]) }
  }
  const loadMeta = async () => {
    try { setFlowMeta(await get<FlowMeta>(`/workflows/meta?lang=${locale}`)) } catch { /* optional */ }
  }
  const loadTasks = async (status = taskStatus) => {
    try {
      const r = await get<{ tasks: FlowTask[] }>(`/workflows/tasks?status=${status}`)
      setTasks(r.tasks || [])
    } catch { setTasks([]) }
  }
  const loadForms = async () => {
    try { const r = await get<{ forms: FormDef[] }>('/forms'); setForms(r.forms || []) }
    catch { setForms([]) }
  }
  useEffect(() => { void load(); void loadMeta(); void loadTasks(); void loadForms() }, [])
  useEffect(() => { void loadMeta() }, [locale])

  const openStart = async () => {
    if (!selected) return
    setStartValues({}); setStartErrors({}); setStartSchema(null)
    try {
      setStartSchema(await get<StartSchema>(`/workflows/${selected.id}/start-schema`))
    } catch (e: any) { toast(e.message, 'error') }
    setStartOpen(true)
  }
  const startInstance = async () => {
    if (!selected) return
    try {
      await post<WorkflowInstance>(`/workflows/${selected.id}/start`,
        { form_data: startValues, create_submission: true })
      setStartOpen(false); await loadInstances(selected.id); await loadTasks()
      setRightTab('tasks'); toast(t('workflows.startSuccess'), 'success')
    } catch (e: any) {
      const msg = String(e.message || '')
      const errs: Record<string, string> = {}
      for (const part of msg.split('; ')) {
        const i = part.indexOf(':')
        if (i > 0) errs[part.slice(0, i).trim()] = part.slice(i + 1).trim()
      }
      setStartErrors(errs)
      toast(msg, 'error')
    }
  }
  const openInstance = async (id: number) => {
    try {
      const r = await get<WorkflowInstance>(`/workflows/instances/${id}`)
      setInstanceDetail(r); setDetailOpen(true); await loadTasks()
    } catch (e: any) { toast(e.message, 'error') }
  }
  const doAct = async () => {
    if (!actDialog) return
    try {
      await post(`/workflows/instances/${actDialog.task.instance_id}/tasks/${actDialog.task.id}/act`, {
        action: actDialog.action, comment: actForm.comment || undefined,
        assignee: actForm.assignee || undefined, return_to: actForm.return_to || undefined,
      })
      const iid = actDialog.task.instance_id
      setActDialog(null); setActForm({ comment: '', assignee: '', return_to: 'initiator' })
      await loadTasks()
      if (instanceDetail?.id === iid) await openInstance(iid)
      if (selected) await loadInstances(selected.id)
      toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const withdrawInstance = async () => {
    if (!instanceDetail) return
    try {
      await post(`/workflows/instances/${instanceDetail.id}/withdraw`, {})
      await openInstance(instanceDetail.id); await loadTasks()
      toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const openVersions = async () => {
    if (!selected) return
    try {
      const r = await get<{ versions: WorkflowVersion[] }>(`/workflows/${selected.id}/versions`)
      setWfVersions(r.versions || []); setVersionsOpen(true)
    } catch (e: any) { toast(e.message, 'error') }
  }
  const restoreVersion = async (v: number) => {
    if (!selected) return
    try {
      const r = await post<WorkflowDef>(`/workflows/${selected.id}/versions`, { version: v })
      setSelected(r); setNodes(r.graph?.nodes || []); setEdges(r.graph?.edges || [])
      await load(); await openVersions(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }

  const select = (wf: WorkflowDef) => {
    setSelected(wf); setNodes(wf.graph?.nodes || []); setEdges(wf.graph?.edges || [])
    setActiveNode(wf.graph?.nodes?.[0]?.id || null); setActiveEdge(null)
    setMeta({ name: wf.name, description: wf.description || '', status: wf.status,
              form_code: wf.form_code || '' })
    setRunResult(null); void loadInstances(wf.id)
  }

  // Deep link: /#/workflows?workflow=leave_approval opens a specific canvas.
  useEffect(() => {
    const code = searchParams.get('workflow')
    if (!code || !workflows.length) return
    const target = workflows.find((w) => w.code === code)
    if (target) { setView('designer'); if (selected?.id !== target.id) select(target) }
  }, [workflows, searchParams, selected?.id])

  const addNode = (type: string) => {
    if (!selected) { toast(t('workflows.emptyTitle'), 'info'); return }
    const n: WfNode = { id: uid('n'), type, name: `${t(`workflows.nodeName`)} · ${type}`, x: 80 + (nodes.length % 4) * 210,
      y: 80 + Math.floor(nodes.length / 4) * 110, config: defaultConfig(type) }
    setNodes((p) => [...p, n]); setActiveNode(n.id); setActiveEdge(null)
  }
  const patchNode = (id: string, patch: Partial<WfNode>) => setNodes((p) => p.map((n) => n.id === id ? { ...n, ...patch } : n))
  const patchConfig = (key: string, value: any) => active && patchNode(active.id, { config: { ...active.config, [key]: value } })
  const removeNode = (id: string) => {
    setNodes((p) => p.filter((n) => n.id !== id)); setEdges((p) => p.filter((e) => e.source !== id && e.target !== id))
    setActiveNode(null)
  }
  const handleNodeClick = (id: string) => {
    if (!connectMode) { setActiveNode(id); setActiveEdge(null); return }
    if (!connectFrom) { setConnectFrom(id); return }
    if (connectFrom === id) { setConnectFrom(null); return }
    if (edges.some((e) => e.source === connectFrom && e.target === id)) { setConnectFrom(null); return }
    const source = nodes.find((n) => n.id === connectFrom)
    const condition = source?.type === 'condition' ? (edges.filter((e) => e.source === connectFrom).length === 0 ? 'true' : 'false') : undefined
    setEdges((p) => [...p, { id: uid('e'), source: connectFrom!, target: id,
      label: condition === 'true' ? t('workflows.branchTrue') : condition === 'false' ? t('workflows.branchFalse') : undefined, condition }])
    setConnectFrom(null); setConnectMode(false)
  }
  const autoLayout = () => {
    if (!nodes.length) return
    const depth: Record<string, number> = {}
    const starts = nodes.filter((n) => n.type === 'start'); const root = starts[0]?.id || nodes[0].id
    depth[root] = 0
    for (let i = 0; i < nodes.length; i++) {
      for (const e of edges) if (depth[e.source] !== undefined && depth[e.target] === undefined) depth[e.target] = depth[e.source] + 1
    }
    const groups: Record<number, WfNode[]> = {}
    nodes.forEach((n) => { const d = depth[n.id] ?? 1; (groups[d] ||= []).push(n) })
    setNodes((p) => p.map((n) => {
      const d = depth[n.id] ?? 1; const idx = (groups[d] || []).findIndex((g) => g.id === n.id)
      return { ...n, x: 60 + d * 240, y: 70 + idx * 130 }
    }))
    toast(t('common.saved'), 'success')
  }
  const save = async (publish = false) => {
    if (!selected) return
    setSaving(true)
    try {
      const r = await put<WorkflowDef>(`/workflows/${selected.id}`, {
        name: meta.name, description: meta.description, status: publish ? 'published' : meta.status,
        form_code: meta.form_code || undefined, graph: { nodes, edges },
      })
      setSelected(r); await load(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
    finally { setSaving(false) }
  }
  const create = async () => {
    try {
      const graph: WfGraph = { nodes: [
        { id: 'n1', type: 'start', name: 'Start', x: 60, y: 180, config: {} },
        { id: 'n2', type: 'end', name: 'End', x: 420, y: 180, config: {} }],
        edges: [{ id: 'e1', source: 'n1', target: 'n2' }] }
      const wf = await post<WorkflowDef>('/workflows',
        { ...newWf, form_code: newWf.form_code || undefined, status: 'draft', graph })
      setCreateOpen(false)
      setNewWf({ code: '', name: '', description: '', form_code: '' }); await load(); select(wf)
      toast(t('common.createdOk'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const remove = async () => {
    if (!selected) return
    try { await del(`/workflows/${selected.id}`); setSelected(null); setNodes([]); setEdges([]); await load(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmDelete(false) }
  }
  const validate = async () => {
    if (!selected) return
    try { const r: any = await post(`/workflows/${selected.id}/validate`, {})
      toast(r.valid ? t('workflows.validateOk') : `${t('workflows.validateFail')}: ${r.errors.join('; ')}`, r.valid ? 'success' : 'error') }
    catch (e: any) { toast(e.message, 'error') }
  }
  const run = async () => {
    if (!selected) return
    try {
      const r: any = await post(`/workflows/${selected.id}/run`, { context: safeParse(contextText, {}) })
      setRunResult(r); void loadInstances(selected.id)
      toast(t('workflows.runSuccess', { status: r.status }), r.status === 'completed' ? 'success' : 'error')
    } catch (e: any) { toast(e.message, 'error') }
  }

  const onPointerDown = (e: React.PointerEvent, node: WfNode) => {
    if (connectMode) return
    setActiveNode(node.id); setActiveEdge(null)
    setDrag({ id: node.id, sx: e.clientX, sy: e.clientY, ox: node.x, oy: node.y })
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag) return
    const dx = (e.clientX - drag.sx) / zoom, dy = (e.clientY - drag.sy) / zoom
    setNodes((p) => p.map((n) => n.id === drag.id ? { ...n, x: Math.max(0, drag.ox + dx), y: Math.max(0, drag.oy + dy) } : n))
  }
  const onPointerUp = () => setDrag(null)

  const edgePaths = useMemo(() => edges.map((e) => {
    const s = nodes.find((n) => n.id === e.source), d = nodes.find((n) => n.id === e.target)
    if (!s || !d) return null
    const x1 = s.x + NODE_W, y1 = s.y + NODE_H / 2, x2 = d.x, y2 = d.y + NODE_H / 2
    const mx = (x1 + x2) / 2
    return { e, d: `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`, mx, my: (y1 + y2) / 2 }
  }).filter(Boolean) as { e: WfEdge; d: string; mx: number; my: number }[], [edges, nodes])

  return (
    <div className="mx-auto max-w-[1700px]">
      <PageHeader icon={<GitBranch className="h-5 w-5" />} title={t('workflows.title')} subtitle={t('workflows.subtitle')}
        actions={<>
          <Segmented value={view} onChange={setView} options={[
            { value: 'portal', label: t('portal.viewPortal'), icon: <LayoutGrid className="h-3 w-3" /> },
            { value: 'designer', label: t('portal.viewDesigner'), icon: <GitBranch className="h-3 w-3" /> },
          ]} />
          <Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>
          {can('workflow:write') && <Button size="sm" onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" />{t('workflows.newWorkflow')}</Button>}
        </>} />

      {view === 'portal' && <WorkflowPortal onDesign={(code) => {
        setView('designer')
        const target = workflows.find((w) => w.code === code)
        if (target) select(target)
      }} />}

      {view === 'designer' && (
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[14rem_minmax(0,1fr)_19rem]">
        {/* left */}
        <div className="space-y-4">
          <Card><CardContent className="p-3">
            <SectionTitle>{t('workflows.workflowList')}</SectionTitle>
            <div className="scroll-thin max-h-52 space-y-1 overflow-y-auto">
              {workflows.map((w) => (
                <button key={w.id} onClick={() => select(w)}
                  className={cn('flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-all',
                    selected?.id === w.id ? 'bg-primary/10 text-primary' : 'hover:bg-muted')}>
                  <GitBranch className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium">{w.name}</span>
                    <span className="block truncate font-mono text-[10px] text-muted-foreground">{w.code}</span></span>
                  <Badge variant={w.status === 'published' ? 'success' : 'muted'} className="shrink-0 text-[9px]">{w.status}</Badge>
                </button>
              ))}
              {!workflows.length && <p className="py-6 text-center text-xs text-muted-foreground">{t('common.noData')}</p>}
            </div>
          </CardContent></Card>

          {selected && <Card><CardContent className="p-3">
            <SectionTitle>{t('workflows.palette')}</SectionTitle>
            <div className="grid grid-cols-2 gap-1.5">
              {nodeTypes.map((nt) => {
                const Icon = NODE_ICONS[nt.type] || CircleDot
                return <button key={nt.type} onClick={() => addNode(nt.type)}
                  className="flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-left text-[11px] transition-all hover:border-primary/40 hover:bg-primary/5">
                  <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: nt.color }} />
                  <Icon className="h-3 w-3 shrink-0 text-muted-foreground" />
                  <span className="truncate">{nt.name.split(' / ')[0]}</span>
                </button>
              })}
            </div>
            <p className="mt-2 text-[10px] text-muted-foreground">{t('workflows.clickEdgeHint')}</p>
          </CardContent></Card>}
        </div>

        {/* canvas */}
        <Card className="min-h-[34rem] overflow-hidden">
          {!selected ? (
            <EmptyState icon={<GitBranch className="h-5 w-5" />} title={t('workflows.emptyTitle')} description={t('workflows.emptyText')}
              action={can('workflow:write') ? <Button size="sm" onClick={() => setCreateOpen(true)}><Plus className="h-3.5 w-3.5" />{t('workflows.newWorkflow')}</Button> : undefined} />
          ) : (
            <>
              <div className="border-b px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <h2 className="truncate text-sm font-semibold">{meta.name}</h2>
                  <Badge variant={meta.status === 'published' ? 'success' : 'muted'}>{meta.status}</Badge>
                  <span className="ml-auto whitespace-nowrap text-[10px] text-muted-foreground">
                    {t('workflows.nodeCount', { count: nodes.length, edges: edges.length })} · v{selected.version}</span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1">
                  <Button variant={connectMode ? 'default' : 'outline'} size="icon-sm" title={t('workflows.connect')}
                    onClick={() => { setConnectMode(!connectMode); setConnectFrom(null) }}><Link2 className="h-3.5 w-3.5" /></Button>
                  <Button variant="outline" size="icon-sm" title={t('workflows.autoLayout')} onClick={autoLayout}><LayoutGrid className="h-3.5 w-3.5" /></Button>
                  <Button variant="outline" size="icon-sm" title={t('workflows.zoomOut')} onClick={() => setZoom((z) => Math.max(.6, z - .1))}><ZoomOut className="h-3.5 w-3.5" /></Button>
                  <span className="w-9 text-center font-mono text-[10px] text-muted-foreground">{Math.round(zoom * 100)}%</span>
                  <Button variant="outline" size="icon-sm" title={t('workflows.zoomIn')} onClick={() => setZoom((z) => Math.min(1.5, z + .1))}><ZoomIn className="h-3.5 w-3.5" /></Button>
                  <Button variant="outline" size="sm" onClick={() => setMetaOpen(true)}><Settings2 className="h-3.5 w-3.5" /></Button>
                  <Button variant="outline" size="sm" onClick={validate}>{t('common.validate')}</Button>
                  <Button variant="outline" size="sm" loading={saving} onClick={() => save(false)} disabled={!can('workflow:write')}><Save className="h-3.5 w-3.5" />{t('common.save')}</Button>
                  <Button variant="outline" size="sm" onClick={() => void openVersions()}><History className="h-3.5 w-3.5" />{t('workflows.versions')}</Button>
                  <Button variant="outline" size="sm" onClick={() => setRightTab('tasks')}><ListTodo className="h-3.5 w-3.5" />{t('workflows.tasks')}</Button>
                  <Button variant="outline" size="sm" onClick={() => void openStart()} disabled={!can('workflow:run')}><Send className="h-3.5 w-3.5" />{t('workflows.start')}</Button>
                  <Button size="sm" onClick={() => { setRunResult(null); setRunOpen(true) }} disabled={!can('workflow:run')}><Play className="h-3.5 w-3.5" />{t('common.run')}</Button>
                </div>
              </div>

              {connectMode && (
                <div className="flex items-center gap-2 border-b bg-primary/5 px-3 py-1.5 text-[11px] text-primary">
                  <Link2 className="h-3 w-3" />{connectFrom ? t('workflows.connectActive') : t('workflows.connectHint')}
                  <Button variant="ghost" size="icon-sm" className="ml-auto" onClick={() => { setConnectMode(false); setConnectFrom(null) }}><X className="h-3 w-3" /></Button>
                </div>
              )}

              <div ref={canvasRef} className="scroll-thin relative h-[30rem] overflow-auto bg-muted/20"
                style={{ backgroundImage: 'radial-gradient(hsl(var(--border)) 1px, transparent 1px)', backgroundSize: '18px 18px' }}>
                <div className="relative" style={{ width: 1700, height: 760, transform: `scale(${zoom})`, transformOrigin: '0 0' }}>
                  <svg className="pointer-events-none absolute inset-0" width="1700" height="760">
                    <defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto">
                      <path d="M0 0 L9 4.5 L0 9 z" fill="hsl(var(--muted-foreground))" /></marker></defs>
                    {edgePaths.map(({ e, d, mx, my }) => (
                      <g key={e.id}>
                        <path d={d} fill="none" stroke={activeEdge === e.id ? 'hsl(var(--primary))' : 'hsl(var(--muted-foreground))'}
                          strokeWidth={activeEdge === e.id ? 2.5 : 1.8} markerEnd="url(#arrow)" opacity={.75}
                          style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
                          onClick={() => { if (!connectMode) { setActiveEdge(e.id); setActiveNode(null); setRightTab('properties') } }} />
                        <path d={d} fill="none" stroke="transparent" strokeWidth="14" style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
                          onClick={() => { if (!connectMode) { setActiveEdge(e.id); setActiveNode(null); setRightTab('properties') } }} />
                        {e.label && <text x={mx} y={my - 7} textAnchor="middle" fontSize="10" fill="hsl(var(--muted-foreground))">{e.label}</text>}
                      </g>
                    ))}
                  </svg>
                  {nodes.map((n) => {
                    const nt = typeOf(n.type), Icon = NODE_ICONS[n.type] || CircleDot
                    const isSelected = activeNode === n.id || (connectMode && connectFrom === n.id)
                    return (
                      <div key={n.id}
                        onPointerDown={(e) => onPointerDown(e, n)} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
                        onClick={() => { if (connectMode) handleNodeClick(n.id); else if (!drag) { setActiveNode(n.id); setActiveEdge(null) } }}
                        className={cn('absolute select-none rounded-xl border bg-card shadow-sm transition-shadow',
                          isSelected && 'ring-2 ring-primary/50 shadow-glow', connectMode && 'cursor-crosshair')}
                        style={{ left: n.x, top: n.y, width: NODE_W, minHeight: NODE_H, borderColor: isSelected ? nt.color : undefined }}>
                        <div className="flex items-center gap-2 rounded-t-xl border-b px-2.5 py-1.5" style={{ borderLeft: `3px solid ${nt.color}` }}>
                          <span className="flex h-6 w-6 items-center justify-center rounded-md" style={{ background: `${nt.color}22`, color: nt.color }}><Icon className="h-3.5 w-3.5" /></span>
                          <span className="min-w-0 flex-1 truncate text-[11px] font-medium">{n.name}</span>
                        </div>
                        <div className="flex items-center justify-between px-2.5 py-1">
                          <span className="text-[9px] uppercase tracking-wide text-muted-foreground">{n.type}</span>
                          <span className="font-mono text-[9px] text-muted-foreground">{n.id}</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2 border-t px-3 py-2">
                <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)} disabled={!can('workflow:write')}><Trash2 className="h-3.5 w-3.5 text-destructive" />{t('common.delete')}</Button>
                <span className="text-[10px] text-muted-foreground">{t('workflows.clickEdgeHint')}</span>
                <Button variant="outline" size="sm" className="ml-auto" onClick={() => save(true)} disabled={!can('workflow:write')}>{t('forms.publish')}</Button>
              </div>
            </>
          )}
        </Card>

        {/* right */}
        <Card className="h-fit">
          <CardContent className="p-3">
            <Tabs value={rightTab} onValueChange={setRightTab} className="mb-3 w-full" items={[
              { value: 'properties', label: t('workflows.properties') },
              { value: 'tasks', label: t('workflows.tasks'), count: tasks.filter((x) => x.status === 'pending').length },
              { value: 'runs', label: t('workflows.instances'), count: instances.length },
            ]} />
            {rightTab === 'properties' && (
              active ? <NodeProperties node={active} operators={operators} meta={flowMeta} forms={forms}
                  schema={(typeOf(active.type) as any)?.config_schema || []}
                  patch={patchNode} patchConfig={patchConfig} remove={removeNode} /> :
              activeE ? <EdgeProperties edge={activeE} onChange={(p) => setEdges((prev) => prev.map((e) => e.id === activeE.id ? { ...e, ...p } : e))}
                onDelete={() => { setEdges((p) => p.filter((e) => e.id !== activeE.id)); setActiveEdge(null) }} /> :
              <p className="py-8 text-center text-xs text-muted-foreground">{t('workflows.properties')}</p>
            )}
            {rightTab === 'tasks' && (
              <div className="space-y-2">
                <Select className="h-8 text-xs" value={taskStatus}
                  onValueChange={(v) => { setTaskStatus(v); void loadTasks(v) }}
                  options={[
                    { value: 'pending', label: t('workflows.pendingTasks') },
                    { value: 'approved', label: t('workflows.approvedTasks') },
                    { value: 'all', label: t('workflows.allTasks') },
                  ]} />
                <div className="scroll-thin max-h-[30rem] space-y-2 overflow-y-auto">
                  {tasks.map((task) => (
                    <div key={task.id} className="rounded-lg border p-2.5">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs">#{task.id}</span>
                        <span className="min-w-0 flex-1 truncate text-xs font-medium">{task.node_name}</span>
                        <Badge variant={task.status === 'pending' ? 'warning' : task.status === 'approved' ? 'success' : 'muted'}
                          className="text-[9px]">{task.status}</Badge>
                      </div>
                      <p className="mt-1 text-[10px] text-muted-foreground">
                        {t('workflows.instance')} #{task.instance_id} · {task.assignee}
                        {task.due_at ? ` · ${t('workflows.dueAt')} ${formatDate(task.due_at, locale)}` : ''}
                        {task.round > 1 ? ` · R${task.round}` : ''}
                      </p>
                      {task.status === 'pending' && <div className="mt-2 flex flex-wrap gap-1">
                        {[
                          { a: 'approve', label: t('workflows.approve'), icon: <UserCheck className="h-3 w-3" /> },
                          { a: 'reject', label: t('workflows.reject'), icon: <X className="h-3 w-3" /> },
                          { a: 'return', label: t('workflows.returnTask'), icon: <Undo2 className="h-3 w-3" /> },
                          { a: 'transfer', label: t('workflows.transfer'), icon: <ArrowRightLeft className="h-3 w-3" /> },
                          { a: 'addsign_after', label: t('workflows.addsign'), icon: <UserPlus className="h-3 w-3" /> },
                        ].map((x) => <Button key={x.a} variant="outline" size="sm"
                          onClick={() => { setActDialog({ task, action: x.a }); setActForm({
                            comment: '', assignee: '', return_to: 'initiator' }) }}>
                          {x.icon}{x.label}</Button>)}
                      </div>}
                    </div>
                  ))}
                  {!tasks.length && <p className="py-8 text-center text-xs text-muted-foreground">{t('workflows.noTasks')}</p>}
                </div>
              </div>
            )}
            {rightTab === 'runs' && (
              <div className="scroll-thin max-h-[30rem] space-y-2 overflow-y-auto">
                {instances.map((ins) => (
                  <button key={ins.id} onClick={() => void openInstance(ins.id)}
                    className="w-full rounded-lg border p-2.5 text-left transition-all hover:border-primary/40 hover:bg-primary/5">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs">#{ins.id}</span>
                      <Badge variant={ins.status === 'approved' || ins.status === 'completed' ? 'success'
                        : ins.status === 'rejected' || ins.status === 'failed' ? 'destructive' : 'warning'}>{ins.status}</Badge>
                      {!!ins.task_count && <Badge variant="muted" className="text-[9px]">{ins.task_count} tasks</Badge>}
                      <span className="ml-auto text-[10px] text-muted-foreground">{formatDate(ins.started_at, locale)}</span>
                    </div>
                    <div className="mt-2 space-y-1">
                      {(ins.logs || []).slice(-4).map((log: any, i: number) => (
                        <div key={i} className="flex items-center gap-1.5 text-[10px]">
                          <span className={cn('h-1.5 w-1.5 rounded-full', log.event === 'node_failed' ? 'bg-destructive' : 'bg-success')} />
                          <span className="truncate">{String(log.event || log.name || log.type || log.node)}</span>
                          {log.branch && <Badge variant="outline" className="text-[9px]">{log.branch}</Badge>}
                        </div>
                      ))}
                    </div>
                  </button>
                ))}
                {!instances.length && <p className="py-8 text-center text-xs text-muted-foreground">{t('workflows.noInstances')}</p>}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
      )}

      {/* dialogs */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen} title={t('workflows.createTitle')}
        footer={<><Button variant="outline" onClick={() => setCreateOpen(false)}>{t('common.cancel')}</Button><Button onClick={create}>{t('common.create')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('workflows.workflowCode')}><Input value={newWf.code} onChange={(e) => setNewWf({ ...newWf, code: e.target.value })} placeholder="my_flow" /></Field>
          <Field label={t('workflows.workflowName')}><Input value={newWf.name} onChange={(e) => setNewWf({ ...newWf, name: e.target.value })} /></Field>
          <Field label={t('common.description')}><Textarea value={newWf.description} onChange={(e) => setNewWf({ ...newWf, description: e.target.value })} /></Field>
          <Field label={t('workflows.formCode')} hint={t('workflows.formCodeHint')}>
            <Select value={newWf.form_code} onValueChange={(v) => setNewWf({ ...newWf, form_code: v })}
              options={[{ value: '', label: t('common.none') },
                ...forms.map((f) => ({ value: f.code, label: `${f.name} · ${f.code}` }))]} />
          </Field>
        </div>
      </Dialog>

      <Dialog open={metaOpen} onOpenChange={setMetaOpen} title={t('workflows.editTitle')}
        footer={<><Button variant="outline" onClick={() => setMetaOpen(false)}>{t('common.cancel')}</Button><Button onClick={() => { setMetaOpen(false); void save(false) }}>{t('common.save')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('workflows.workflowName')}><Input value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} /></Field>
          <Field label={t('common.description')}><Textarea value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })} /></Field>
          <Field label={t('workflows.formCode')} hint={t('workflows.formCodeHint')}>
            <Select value={meta.form_code} onValueChange={(v) => setMeta({ ...meta, form_code: v })}
              options={[{ value: '', label: t('common.none') },
                ...forms.map((f) => ({ value: f.code, label: `${f.name} · ${f.code}` }))]} />
          </Field>
          <Field label={t('common.status')}><Select value={meta.status} onValueChange={(v) => setMeta({ ...meta, status: v })}
            options={(bootstrap?.workflow.statuses || ['draft', 'published', 'archived']).map((s) => ({ value: s, label: t(`common.${s}`) }))} /></Field>
        </div>
      </Dialog>

      <Dialog open={runOpen} onOpenChange={setRunOpen} title={t('workflows.runTitle', { name: selected?.name || '' })} size="lg"
        footer={<><Button variant="outline" onClick={() => setRunOpen(false)}>{t('common.close')}</Button><Button onClick={run}><Play className="h-3.5 w-3.5" />{t('common.run')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('workflows.initialContext')}><Textarea className="font-mono text-xs" rows={6} value={contextText} onChange={(e) => setContextText(e.target.value)} /></Field>
          {runResult && (
            <div className="rounded-lg border bg-muted/30 p-3">
              <div className="mb-2 flex items-center gap-2 text-xs">
                <Badge variant={runResult.status === 'completed' ? 'success' : 'destructive'}>{runResult.status}</Badge>
                <span className="font-mono text-muted-foreground">#{runResult.instance_id} · {runResult.steps?.length ?? 0} steps</span>
              </div>
              <div className="scroll-thin max-h-52 space-y-1 overflow-y-auto">
                {(runResult.logs || []).map((l: any, i: number) => (
                  <div key={i} className="flex items-start gap-2 rounded bg-background/60 px-2 py-1 font-mono text-[10px]">
                    <span className={cn('mt-1 h-1.5 w-1.5 shrink-0 rounded-full', l.status === 'failed' ? 'bg-destructive' : 'bg-success')} />
                    <span className="shrink-0 text-primary">{l.node}</span>
                    <span className="truncate text-muted-foreground">{JSON.stringify(l.output || l.error || {})}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </Dialog>

      <Dialog open={startOpen} onOpenChange={setStartOpen} title={t('workflows.startTitle', { name: selected?.name || '' })} size="lg"
        footer={<><Button variant="outline" onClick={() => setStartOpen(false)}>{t('common.cancel')}</Button>
          <Button onClick={startInstance}><Send className="h-3.5 w-3.5" />{t('workflows.start')}</Button></>}>
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">{t('workflows.startHint')}</p>
          {startSchema?.form && <div className="flex flex-wrap items-center gap-2">
            <Badge variant="muted">{startSchema.form.name}</Badge>
            <span className="text-[10px] text-muted-foreground">
              v{startSchema.form.version} · {startSchema.fields.length} {t('forms.fields').toLowerCase()}
            </span>
          </div>}
          <SchemaForm fields={startSchema?.fields || []} value={startValues}
            onChange={setStartValues} formId={startSchema?.form?.id} errors={startErrors} />
          {!startSchema?.fields?.length &&
            <p className="py-4 text-center text-xs text-muted-foreground">
              {startSchema?.hint || t('common.noData')}</p>}
        </div>
      </Dialog>

      <Dialog open={!!actDialog} onOpenChange={() => setActDialog(null)}
        title={actDialog ? t('workflows.taskAction', { action: actDialog.action }) : ''} size="sm"
        footer={<><Button variant="outline" onClick={() => setActDialog(null)}>{t('common.cancel')}</Button>
          <Button onClick={doAct}><CheckCircle2 className="h-3.5 w-3.5" />{t('common.confirm')}</Button></>}>
        {actDialog && <div className="space-y-3">
          <div className="rounded-lg border bg-muted/30 p-2 text-xs">
            <p className="font-medium">{actDialog.task.node_name}</p>
            <p className="text-[10px] text-muted-foreground">
              #{actDialog.task.id} · {actDialog.task.assignee} · {t('workflows.instance')} #{actDialog.task.instance_id}</p>
          </div>
          {['approve', 'reject', 'return'].includes(actDialog.action) && <Field label={t('workflows.comment')}>
            <Textarea rows={3} value={actForm.comment}
              onChange={(e) => setActForm({ ...actForm, comment: e.target.value })} /></Field>}
          {['transfer', 'addsign_before', 'addsign_after'].includes(actDialog.action) &&
            <Field label={t('workflows.assignee')}><Input value={actForm.assignee}
              placeholder="username" onChange={(e) => setActForm({ ...actForm, assignee: e.target.value })} /></Field>}
          {actDialog.action === 'return' && <Field label={t('workflows.returnTo')}>
            <Select value={actForm.return_to} onValueChange={(v) => setActForm({ ...actForm, return_to: v })}
              options={[{ value: 'initiator', label: t('workflows.initiator') },
                { value: 'previous', label: t('workflows.previous') }]} /></Field>}
        </div>}
      </Dialog>

      <Dialog open={detailOpen} onOpenChange={setDetailOpen} title={t('workflows.instanceDetail', { id: instanceDetail?.id || 0 })} size="lg"
        footer={<><Button variant="outline" size="sm" onClick={withdrawInstance}
          disabled={instanceDetail?.status !== 'running'}><Undo2 className="h-3.5 w-3.5" />{t('workflows.withdraw')}</Button>
          <Button size="sm" onClick={() => setDetailOpen(false)}>{t('common.close')}</Button></>}>
        {instanceDetail && <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/20 p-2.5">
            <Badge variant={instanceDetail.status === 'approved' ? 'success'
              : instanceDetail.status === 'rejected' || instanceDetail.status === 'canceled' ? 'destructive' : 'warning'}>
              {instanceDetail.status}</Badge>
            <span className="text-xs">{instanceDetail.form_code || '-'}</span>
            <span className="ml-auto text-[10px] text-muted-foreground">
              v{instanceDetail.workflow_version} · {instanceDetail.started_by} · {formatDate(instanceDetail.started_at, locale)}</span>
          </div>
          {!!instanceDetail.current_nodes?.length && <p className="text-[11px]">
            {t('workflows.currentNodes')}: <span className="font-mono">{instanceDetail.current_nodes.join(', ')}</span></p>}
          <div className="grid gap-3 md:grid-cols-2">
            <div><p className="mb-1.5 text-xs font-semibold">{t('workflows.tasks')} ({instanceDetail.tasks?.length || 0})</p>
              <div className="scroll-thin max-h-52 space-y-1 overflow-y-auto">
                {(instanceDetail.tasks || []).map((task) => <div key={task.id}
                  className="flex items-center gap-2 rounded border px-2 py-1.5 text-[10px]">
                  <span className={cn('h-1.5 w-1.5 rounded-full', task.status === 'pending' ? 'bg-amber-500'
                    : task.status === 'approved' ? 'bg-emerald-500' : 'bg-muted-foreground')} />
                  <span className="min-w-0 flex-1 truncate">{task.node_name}</span>
                  <span className="font-mono">{task.assignee}</span>
                  <Badge variant="muted" className="text-[9px]">{task.status}</Badge>
                </div>)}
                {!instanceDetail.tasks?.length && <p className="text-[10px] text-muted-foreground">{t('common.noData')}</p>}
              </div>
            </div>
            <div><p className="mb-1.5 text-xs font-semibold">{t('workflows.timeline')}</p>
              <div className="scroll-thin max-h-52 space-y-1 overflow-y-auto">
                {(instanceDetail.logs || []).slice().reverse().map((log: any, i: number) =>
                  <div key={i} className="rounded border px-2 py-1.5 text-[10px]">
                    <span className="font-mono text-primary">{log.event || log.node}</span>
                    {log.actor && <span className="ml-1 text-muted-foreground">· {log.actor}</span>}
                    {log.comment && <span className="ml-1 text-muted-foreground">· {log.comment}</span>}
                  </div>)}
              </div>
            </div>
          </div>
          <details className="rounded-lg border p-2">
            <summary className="cursor-pointer text-xs font-medium">{t('workflows.formData')}</summary>
            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-muted-foreground">
              {JSON.stringify(instanceDetail.form_data || {}, null, 2)}</pre>
          </details>
        </div>}
      </Dialog>

      <Dialog open={versionsOpen} onOpenChange={setVersionsOpen} title={t('workflows.versions')} size="md"
        footer={<Button variant="outline" onClick={() => setVersionsOpen(false)}>{t('common.close')}</Button>}>
        <div className="space-y-2">
          {wfVersions.map((v) => <div key={v.id} className="flex items-center gap-2 rounded-lg border px-3 py-2">
            <Badge variant="muted">v{v.version}</Badge>
            <span className="min-w-0 flex-1 truncate text-xs">{v.note || '-'}</span>
            <span className="text-[10px] text-muted-foreground">{formatDate(v.created_at, locale)}</span>
            {can('workflow:write') && <Button variant="outline" size="sm"
              onClick={() => void restoreVersion(v.version)}>{t('workflows.restore')}</Button>}
          </div>)}
          {!wfVersions.length && <p className="py-6 text-center text-xs text-muted-foreground">{t('common.noData')}</p>}
        </div>
      </Dialog>

      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} title={t('common.confirmDelete')}
        description={selected?.name} onConfirm={remove} />
    </div>
  )
}

function defaultConfig(type: string): Record<string, unknown> {
  return ({
    start: { form_code: '' },
    form: { form_code: 'leave_request', assignee: '${initiator}' },
    condition: { field: 'days', operator: 'gt', value: 3, logic: 'and', conditions: [] },
    approval: { approver_rule: 'roles', roles: ['admin'], sign_mode: 'any',
      empty_policy: 'admin', timeout_hours: 24, timeout_action: 'remind',
      comment_required: false, signature_required: false, field_permissions: {},
      reject_policy: 'terminate', allow_return: true, allow_transfer: true, allow_addsign: true },
    cc: { approver_rule: 'users', assignees: [] },
    join: { join_mode: 'all' },
    delay: { delay_hours: 1 },
    subflow: { workflow_code: '' },
    ai: { prompt: 'Summarize this workflow context.' },
    knowledge: { query: 'policy', top_k: 3 },
    http: { method: 'POST', url: 'https://api.example.com/hook' },
    notification: { channel: 'in-app', template: 'Task completed' },
  } as Record<string, Record<string, unknown>>)[type] || {}
}

function NodeProperties({ node, operators, patch, patchConfig, remove, meta, forms, schema }: {
  node: WfNode; operators: string[]; meta: FlowMeta | null; forms: FormDef[]
  schema: ConfigField[]
  patch: (id: string, p: Partial<WfNode>) => void
  patchConfig: (k: string, v: any) => void; remove: (id: string) => void
}) {
  const { t } = useI18n()
  const Icon = NODE_ICONS[node.type] || CircleDot
  const cfg: any = node.config || {}
  const csv = (v: any) => Array.isArray(v) ? v.join(', ') : (v ?? '')
  const labelOf = (f: ConfigField) => {
    const key = `workflows.cfg.${f.key}`
    const translated = t(key)
    return translated === key ? (f.label || f.key) : translated
  }
  const jsonValue = (f: ConfigField) => {
    const v = cfg[f.key] ?? f.default
    if (v === undefined || v === null || v === '') return ''
    return typeof v === 'string' ? v : JSON.stringify(v, null, 2)
  }
  const optionsFor = (f: ConfigField) => {
    if (f.key === 'approver_rule' && meta?.approver_rules?.length)
      return meta.approver_rules.map((r) => ({ value: r.code, label: r.label }))
    if (f.key === 'sign_mode' && meta?.sign_modes?.length)
      return meta.sign_modes.map((r) => ({ value: r.code, label: r.label }))
    if (f.key === 'empty_policy' && meta?.empty_policies?.length)
      return meta.empty_policies.map((r) => ({ value: r.code, label: r.label }))
    if (f.key === 'timeout_action' && meta?.timeout_actions?.length)
      return meta.timeout_actions.map((r) => ({ value: r.code, label: r.label }))
    if (f.key === 'operator') return operators.map((o) => ({ value: o, label: o }))
    return (f.options || []).map((o) => ({ value: String(o), label: String(o) }))
  }

  const renderField = (f: ConfigField) => {
    const value = cfg[f.key] ?? f.default ?? ''
    switch (f.type) {
      case 'boolean':
        return <div key={f.key} className="flex items-center justify-between rounded-lg border px-2.5 py-1.5">
          <span className="text-[11px] font-medium">{labelOf(f)}</span>
          <Switch checked={!!value} onCheckedChange={(v) => patchConfig(f.key, v)} /></div>
      case 'select':
        return <Field key={f.key} label={labelOf(f)} hint={f.help}>
          <Select value={String(value || '')} onValueChange={(v) => patchConfig(f.key, v)}
            options={[{ value: '', label: t('common.none') }, ...optionsFor(f)]} /></Field>
      case 'number':
        return <Field key={f.key} label={labelOf(f)} hint={f.help}>
          <Input type="number" value={value as any} placeholder={f.placeholder}
            onChange={(e) => patchConfig(f.key, e.target.value === '' ? '' : Number(e.target.value))} /></Field>
      case 'textarea':
      case 'code':
        return <Field key={f.key} label={labelOf(f)} hint={f.help}>
          <Textarea rows={f.type === 'code' ? 4 : 3}
            className={f.type === 'code' ? 'font-mono text-[10px]' : ''}
            value={String(value ?? '')} placeholder={f.placeholder}
            onChange={(e) => patchConfig(f.key, e.target.value)} /></Field>
      case 'json':
        return <Field key={f.key} label={labelOf(f)} hint={f.help || 'JSON'}>
          <Textarea rows={3} className="font-mono text-[10px]" value={jsonValue(f)}
            onChange={(e) => { try { patchConfig(f.key, e.target.value.trim()
              ? JSON.parse(e.target.value) : {}) } catch { /* keep typing */ } }} /></Field>
      case 'list':
        return <Field key={f.key} label={labelOf(f)} hint={f.help || 'comma separated'}>
          <Input value={csv(value)} placeholder={f.placeholder}
            onChange={(e) => patchConfig(f.key, e.target.value.split(',').map((x) => x.trim()).filter(Boolean))} /></Field>
      case 'form':
        return <Field key={f.key} label={labelOf(f)} hint={f.help}>
          <Select value={String(value || '')} onValueChange={(v) => patchConfig(f.key, v)}
            options={[{ value: '', label: t('common.none') },
              ...forms.map((x) => ({ value: x.code, label: `${x.name} · ${x.code}` }))]} /></Field>
      default:
        return <Field key={f.key} label={labelOf(f)} hint={f.help}>
          <Input value={String(value ?? '')} placeholder={f.placeholder}
            onChange={(e) => patchConfig(f.key, e.target.value)} /></Field>
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 rounded-lg border bg-muted/30 p-2">
        <Icon className="h-4 w-4 text-primary" /><span className="text-xs font-medium">{node.type}</span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">{node.id}</span>
      </div>
      <Field label={t('workflows.nodeName')}>
        <Input value={node.name} onChange={(e) => patch(node.id, { name: e.target.value })} /></Field>
      {schema.length > 0 ? (
        <>
          <p className="text-[10px] text-muted-foreground">{t('registry.propertyHint')}</p>
          {schema.map(renderField)}
        </>
      ) : (
        <p className="py-4 text-center text-[11px] text-muted-foreground">{t('registry.none')}</p>
      )}
      <Button variant="outline" size="sm" className="w-full" onClick={() => remove(node.id)}>
        <Trash2 className="h-3.5 w-3.5 text-destructive" />{t('workflows.deleteNode')}</Button>
    </div>
  )
}

function EdgeProperties({ edge, onChange, onDelete }: {
  edge: WfEdge; onChange: (p: Partial<WfEdge>) => void; onDelete: () => void
}) {
  const { t } = useI18n()
  return (
    <div className="space-y-3">
      <div className="rounded-lg border bg-muted/30 p-2 font-mono text-[10px]">{edge.source} → {edge.target}</div>
      <Field label={t('common.label')}><Input value={edge.label || ''} onChange={(e) => onChange({ label: e.target.value })} /></Field>
      <Field label={t('workflows.branchTrue') + ' / ' + t('workflows.branchFalse')}>
        <Select value={edge.condition || ''} onValueChange={(v) => onChange({ condition: v || undefined })}
          options={[{ value: '', label: t('common.none') }, { value: 'true', label: 'true' }, { value: 'false', label: 'false' }]} />
      </Field>
      <Button variant="outline" size="sm" className="w-full" onClick={onDelete}><Trash2 className="h-3.5 w-3.5 text-destructive" />{t('workflows.deleteEdge')}</Button>
    </div>
  )
}
