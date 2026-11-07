import { useEffect, useState } from 'react'
import {
  Activity, BarChart3, Braces, CheckCircle2, Copy, Download, Eye, FileCode2,
  FilePlus2, FileText, FolderOpen, Globe2, Layers, Package, Play, Plug, Plus,
  RefreshCw, Save, Terminal, Trash2, Wrench, XCircle,
} from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import {
  Badge, Button, Card, CardContent, Field, Input, Label, Select, Switch, Textarea,
} from '@/components/ui/basic'
import { ConfirmDialog, Dialog, Dropdown, Tabs, useToast } from '@/components/ui/overlay'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { api, del, get, post, put } from '@/lib/api'
import { copyText, downloadText, formatDate, safeParse, truncate } from '@/lib/utils'
import type { CallStats, CatalogSkill, McpCall, McpSkill, SkillFile, ToolSpec } from '@/types'

const fileUrl = (skillId: number, path: string) =>
  `/mcp/skills/${skillId}/files/${path.split('/').map(encodeURIComponent).join('/')}`

const jsonText = (value: unknown) => {
  try { return JSON.stringify(value ?? {}, null, 2) } catch { return String(value) }
}

export default function McpSkills() {
  const { t, locale } = useI18n()
  const { can } = useApp()
  const { toast } = useToast()
  const [tab, setTab] = useState('skills')
  const [tools, setTools] = useState<ToolSpec[]>([])
  const [permissions, setPermissions] = useState<Record<string, string>>({})
  const [skills, setSkills] = useState<McpSkill[]>([])
  const [catalog, setCatalog] = useState<CatalogSkill[]>([])
  const [status, setStatus] = useState<any>(null)
  const [calls, setCalls] = useState<McpCall[]>([])
  const [callTotal, setCallTotal] = useState(0)
  const [callStats, setCallStats] = useState<CallStats | null>(null)
  const [filters, setFilters] = useState({ tool: '', source: '', status: '', q: '' })
  const [callDetail, setCallDetail] = useState<McpCall | null>(null)

  const [skillOpen, setSkillOpen] = useState(false)
  const [invokeOpen, setInvokeOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)
  const [confirmUninstall, setConfirmUninstall] = useState<number | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  const [skillForm, setSkillForm] = useState<any>({})
  const [detail, setDetail] = useState<any>(null)
  const [filesSkill, setFilesSkill] = useState<McpSkill | null>(null)
  const [files, setFiles] = useState<SkillFile[]>([])
  const [diskPath, setDiskPath] = useState('')
  const [activeFile, setActiveFile] = useState('')
  const [fileContent, setFileContent] = useState('')
  const [fileDirty, setFileDirty] = useState(false)
  const [newFileOpen, setNewFileOpen] = useState(false)
  const [newFilePath, setNewFilePath] = useState('')
  const [invokeTool, setInvokeTool] = useState('get_stats')
  const [invokeArgs, setInvokeArgs] = useState('{}')
  const [invokeResult, setInvokeResult] = useState<any>(null)
  const [syncMessage, setSyncMessage] = useState('')

  const loadCalls = async () => {
    const qs = new URLSearchParams({ limit: '100' })
    if (filters.tool) qs.set('tool', filters.tool)
    if (filters.source) qs.set('source', filters.source)
    if (filters.status) qs.set('status', filters.status)
    if (filters.q) qs.set('q', filters.q)
    try {
      const [list, stats] = await Promise.all([
        get<{ calls: McpCall[]; total: number }>(`/mcp/calls?${qs.toString()}`),
        get<CallStats>('/mcp/calls/stats'),
      ])
      setCalls(list.calls || []); setCallTotal(list.total || 0); setCallStats(stats)
    } catch (e: any) { toast(e.message, 'error') }
  }

  const load = async () => {
    try {
      const [tl, sl, st, cat] = await Promise.all([
        get<{ tools: ToolSpec[]; permissions: Record<string, string> }>('/mcp/tools'),
        get<{ skills: McpSkill[] }>('/mcp/skills'),
        get<any>('/mcp/status'),
        get<{ catalog: CatalogSkill[] }>('/mcp/skills/catalog'),
      ])
      setTools(tl.tools || []); setPermissions(tl.permissions || {})
      setSkills(sl.skills || []); setStatus(st); setCatalog(cat.catalog || [])
      await loadCalls()
    } catch (e: any) { toast(e.message, 'error') }
  }
  useEffect(() => { void load() }, [])
  useEffect(() => { if (tab === 'journal') void loadCalls() },
    [filters.tool, filters.source, filters.status, filters.q])

  const statusLabel = (s: string) => s === 'installed' ? t('mcp.installed')
    : s === 'disabled' ? t('mcp.disabled')
      : s === 'uninstalled' ? t('mcp.uninstalled') : s

  const lifecycle = async (s: McpSkill, action: string) => {
    try {
      await post(`/mcp/skills/${s.id}/${action}`, {})
      await load(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const installFromCatalog = async (code: string) => {
    try { await post('/mcp/skills/install', { code }); await load(); toast(t('common.saved'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
  }
  const sync = async (id: number) => {
    try {
      const r: any = await post(`/mcp/skills/${id}/sync`, {})
      setSyncMessage(`${r.health}: ${r.message}`)
      toast(t('mcp.syncResult') + ': ' + r.health, r.health === 'healthy' ? 'success' : 'info')
      await load()
    } catch (e: any) { toast(e.message, 'error') }
  }
  const remove = async () => {
    if (!confirmDelete) return
    try { await del(`/mcp/skills/${confirmDelete}`); await load(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmDelete(null) }
  }
  const uninstall = async () => {
    if (!confirmUninstall) return
    try { await post(`/mcp/skills/${confirmUninstall}/uninstall`, {}); await load(); toast(t('common.saved'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmUninstall(null) }
  }
  const clearJournal = async () => {
    try { await del('/mcp/calls'); await loadCalls(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmClear(false) }
  }
  const exportJournal = async () => {
    try { const csv = await api<string>('/mcp/calls/export'); downloadText('mcp-call-journal.csv', csv, 'text/csv') }
    catch (e: any) { toast(e.message, 'error') }
  }
  const saveSkill = async () => {
    const payload: any = {
      code: skillForm.code, name: skillForm.name, type: skillForm.type,
      endpoint: skillForm.endpoint || null, command: skillForm.command || null,
      enabled: skillForm.enabled, auth_config: skillForm.auth_config || {},
      description: skillForm.description || '', version: skillForm.version || '1.0.0',
    }
    try {
      if (skillForm.id) await put(`/mcp/skills/${skillForm.id}`, payload)
      else await post('/mcp/skills', payload)
      setSkillOpen(false); await load(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const openSkill = (s?: McpSkill) => {
    setSkillForm(s ? {
      id: s.id, code: s.code, name: s.name, type: s.type, endpoint: s.endpoint || '',
      command: s.command || '', enabled: s.enabled, auth_config: s.auth_config || {},
      description: s.description || '', version: s.version || '1.0.0',
    } : { id: 0, code: '', name: '', type: 'http', endpoint: '', command: '', enabled: true,
      auth_config: {}, description: '', version: '1.0.0' })
    setSkillOpen(true)
  }
  const openDetail = async (s: McpSkill) => {
    try { setDetail(await get(`/mcp/skills/${s.id}`)) } catch (e: any) { toast(e.message, 'error') }
  }
  const selectFile = async (skillId: number, path: string) => {
    try {
      const f = await get<SkillFile>(fileUrl(skillId, path))
      setActiveFile(path); setFileContent(f.content || ''); setFileDirty(false)
    } catch (e: any) { toast(e.message, 'error') }
  }
  const openFiles = async (s: McpSkill) => {
    try {
      const d = await get<{ files: SkillFile[]; disk_path: string }>(`/mcp/skills/${s.id}/files`)
      setFilesSkill(s); setFiles(d.files || []); setDiskPath(d.disk_path || '')
      if (d.files?.length) await selectFile(s.id, d.files[0].path)
      else { setActiveFile(''); setFileContent('') }
    } catch (e: any) { toast(e.message, 'error') }
  }
  const saveFile = async () => {
    if (!filesSkill || !activeFile) return
    try {
      await put(fileUrl(filesSkill.id, activeFile), { content: fileContent })
      setFileDirty(false); toast(t('mcp.fileSaved'), 'success'); await openFiles(filesSkill)
    } catch (e: any) { toast(e.message, 'error') }
  }
  const createFile = async () => {
    if (!filesSkill || !newFilePath.trim()) return
    try {
      await put(fileUrl(filesSkill.id, newFilePath.trim()), { content: '' })
      setNewFileOpen(false); setNewFilePath(''); await openFiles(filesSkill)
      await selectFile(filesSkill.id, newFilePath.trim())
      toast(t('mcp.fileSaved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const removeFile = async () => {
    if (!filesSkill || !activeFile) return
    try {
      await del(fileUrl(filesSkill.id, activeFile))
      toast(t('mcp.fileDeleted'), 'success'); await openFiles(filesSkill)
    } catch (e: any) { toast(e.message, 'error') }
  }
  const reloadFiles = async () => {
    if (!filesSkill) return
    try { await post(`/mcp/skills/${filesSkill.id}/files/reload`, {}); await openFiles(filesSkill) }
    catch (e: any) { toast(e.message, 'error') }
  }
  const invoke = async () => {
    try {
      const r: any = await post('/mcp/invoke', { tool: invokeTool, arguments: safeParse(invokeArgs, {}) })
      setInvokeResult(r.result); void loadCalls()
    } catch (e: any) { setInvokeResult({ error: e.message }); toast(e.message, 'error') }
  }

  const maxTool = Math.max(1, ...(callStats?.by_tool || []).map((x) => x.count))
  const maxDay = Math.max(1, ...(callStats?.timeline || []).map((x) => x.count))

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader icon={<Plug className="h-5 w-5" />} title={t('mcp.title')} subtitle={t('mcp.subtitle')}
        actions={<>
          <Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>
          {can('mcp:invoke') && <Button variant="outline" size="sm" onClick={() => { setInvokeResult(null); setInvokeOpen(true) }}><Play className="h-3.5 w-3.5" />{t('mcp.invoke')}</Button>}
          {can('mcp:write') && <Button size="sm" onClick={() => setTab('catalog')}><Package className="h-4 w-4" />{t('mcp.installSkill')}</Button>}
          {can('mcp:write') && <Button size="sm" variant="outline" onClick={() => openSkill()}><Plus className="h-4 w-4" />{t('mcp.newSkill')}</Button>}
        </>} />

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: t('mcp.status'), value: status?.enabled ? t('common.enabled') : t('common.disabled'), icon: <Activity className="h-4 w-4" /> },
          { label: t('mcp.transport'), value: status?.transport || 'streamable-http', icon: <Globe2 className="h-4 w-4" /> },
          { label: t('mcp.toolCount'), value: status?.tool_count ?? tools.length, icon: <Wrench className="h-4 w-4" /> },
          { label: t('mcp.totalCalls'), value: callStats?.total ?? 0, icon: <BarChart3 className="h-4 w-4" /> },
        ].map((s, i) => <Card key={i} className="p-3"><div className="flex items-center gap-2 text-primary">{s.icon}
          <span className="mono-num text-sm font-semibold text-foreground">{s.value}</span></div>
          <p className="mt-1 text-[11px] text-muted-foreground">{s.label}</p></Card>)}
      </div>

      <Tabs value={tab} onValueChange={setTab} className="mb-4" items={[
        { value: 'skills', label: t('mcp.registered'), icon: <Plug className="h-3 w-3" />, count: skills.length },
        { value: 'catalog', label: t('mcp.catalog'), icon: <Package className="h-3 w-3" />, count: catalog.length },
        { value: 'tools', label: t('mcp.platformTools'), icon: <Braces className="h-3 w-3" />, count: tools.length },
        { value: 'journal', label: t('mcp.journal'), icon: <Activity className="h-3 w-3" />, count: callTotal },
      ]} />

      {/* ---------------- Skills ---------------- */}
      {tab === 'skills' && <>
        <p className="mb-3 text-xs text-muted-foreground">{t('mcp.installHint')}</p>
        {syncMessage && <div className="mb-3 rounded-lg border bg-muted/40 px-3 py-2 font-mono text-[11px]">{syncMessage}</div>}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {skills.map((s) => (
            <Card key={s.id} className="card-hover">
              <CardContent className="p-4">
                <div className="flex items-start gap-2">
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    {s.type === 'builtin' ? <Braces className="h-4 w-4" /> : s.type === 'stdio' ? <Terminal className="h-4 w-4" /> : <Globe2 className="h-4 w-4" />}
                  </span>
                  <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{s.name}</p>
                    <p className="truncate font-mono text-[10px] text-muted-foreground">{s.code} · {s.type} · v{s.version || '1.0.0'}</p></div>
                  <Switch checked={s.enabled && s.status === 'installed'}
                    onCheckedChange={(v) => void lifecycle(s, v ? 'enable' : 'disable')}
                    disabled={!can('mcp:write') || s.status === 'uninstalled'} />
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  <Badge variant={s.status === 'installed' ? 'success' : s.status === 'disabled' ? 'muted' : 'outline'}>
                    {s.status === 'installed' ? <CheckCircle2 className="h-2.5 w-2.5" /> : <XCircle className="h-2.5 w-2.5" />}{statusLabel(s.status)}
                  </Badge>
                  <Badge variant={s.health === 'healthy' ? 'success' : s.health === 'unreachable' ? 'destructive' : 'muted'}>{s.health}</Badge>
                  <Badge variant="outline"><FileCode2 className="h-2.5 w-2.5" />{t('mcp.fileCount', { count: s.file_count ?? 0 })}</Badge>
                  <Badge variant="outline">{t('mcp.tools')}: {s.tools?.length ?? 0}</Badge>
                </div>
                <p className="mt-2 truncate font-mono text-[10px] text-muted-foreground">{s.endpoint || s.command || '—'}</p>
                {s.description && <p className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">{s.description}</p>}
                <div className="mt-3 flex items-center gap-1.5 border-t pt-3">
                  <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => void openDetail(s)}><Eye className="h-3 w-3" />{t('mcp.viewDetail')}</Button>
                  <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => void openFiles(s)}><FolderOpen className="h-3 w-3" />{t('mcp.files')}</Button>
                  <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => void sync(s.id)} disabled={!can('mcp:write') || s.status === 'uninstalled'}><RefreshCw className="h-3 w-3" />{t('mcp.syncNow')}</Button>
                  {can('mcp:write') && <div className="ml-auto"><Dropdown trigger={<Button variant="ghost" size="sm" className="h-7 text-xs">···</Button>} items={[
                    { label: t('common.edit'), icon: <FileText className="h-3 w-3" />, onClick: () => openSkill(s) },
                    ...(s.status === 'installed' || s.status === 'disabled'
                      ? [{ label: t('mcp.uninstall'), icon: <Trash2 className="h-3 w-3" />, destructive: true, onClick: () => setConfirmUninstall(s.id) }]
                      : [{ label: t('mcp.reinstall'), icon: <RefreshCw className="h-3 w-3" />, onClick: () => void lifecycle(s, 'reinstall') }]),
                    { label: t('common.delete'), icon: <Trash2 className="h-3 w-3" />, destructive: true, separator: true, onClick: () => setConfirmDelete(s.id) },
                  ]} /></div>}
                </div>
                {s.last_sync_at && <p className="mt-1.5 text-[9px] text-muted-foreground">{formatDate(s.last_sync_at, locale)}</p>}
              </CardContent>
            </Card>
          ))}
          {!skills.length && <Card className="p-8 text-center text-sm text-muted-foreground md:col-span-2 xl:col-span-3">{t('mcp.emptySkills')}</Card>}
        </div>
      </>}

      {/* ---------------- Catalog ---------------- */}
      {tab === 'catalog' && <>
        <p className="mb-3 text-xs text-muted-foreground">{t('mcp.catalogHint')}</p>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {catalog.map((item) => (
            <Card key={item.code} className="card-hover"><CardContent className="p-4">
              <div className="flex items-start gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary"><Package className="h-4 w-4" /></span>
                <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{item.name}</p>
                  <p className="font-mono text-[10px] text-muted-foreground">{item.code} · {item.type} · v{item.version}</p></div>
                <Badge variant={item.installed ? 'success' : 'outline'}>{item.installed ? t('mcp.installed') : t('mcp.available')}</Badge>
              </div>
              <p className="mt-2 min-h-[2rem] text-[11px] text-muted-foreground">{item.description}</p>
              <div className="mt-2 flex flex-wrap gap-1">{item.capabilities.map((c) => <Badge key={c} variant="secondary" className="font-mono text-[9px]">{c}</Badge>)}</div>
              <div className="mt-2 flex flex-wrap gap-1 text-[10px] text-muted-foreground">
                <span>{t('mcp.tools')}: {item.tool_count}</span><span>·</span><span>{t('mcp.fileCount', { count: item.file_count })}</span>
              </div>
              <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground">{item.endpoint || item.command}</p>
              <div className="mt-3 border-t pt-3">
                <Button size="sm" className="h-7 text-xs" disabled={!can('mcp:write') || item.installed}
                  onClick={() => void installFromCatalog(item.code)}><Download className="h-3 w-3" />{t('mcp.install')}</Button>
              </div>
            </CardContent></Card>
          ))}
        </div>
      </>}

      {/* ---------------- Platform tools ---------------- */}
      {tab === 'tools' && <Card>
        <CardContent className="p-0">
          <div className="border-b px-4 py-3 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5 font-medium text-foreground"><Terminal className="h-3.5 w-3.5" />/mcp</span>
            {' · '}{t('mcp.builtinHint')}
          </div>
          <Table><TableHeader><TableRow>
            <TableHead>{t('common.name')}</TableHead><TableHead>{t('common.description')}</TableHead>
            <TableHead>{t('mcp.inputSchema')}</TableHead><TableHead>{t('mcp.permissions')}</TableHead><TableHead>{t('common.actions')}</TableHead>
          </TableRow></TableHeader><TableBody>
            {tools.map((tool) => <TableRow key={tool.name}>
              <TableCell className="font-mono text-xs font-medium text-primary">{tool.name}</TableCell>
              <TableCell className="max-w-xs text-xs text-muted-foreground">{tool.description}</TableCell>
              <TableCell><div className="flex max-w-[16rem] flex-wrap gap-1">
                {(tool.inputSchema?.required || []).map((r) => <Badge key={r} variant="outline" className="font-mono text-[9px]">{r}*</Badge>)}
                {Object.keys(tool.inputSchema?.properties || {}).filter((k) => !(tool.inputSchema?.required || []).includes(k))
                  .map((k) => <Badge key={k} variant="muted" className="font-mono text-[9px]">{k}</Badge>)}
              </div></TableCell>
              <TableCell className="font-mono text-[10px] text-muted-foreground">{permissions[tool.name] || '—'}</TableCell>
              <TableCell><Button variant="ghost" size="sm" className="h-7 text-xs" disabled={!can('mcp:invoke')}
                onClick={() => { setInvokeTool(tool.name); setInvokeArgs('{}'); setInvokeResult(null); setInvokeOpen(true) }}>
                <Play className="h-3 w-3" />{t('mcp.invoke')}</Button></TableCell>
            </TableRow>)}
          </TableBody></Table>
        </CardContent>
      </Card>}

      {/* ---------------- Call journal ---------------- */}
      {tab === 'journal' && <>
        <p className="mb-3 text-xs text-muted-foreground">{t('mcp.journalHint')}</p>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: t('mcp.totalCalls'), value: callStats?.total ?? 0, icon: <Activity className="h-4 w-4" /> },
            { label: t('mcp.successRate'), value: `${callStats?.success_rate ?? 100}%`, icon: <CheckCircle2 className="h-4 w-4" /> },
            { label: t('mcp.avgDuration'), value: `${callStats?.avg_duration_ms ?? 0} ms`, icon: <Wrench className="h-4 w-4" /> },
            { label: t('mcp.todayCalls'), value: callStats?.today ?? 0, icon: <BarChart3 className="h-4 w-4" /> },
          ].map((s, i) => <Card key={i} className="p-3"><div className="flex items-center gap-2 text-primary">{s.icon}
            <span className="mono-num text-sm font-semibold text-foreground">{s.value}</span></div>
            <p className="mt-1 text-[11px] text-muted-foreground">{s.label}</p></Card>)}
        </div>

        <div className="mb-4 grid gap-3 lg:grid-cols-3">
          <Card className="p-4 lg:col-span-2"><h3 className="mb-3 text-xs font-semibold">{t('mcp.byTool')}</h3>
            <div className="space-y-2">{(callStats?.by_tool || []).slice(0, 8).map((x) => (
              <div key={x.name} className="flex items-center gap-2">
                <span className="w-32 shrink-0 truncate font-mono text-[10px] text-muted-foreground">{x.name}</span>
                <div className="h-2 flex-1 rounded-full bg-muted"><div className="h-2 rounded-full bg-primary/80" style={{ width: `${(x.count / maxTool) * 100}%` }} /></div>
                <span className="mono-num w-8 text-right text-[10px]">{x.count}</span>
              </div>))}
              {!callStats?.by_tool?.length && <p className="text-xs text-muted-foreground">{t('mcp.noCalls')}</p>}
            </div>
          </Card>
          <Card className="p-4"><h3 className="mb-3 text-xs font-semibold">{t('mcp.timeline')}</h3>
            <div className="flex h-24 items-end gap-1">{(callStats?.timeline || []).map((d) => (
              <div key={d.day} className="flex flex-1 flex-col items-center gap-1" title={`${d.day}: ${d.count}`}>
                <div className="w-full rounded-t bg-primary/70" style={{ height: `${Math.max(3, (d.count / maxDay) * 72)}px` }} />
                <span className="font-mono text-[8px] text-muted-foreground">{d.day.slice(5)}</span>
              </div>))}
              {!callStats?.timeline?.length && <p className="text-xs text-muted-foreground">{t('mcp.noCalls')}</p>}
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">{(callStats?.by_source || []).map((x) => (
              <Badge key={x.source} variant="outline" className="font-mono text-[9px]">{x.source}: {x.count}</Badge>))}
            </div>
          </Card>
        </div>

        <Card><CardContent className="p-0">
          <div className="flex flex-wrap items-center gap-2 border-b p-3">
            <Input className="h-8 w-52 text-xs" placeholder={t('mcp.searchCalls')} value={filters.q}
              onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
            <Select className="w-36" value={filters.tool} onValueChange={(v) => setFilters({ ...filters, tool: v })}
              options={[{ value: '', label: t('mcp.allTools') }, ...(callStats?.tools || []).map((x) => ({ value: x, label: x }))]} />
            <Select className="w-32" value={filters.source} onValueChange={(v) => setFilters({ ...filters, source: v })}
              options={[{ value: '', label: t('mcp.allSources') }, ...(callStats?.sources || []).map((x) => ({ value: x, label: x }))]} />
            <Select className="w-32" value={filters.status} onValueChange={(v) => setFilters({ ...filters, status: v })}
              options={[{ value: '', label: t('mcp.allStatuses') }, ...(callStats?.statuses || []).map((x) => ({ value: x, label: x }))]} />
            <div className="ml-auto flex gap-1.5">
              <Button variant="outline" size="sm" className="h-8 text-xs" onClick={() => void loadCalls()}><RefreshCw className="h-3 w-3" /></Button>
              <Button variant="outline" size="sm" className="h-8 text-xs" onClick={() => void exportJournal()}><Download className="h-3 w-3" />{t('mcp.exportJournal')}</Button>
              {can('mcp:write') && <Button variant="outline" size="sm" className="h-8 text-xs" onClick={() => setConfirmClear(true)}><Trash2 className="h-3 w-3" />{t('mcp.clearJournal')}</Button>}
            </div>
          </div>
          <Table><TableHeader><TableRow>
            <TableHead>{t('common.created')}</TableHead><TableHead>{t('mcp.source')}</TableHead>
            <TableHead>{t('mcp.method')} / {t('mcp.tools')}</TableHead><TableHead>{t('common.status')}</TableHead>
            <TableHead>{t('mcp.duration')}</TableHead><TableHead>{t('mcp.actor')}</TableHead><TableHead>{t('common.actions')}</TableHead>
          </TableRow></TableHeader><TableBody>
            {calls.map((c) => <TableRow key={c.id}>
              <TableCell className="whitespace-nowrap text-[11px] text-muted-foreground">{formatDate(c.created_at, locale)}</TableCell>
              <TableCell><Badge variant="outline" className="font-mono text-[9px]">{c.source}</Badge></TableCell>
              <TableCell><div className="font-mono text-[11px] text-primary">{c.tool || c.method}</div>
                <div className="font-mono text-[9px] text-muted-foreground">{truncate(jsonText(c.arguments), 60)}</div></TableCell>
              <TableCell><Badge variant={c.status === 'success' ? 'success' : 'destructive'}>
                {c.status === 'success' ? t('mcp.statusSuccess') : t('mcp.statusError')}</Badge></TableCell>
              <TableCell className="mono-num text-[11px]">{c.duration_ms} ms</TableCell>
              <TableCell className="text-[11px] text-muted-foreground">{c.actor || '—'}</TableCell>
              <TableCell><Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setCallDetail(c)}><Eye className="h-3 w-3" />{t('mcp.viewDetail')}</Button></TableCell>
            </TableRow>)}
          </TableBody></Table>
          {!calls.length && <div className="p-8 text-center text-sm text-muted-foreground">{t('mcp.noCalls')}</div>}
        </CardContent></Card>
      </>}

      {/* ---------------- Dialogs ---------------- */}
      <Dialog open={skillOpen} onOpenChange={setSkillOpen} title={skillForm.id ? t('mcp.editTitle') : t('mcp.createTitle')}
        footer={<><Button variant="outline" onClick={() => setSkillOpen(false)}>{t('common.cancel')}</Button><Button onClick={saveSkill}>{t('common.save')}</Button></>}>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('mcp.skillCode')}><Input value={skillForm.code} disabled={!!skillForm.id} onChange={(e) => setSkillForm({ ...skillForm, code: e.target.value })} placeholder="my_mcp" /></Field>
            <Field label={t('mcp.skillName')}><Input value={skillForm.name} onChange={(e) => setSkillForm({ ...skillForm, name: e.target.value })} /></Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('mcp.skillType')}><Select value={skillForm.type} onValueChange={(v) => setSkillForm({ ...skillForm, type: v })}
              options={['builtin', 'http', 'sse', 'stdio'].map((x) => ({ value: x, label: x }))} /></Field>
            <Field label={t('common.version')}><Input value={skillForm.version} onChange={(e) => setSkillForm({ ...skillForm, version: e.target.value })} /></Field>
          </div>
          <Field label={t('common.description')}><Input value={skillForm.description} onChange={(e) => setSkillForm({ ...skillForm, description: e.target.value })} /></Field>
          {skillForm.type !== 'stdio' && <Field label={t('mcp.endpoint')}><Input value={skillForm.endpoint} onChange={(e) => setSkillForm({ ...skillForm, endpoint: e.target.value })} placeholder="http://127.0.0.1:9100/mcp" /></Field>}
          {skillForm.type === 'stdio' && <Field label={t('mcp.command')}><Input value={skillForm.command} onChange={(e) => setSkillForm({ ...skillForm, command: e.target.value })} placeholder="npx -y @modelcontextprotocol/server-filesystem ./data" /></Field>}
          <Field label={t('mcp.authToken')}><Input value={skillForm.auth_config?.token || ''} onChange={(e) => setSkillForm({ ...skillForm, auth_config: { ...skillForm.auth_config, token: e.target.value } })} /></Field>
          <div className="flex items-center justify-between rounded-lg border px-3 py-2"><span className="text-xs">{t('common.enabled')}</span>
            <Switch checked={skillForm.enabled} onCheckedChange={(v) => setSkillForm({ ...skillForm, enabled: v })} /></div>
        </div>
      </Dialog>

      <Dialog open={!!detail} onOpenChange={() => setDetail(null)} title={t('mcp.skillDetail')} size="lg"
        footer={<Button variant="outline" onClick={() => setDetail(null)}>{t('common.close')}</Button>}>
        {detail && <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 text-xs">
            {[
              [t('common.code'), detail.code], [t('common.name'), detail.name],
              [t('common.type'), detail.type], [t('common.version'), detail.version],
              [t('mcp.skillStatus'), statusLabel(detail.status)], [t('mcp.source'), detail.source],
              [t('mcp.health'), detail.health], [t('mcp.installedAt'), formatDate(detail.installed_at, locale)],
            ].map(([k, v]) => <div key={String(k)} className="rounded-lg border px-3 py-2"><p className="text-[10px] text-muted-foreground">{k}</p><p className="mt-0.5 truncate font-medium">{String(v ?? '—')}</p></div>)}
          </div>
          <div><h3 className="mb-1.5 text-xs font-semibold">{t('mcp.manifest')}</h3>
            <pre className="scroll-thin max-h-40 overflow-auto rounded-lg border bg-muted/30 p-3 font-mono text-[10px]">{jsonText(detail.manifest)}</pre></div>
          <div><h3 className="mb-1.5 text-xs font-semibold">{t('mcp.declaredTools')} ({detail.tools?.length || 0})</h3>
            <div className="flex flex-wrap gap-1">{(detail.tools || []).map((x: any) => <Badge key={x.name} variant="secondary" className="font-mono text-[9px]">{x.name}</Badge>)}
              {!detail.tools?.length && <span className="text-xs text-muted-foreground">—</span>}</div></div>
          <div><h3 className="mb-1.5 text-xs font-semibold">{t('mcp.files')} ({detail.files?.length || 0})</h3>
            <div className="flex flex-wrap gap-1">{(detail.files || []).map((f: SkillFile) => <Badge key={f.path} variant="outline" className="font-mono text-[9px]">{f.path} · {f.size}B</Badge>)}</div></div>
        </div>}
      </Dialog>

      <Dialog open={!!filesSkill} onOpenChange={() => setFilesSkill(null)} title={`${t('mcp.fileManager')} · ${filesSkill?.code || ''}`} size="full"
        footer={<><Button variant="outline" onClick={() => setFilesSkill(null)}>{t('common.close')}</Button>
          <Button onClick={saveFile} disabled={!activeFile || !can('mcp:write')}><Save className="h-3.5 w-3.5" />{t('mcp.saveFile')}{fileDirty ? ' *' : ''}</Button></>}>
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2 text-[10px] text-muted-foreground">
            <FolderOpen className="h-3.5 w-3.5" /><span className="font-mono">{t('mcp.diskPath')}: {diskPath}</span>
            <div className="ml-auto flex gap-1.5">
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setNewFileOpen(true)} disabled={!can('mcp:write')}><FilePlus2 className="h-3 w-3" />{t('mcp.newFile')}</Button>
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => void reloadFiles()} disabled={!can('mcp:write')}><RefreshCw className="h-3 w-3" />{t('mcp.reloadFiles')}</Button>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-[16rem_1fr]">
            <div className="scroll-thin max-h-[26rem] space-y-1 overflow-y-auto rounded-lg border p-2">
              {files.map((f) => <button key={f.path} onClick={() => void selectFile(filesSkill!.id, f.path)}
                className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[11px] transition-colors ${activeFile === f.path ? 'bg-primary/10 text-primary' : 'hover:bg-accent'}`}>
                <FileCode2 className="h-3 w-3 shrink-0" /><span className="min-w-0 flex-1 truncate font-mono">{f.path}</span>
                <span className="text-[9px] text-muted-foreground">{f.size}B</span></button>)}
              {!files.length && <p className="p-3 text-center text-xs text-muted-foreground">{t('mcp.noCalls')}</p>}
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between"><Label className="font-mono text-xs">{activeFile || t('mcp.fileContent')}</Label>
                {activeFile && <div className="flex gap-1"><Badge variant="outline" className="text-[9px]">{files.find((f) => f.path === activeFile)?.language}</Badge>
                  {can('mcp:write') && <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => void removeFile()}><Trash2 className="h-3 w-3 text-destructive" /></Button>}</div>}</div>
              <Textarea rows={18} className="font-mono text-xs" value={fileContent} disabled={!activeFile}
                onChange={(e) => { setFileContent(e.target.value); setFileDirty(true) }} />
              <p className="text-[10px] text-muted-foreground">{t('mcp.fileContent')} · {fileContent.length} chars</p>
            </div>
          </div>
        </div>
      </Dialog>

      <Dialog open={newFileOpen} onOpenChange={setNewFileOpen} title={t('mcp.newFile')} size="sm"
        footer={<><Button variant="outline" onClick={() => setNewFileOpen(false)}>{t('common.cancel')}</Button><Button onClick={createFile}>{t('common.create')}</Button></>}>
        <Field label={t('mcp.fileName')}><Input value={newFilePath} onChange={(e) => setNewFilePath(e.target.value)} placeholder="notes/readme.md" /></Field>
      </Dialog>

      <Dialog open={invokeOpen} onOpenChange={setInvokeOpen} title={t('mcp.invoke')} size="lg"
        footer={<><Button variant="outline" onClick={() => setInvokeOpen(false)}>{t('common.close')}</Button><Button onClick={invoke}><Play className="h-3.5 w-3.5" />{t('mcp.invokeNow')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('mcp.tools')}><Select value={invokeTool} onValueChange={setInvokeTool}
            options={tools.map((x) => ({ value: x.name, label: x.name }))} /></Field>
          <Field label={t('mcp.arguments')}><Textarea rows={5} className="font-mono text-xs" value={invokeArgs} onChange={(e) => setInvokeArgs(e.target.value)} /></Field>
          {invokeResult !== null && <div className="space-y-1.5">
            <div className="flex items-center justify-between"><Label>{t('mcp.result')}</Label>
              <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => void copyText(jsonText(invokeResult))}><Copy className="h-3 w-3" />{t('common.copy')}</Button></div>
            <pre className="scroll-thin max-h-64 overflow-auto rounded-lg border bg-muted/30 p-3 font-mono text-[11px]">{jsonText(invokeResult)}</pre>
          </div>}
        </div>
      </Dialog>

      <Dialog open={!!callDetail} onOpenChange={() => setCallDetail(null)} title={t('mcp.callDetail')} size="lg"
        footer={<Button variant="outline" onClick={() => setCallDetail(null)}>{t('common.close')}</Button>}>
        {callDetail && <div className="space-y-3 text-xs">
          <div className="grid grid-cols-2 gap-2">
            {[[t('mcp.method'), callDetail.method], [t('mcp.tools'), callDetail.tool || '—'],
              [t('mcp.source'), callDetail.source], [t('mcp.actor'), callDetail.actor || '—'],
              [t('common.status'), callDetail.status], [t('mcp.duration'), `${callDetail.duration_ms} ms`],
              [t('common.created'), formatDate(callDetail.created_at, locale)], [t('mcp.transport'), callDetail.transport || '—'],
            ].map(([k, v]) => <div key={String(k)} className="rounded-lg border px-3 py-2"><p className="text-[10px] text-muted-foreground">{k}</p><p className="mt-0.5 font-mono">{String(v)}</p></div>)}
          </div>
          <div><Label>{t('mcp.arguments')}</Label><pre className="mt-1 max-h-40 overflow-auto rounded-lg border bg-muted/30 p-3 font-mono text-[10px]">{jsonText(callDetail.arguments)}</pre></div>
          {callDetail.error && <div><Label>{t('mcp.statusError')}</Label><pre className="mt-1 rounded-lg border border-destructive/30 bg-destructive/5 p-3 font-mono text-[10px] text-destructive">{callDetail.error}</pre></div>}
          <div><Label>{t('mcp.result')}</Label><pre className="mt-1 max-h-52 overflow-auto rounded-lg border bg-muted/30 p-3 font-mono text-[10px]">{jsonText(callDetail.result)}</pre></div>
        </div>}
      </Dialog>

      <ConfirmDialog open={confirmDelete !== null} onOpenChange={() => setConfirmDelete(null)} title={t('common.confirmDelete')} onConfirm={remove} />
      <ConfirmDialog open={confirmUninstall !== null} onOpenChange={() => setConfirmUninstall(null)}
        title={t('mcp.uninstall')} description={t('mcp.confirmUninstall')} onConfirm={uninstall} />
      <ConfirmDialog open={confirmClear} onOpenChange={() => setConfirmClear(false)}
        title={t('mcp.clearJournal')} description={t('mcp.confirmClearJournal')} onConfirm={clearJournal} />
    </div>
  )
}
