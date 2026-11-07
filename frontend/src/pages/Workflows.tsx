import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Bell, BookOpen, Bot, CheckCircle2, CircleDot, FileText, GitBranch, Globe2,
  LayoutGrid, Link2, Minus, Play, Plus, RefreshCw, Save, Settings2, ShieldCheck,
  Sparkles, Square, Trash2, X, ZoomIn, ZoomOut,
} from 'lucide-react'
import { PageHeader, SectionTitle } from '@/components/PageHeader'
import {
  Badge, Button, Card, CardContent, EmptyState, Field, Input, Label, Segmented,
  Select, Textarea,
} from '@/components/ui/basic'
import { ConfirmDialog, Dialog, Tabs, useToast } from '@/components/ui/overlay'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { del, get, post, put } from '@/lib/api'
import { cn, formatDate, safeParse, uid } from '@/lib/utils'
import type { WfEdge, WfGraph, WfNode, WorkflowDef, WorkflowInstance } from '@/types'

const NODE_ICONS: Record<string, typeof Play> = {
  start: Play, end: Square, form: FileText, condition: GitBranch, approval: ShieldCheck,
  ai: Sparkles, knowledge: BookOpen, http: Globe2, notification: Bell,
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
]
const NODE_W = 176, NODE_H = 64

export default function Workflows() {
  const { t, locale } = useI18n()
  const { can, bootstrap } = useApp()
  const { toast } = useToast()
  const canvasRef = useRef<HTMLDivElement>(null)
  const [searchParams] = useSearchParams()

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
  const [meta, setMeta] = useState({ name: '', description: '', status: 'draft' })
  const [rightTab, setRightTab] = useState('properties')
  const [saving, setSaving] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [metaOpen, setMetaOpen] = useState(false)
  const [runOpen, setRunOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [contextText, setContextText] = useState('{\n  "days": 2,\n  "leave_type": "Annual"\n}')
  const [runResult, setRunResult] = useState<any>(null)
  const [instances, setInstances] = useState<WorkflowInstance[]>([])
  const [newWf, setNewWf] = useState({ code: '', name: '', description: '' })

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
  useEffect(() => { void load() }, [])

  const select = (wf: WorkflowDef) => {
    setSelected(wf); setNodes(wf.graph?.nodes || []); setEdges(wf.graph?.edges || [])
    setActiveNode(wf.graph?.nodes?.[0]?.id || null); setActiveEdge(null)
    setMeta({ name: wf.name, description: wf.description || '', status: wf.status })
    setRunResult(null); void loadInstances(wf.id)
  }

  // Deep link: /#/workflows?workflow=leave_approval opens a specific canvas.
  useEffect(() => {
    const code = searchParams.get('workflow')
    if (!code || !workflows.length) return
    const target = workflows.find((w) => w.code === code)
    if (target && selected?.id !== target.id) select(target)
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
        graph: { nodes, edges },
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
      const wf = await post<WorkflowDef>('/workflows', { ...newWf, status: 'draft', graph })
      setCreateOpen(false); setNewWf({ code: '', name: '', description: '' }); await load(); select(wf)
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
          <Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>
          {can('workflow:write') && <Button size="sm" onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" />{t('workflows.newWorkflow')}</Button>}
        </>} />

      <div className="grid gap-4 lg:grid-cols-[14rem_minmax(0,1fr)_19rem]">
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
              { value: 'runs', label: t('workflows.instances'), count: instances.length },
            ]} />
            {rightTab === 'properties' && (
              active ? <NodeProperties node={active} operators={operators} patch={patchNode} patchConfig={patchConfig} remove={removeNode} /> :
              activeE ? <EdgeProperties edge={activeE} onChange={(p) => setEdges((prev) => prev.map((e) => e.id === activeE.id ? { ...e, ...p } : e))}
                onDelete={() => { setEdges((p) => p.filter((e) => e.id !== activeE.id)); setActiveEdge(null) }} /> :
              <p className="py-8 text-center text-xs text-muted-foreground">{t('workflows.properties')}</p>
            )}
            {rightTab === 'runs' && (
              <div className="scroll-thin max-h-[30rem] space-y-2 overflow-y-auto">
                {instances.map((ins) => (
                  <div key={ins.id} className="rounded-lg border p-2.5">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs">#{ins.id}</span>
                      <Badge variant={ins.status === 'completed' ? 'success' : ins.status === 'failed' ? 'destructive' : 'warning'}>{ins.status}</Badge>
                      <span className="ml-auto text-[10px] text-muted-foreground">{formatDate(ins.started_at, locale)}</span>
                    </div>
                    <div className="mt-2 space-y-1">
                      {(ins.logs || []).map((log: any, i: number) => (
                        <div key={i} className="flex items-center gap-1.5 text-[10px]">
                          <span className={cn('h-1.5 w-1.5 rounded-full', log.status === 'failed' ? 'bg-destructive' : 'bg-success')} />
                          <span className="truncate">{String(log.name || log.type || log.node)}</span>
                          {log.branch && <Badge variant="outline" className="text-[9px]">{log.branch}</Badge>}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
                {!instances.length && <p className="py-8 text-center text-xs text-muted-foreground">{t('workflows.noInstances')}</p>}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* dialogs */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen} title={t('workflows.createTitle')}
        footer={<><Button variant="outline" onClick={() => setCreateOpen(false)}>{t('common.cancel')}</Button><Button onClick={create}>{t('common.create')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('workflows.workflowCode')}><Input value={newWf.code} onChange={(e) => setNewWf({ ...newWf, code: e.target.value })} placeholder="my_flow" /></Field>
          <Field label={t('workflows.workflowName')}><Input value={newWf.name} onChange={(e) => setNewWf({ ...newWf, name: e.target.value })} /></Field>
          <Field label={t('common.description')}><Textarea value={newWf.description} onChange={(e) => setNewWf({ ...newWf, description: e.target.value })} /></Field>
        </div>
      </Dialog>

      <Dialog open={metaOpen} onOpenChange={setMetaOpen} title={t('workflows.editTitle')}
        footer={<><Button variant="outline" onClick={() => setMetaOpen(false)}>{t('common.cancel')}</Button><Button onClick={() => { setMetaOpen(false); void save(false) }}>{t('common.save')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('workflows.workflowName')}><Input value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} /></Field>
          <Field label={t('common.description')}><Textarea value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })} /></Field>
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

      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} title={t('common.confirmDelete')}
        description={selected?.name} onConfirm={remove} />
    </div>
  )
}

function defaultConfig(type: string): Record<string, unknown> {
  return ({
    form: { form_code: 'leave_request', assignee: '${initiator}' },
    condition: { field: 'days', operator: 'gt', value: 3 },
    approval: { approver_role: 'admin', mode: 'any' },
    ai: { prompt: 'Summarize this workflow context.' },
    knowledge: { query: 'policy', top_k: 3 },
    http: { method: 'POST', url: 'https://api.example.com/hook' },
    notification: { channel: 'in-app', template: 'Task completed' },
  } as Record<string, Record<string, unknown>>)[type] || {}
}

function NodeProperties({ node, operators, patch, patchConfig, remove }: {
  node: WfNode; operators: string[]
  patch: (id: string, p: Partial<WfNode>) => void
  patchConfig: (k: string, v: any) => void; remove: (id: string) => void
}) {
  const { t } = useI18n()
  const Icon = NODE_ICONS[node.type] || CircleDot
  const cfg: any = node.config || {}
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 rounded-lg border bg-muted/30 p-2">
        <Icon className="h-4 w-4 text-primary" /><span className="text-xs font-medium">{node.type}</span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">{node.id}</span>
      </div>
      <Field label={t('workflows.nodeName')}><Input value={node.name} onChange={(e) => patch(node.id, { name: e.target.value })} /></Field>
      {(node.type === 'form') && <Field label={t('workflows.formCode')}><Input value={cfg.form_code || ''} onChange={(e) => patchConfig('form_code', e.target.value)} /></Field>}
      {node.type === 'condition' && <>
        <Field label={t('workflows.conditionField')}><Input value={cfg.field || ''} onChange={(e) => patchConfig('field', e.target.value)} /></Field>
        <Field label={t('workflows.operator')}><Select value={cfg.operator || 'gt'} onValueChange={(v) => patchConfig('operator', v)}
          options={operators.map((o) => ({ value: o, label: o }))} /></Field>
        <Field label={t('workflows.conditionValue')}><Input value={String(cfg.value ?? '')} onChange={(e) => patchConfig('value', isNaN(Number(e.target.value)) ? e.target.value : Number(e.target.value))} /></Field>
      </>}
      {node.type === 'approval' && <Field label={t('workflows.approverRole')}><Input value={cfg.approver_role || ''} onChange={(e) => patchConfig('approver_role', e.target.value)} /></Field>}
      {node.type === 'ai' && <Field label={t('workflows.prompt')}><Textarea rows={3} value={cfg.prompt || ''} onChange={(e) => patchConfig('prompt', e.target.value)} /></Field>}
      {node.type === 'knowledge' && <Field label={t('workflows.query')}><Input value={cfg.query || ''} onChange={(e) => patchConfig('query', e.target.value)} /></Field>}
      {node.type === 'http' && <>
        <Field label={t('workflows.method')}><Select value={cfg.method || 'POST'} onValueChange={(v) => patchConfig('method', v)}
          options={['GET', 'POST', 'PUT', 'DELETE'].map((m) => ({ value: m, label: m }))} /></Field>
        <Field label={t('workflows.url')}><Input value={cfg.url || ''} onChange={(e) => patchConfig('url', e.target.value)} /></Field>
      </>}
      {node.type === 'notification' && <>
        <Field label={t('workflows.channel')}><Input value={cfg.channel || ''} onChange={(e) => patchConfig('channel', e.target.value)} /></Field>
        <Field label={t('workflows.template')}><Input value={cfg.template || ''} onChange={(e) => patchConfig('template', e.target.value)} /></Field>
      </>}
      <Button variant="outline" size="sm" className="w-full" onClick={() => remove(node.id)}><Trash2 className="h-3.5 w-3.5 text-destructive" />{t('workflows.deleteNode')}</Button>
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
