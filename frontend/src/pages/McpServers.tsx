import { useEffect, useState } from 'react'
import {
  Activity, BarChart3, Braces, CheckCircle2, Copy, Download, Eye, Globe2,
  Plus, RefreshCw, Save, Server, Terminal, Trash2, Wrench, XCircle, Play,
} from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { Badge, Button, Card, CardContent, Field, Input, Label, Select, Switch, Textarea } from '@/components/ui/basic'
import { ConfirmDialog, Dialog, Tabs, useToast } from '@/components/ui/overlay'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { api, del, get, post, put } from '@/lib/api'
import { copyText, downloadText, formatDate, safeParse, truncate } from '@/lib/utils'
import type { CallStats, McpCall, McpServer, McpServerStats, ToolSpec } from '@/types'

const jsonText = (value: unknown) => {
  try { return JSON.stringify(value ?? {}, null, 2) } catch { return String(value) }
}

export default function McpServers() {
  const { t, locale } = useI18n()
  const { can } = useApp()
  const { toast } = useToast()
  const [tab, setTab] = useState('servers')
  const [servers, setServers] = useState<McpServer[]>([])
  const [serverStats, setServerStats] = useState<McpServerStats | null>(null)
  const [tools, setTools] = useState<ToolSpec[]>([])
  const [permissions, setPermissions] = useState<Record<string, string>>({})
  const [status, setStatus] = useState<any>(null)
  const [calls, setCalls] = useState<McpCall[]>([])
  const [callTotal, setCallTotal] = useState(0)
  const [callStats, setCallStats] = useState<CallStats | null>(null)
  const [filters, setFilters] = useState({ tool: '', source: '', status: '', q: '' })
  const [callDetail, setCallDetail] = useState<McpCall | null>(null)

  const [serverOpen, setServerOpen] = useState(false)
  const [serverForm, setServerForm] = useState<any>({})
  const [detail, setDetail] = useState<any>(null)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  const [invokeOpen, setInvokeOpen] = useState(false)
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
      const [srv, tl, st] = await Promise.all([
        get<{ servers: McpServer[]; stats: McpServerStats; transports: string[] }>('/mcp/servers'),
        get<{ tools: ToolSpec[]; permissions: Record<string, string>; builtin_tools: number }>('/mcp/tools'),
        get<any>('/mcp/status'),
      ])
      setServers(srv.servers || []); setServerStats(srv.stats || null)
      setTools(tl.tools || []); setPermissions(tl.permissions || {}); setStatus(st)
      await loadCalls()
    } catch (e: any) { toast(e.message, 'error') }
  }
  useEffect(() => { void load() }, [])
  useEffect(() => { if (tab === 'journal') void loadCalls() },
    [filters.tool, filters.source, filters.status, filters.q, tab])

  const openForm = (s?: McpServer) => {
    setServerForm(s ? {
      id: s.id, code: s.code, name: s.name, description: s.description || '',
      transport: s.transport, endpoint: s.endpoint || '', command: s.command || '',
      enabled: s.enabled, auth_token: (s.auth_config as any)?.token || '',
      tools: jsonText(s.tools || []),
    } : { id: 0, code: '', name: '', description: '', transport: 'http', endpoint: '',
      command: '', enabled: true, auth_token: '', tools: '[]' })
    setServerOpen(true)
  }

  const saveServer = async () => {
    let tools: any[] = []
    try { tools = safeParse(serverForm.tools, []) } catch { tools = [] }
    if (!Array.isArray(tools)) tools = []
    const payload: any = {
      code: serverForm.code, name: serverForm.name, description: serverForm.description,
      transport: serverForm.transport, endpoint: serverForm.endpoint || null,
      command: serverForm.command || null, enabled: serverForm.enabled,
      auth_config: { token: serverForm.auth_token || '' }, tools,
    }
    if (serverForm.id) delete payload.code
    try {
      if (serverForm.id) await put(`/mcp/servers/${serverForm.id}`, payload)
      else await post('/mcp/servers', payload)
      setServerOpen(false); await load(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }

  const toggle = async (s: McpServer) => {
    try {
      await post(`/mcp/servers/${s.id}/${s.enabled ? 'disable' : 'enable'}`, {})
      await load(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const sync = async (s: McpServer) => {
    try {
      const r: any = await post(`/mcp/servers/${s.id}/sync`, {})
      setSyncMessage(`${s.code}: ${r.health} — ${r.message}`)
      toast(t('mcp.syncResult') + ': ' + r.health, r.health === 'healthy' ? 'success' : 'info')
      await load()
    } catch (e: any) { toast(e.message, 'error') }
  }
  const remove = async () => {
    if (!confirmDelete) return
    try { await del(`/mcp/servers/${confirmDelete}`); await load(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmDelete(null) }
  }
  const openDetail = async (s: McpServer) => {
    try { setDetail(await get(`/mcp/servers/${s.id}`)) } catch (e: any) { toast(e.message, 'error') }
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
      <PageHeader icon={<Server className="h-5 w-5" />} title={t('mcpServers.title')} subtitle={t('mcpServers.subtitle')}
        actions={<>
          <Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>
          {can('mcp:invoke') && <Button variant="outline" size="sm" onClick={() => { setInvokeResult(null); setInvokeOpen(true) }}><Play className="h-3.5 w-3.5" />{t('mcp.invoke')}</Button>}
          {can('mcp:write') && <Button size="sm" onClick={() => openForm()}><Plus className="h-4 w-4" />{t('mcpServers.newServer')}</Button>}
        </>} />

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: t('mcpServers.totalServers'), value: serverStats?.total ?? 0, icon: <Server className="h-4 w-4" /> },
          { label: t('mcpServers.enabledServers'), value: serverStats?.enabled ?? 0, icon: <CheckCircle2 className="h-4 w-4" /> },
          { label: t('mcp.toolCount'), value: status?.tool_count ?? tools.length, icon: <Wrench className="h-4 w-4" /> },
          { label: t('mcp.totalCalls'), value: callStats?.total ?? 0, icon: <BarChart3 className="h-4 w-4" /> },
        ].map((s, i) => <Card key={i} className="p-3"><div className="flex items-center gap-2 text-primary">{s.icon}
          <span className="mono-num text-sm font-semibold text-foreground">{s.value}</span></div>
          <p className="mt-1 text-[11px] text-muted-foreground">{s.label}</p></Card>)}
      </div>

      <Tabs value={tab} onValueChange={setTab} className="mb-4" items={[
        { value: 'servers', label: t('mcpServers.registered'), icon: <Server className="h-3 w-3" />, count: servers.length },
        { value: 'tools', label: t('mcp.platformTools'), icon: <Braces className="h-3 w-3" />, count: tools.length },
        { value: 'journal', label: t('mcp.journal'), icon: <Activity className="h-3 w-3" />, count: callTotal },
      ]} />

      {tab === 'servers' && <>
        <p className="mb-3 text-xs text-muted-foreground">{t('mcpServers.hint')}</p>
        {syncMessage && <div className="mb-3 rounded-lg border bg-muted/40 px-3 py-2 font-mono text-[11px]">{syncMessage}</div>}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {servers.map((s) => (
            <Card key={s.id} className="card-hover"><CardContent className="p-4">
              <div className="flex items-start gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  {s.transport === 'builtin' ? <Braces className="h-4 w-4" /> : s.transport === 'stdio' ? <Terminal className="h-4 w-4" /> : <Globe2 className="h-4 w-4" />}
                </span>
                <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{s.name}</p>
                  <p className="truncate font-mono text-[10px] text-muted-foreground">{s.code} · {s.transport}</p></div>
                <Switch checked={s.enabled} onCheckedChange={() => void toggle(s)} disabled={!can('mcp:write')} />
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <Badge variant={s.status === 'active' ? 'success' : s.status === 'error' ? 'destructive' : 'muted'}>
                  {s.status === 'active' ? <CheckCircle2 className="h-2.5 w-2.5" /> : <XCircle className="h-2.5 w-2.5" />}{s.status}</Badge>
                <Badge variant={s.health === 'healthy' ? 'success' : s.health === 'unreachable' ? 'destructive' : 'muted'}>{s.health}</Badge>
                <Badge variant="outline">{t('mcp.tools')}: {s.tool_count}</Badge>
              </div>
              <p className="mt-2 truncate font-mono text-[10px] text-muted-foreground">{s.endpoint || s.command || '—'}</p>
              {s.description && <p className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">{s.description}</p>}
              <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t pt-3">
                <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => void openDetail(s)}><Eye className="h-3 w-3" />{t('mcp.viewDetail')}</Button>
                <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => void sync(s)} disabled={!can('mcp:write')}><RefreshCw className="h-3 w-3" />{t('mcp.syncNow')}</Button>
                {can('mcp:write') && <div className="ml-auto flex gap-0.5">
                  <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => openForm(s)}><Save className="h-3 w-3" />{t('common.edit')}</Button>
                  <Button variant="ghost" size="icon-sm" onClick={() => setConfirmDelete(s.id)}><Trash2 className="h-3 w-3 text-destructive" /></Button>
                </div>}
              </div>
              {s.last_sync_at && <p className="mt-1.5 text-[9px] text-muted-foreground">{formatDate(s.last_sync_at, locale)}</p>}
            </CardContent></Card>
          ))}
          {!servers.length && <Card className="p-8 text-center text-sm text-muted-foreground md:col-span-2 xl:col-span-3">{t('common.noData')}</Card>}
        </div>
      </>}

      {tab === 'tools' && <Card><CardContent className="p-0">
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
            <TableCell className="font-mono text-[10px] text-muted-foreground">{permissions[tool.name] || 'mcp:invoke'}</TableCell>
            <TableCell><Button variant="ghost" size="sm" className="h-7 text-xs" disabled={!can('mcp:invoke')}
              onClick={() => { setInvokeTool(tool.name); setInvokeArgs('{}'); setInvokeResult(null); setInvokeOpen(true) }}>
              <Play className="h-3 w-3" />{t('mcp.invoke')}</Button></TableCell>
          </TableRow>)}
        </TableBody></Table>
      </CardContent></Card>}

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
        <div className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-3">
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

      <Dialog open={serverOpen} onOpenChange={setServerOpen}
        title={serverForm.id ? t('mcpServers.editTitle') : t('mcpServers.createTitle')} size="lg"
        footer={<><Button variant="outline" onClick={() => setServerOpen(false)}>{t('common.cancel')}</Button><Button onClick={saveServer}>{t('common.save')}</Button></>}>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('mcpServers.code')}><Input value={serverForm.code} disabled={!!serverForm.id} onChange={(e) => setServerForm({ ...serverForm, code: e.target.value })} placeholder="my_mcp_server" /></Field>
            <Field label={t('common.name')}><Input value={serverForm.name} onChange={(e) => setServerForm({ ...serverForm, name: e.target.value })} /></Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('mcpServers.transport')}><Select value={serverForm.transport} onValueChange={(v) => setServerForm({ ...serverForm, transport: v })}
              options={['builtin', 'http', 'sse', 'stdio'].map((x) => ({ value: x, label: x }))} /></Field>
            <Field label={t('mcp.authToken')}><Input value={serverForm.auth_token} onChange={(e) => setServerForm({ ...serverForm, auth_token: e.target.value })} /></Field>
          </div>
          <Field label={t('common.description')}><Input value={serverForm.description} onChange={(e) => setServerForm({ ...serverForm, description: e.target.value })} /></Field>
          {serverForm.transport !== 'stdio' && <Field label={t('mcp.endpoint')}><Input value={serverForm.endpoint} onChange={(e) => setServerForm({ ...serverForm, endpoint: e.target.value })} placeholder="http://127.0.0.1:9100/mcp" /></Field>}
          {serverForm.transport === 'stdio' && <Field label={t('mcp.command')}><Input value={serverForm.command} onChange={(e) => setServerForm({ ...serverForm, command: e.target.value })} /></Field>}
          <Field label={t('mcpServers.declaredTools')}><Textarea rows={4} className="font-mono text-xs" value={serverForm.tools} onChange={(e) => setServerForm({ ...serverForm, tools: e.target.value })} /></Field>
          <div className="flex items-center justify-between rounded-lg border px-3 py-2"><span className="text-xs">{t('common.enabled')}</span>
            <Switch checked={serverForm.enabled} onCheckedChange={(v) => setServerForm({ ...serverForm, enabled: v })} /></div>
        </div>
      </Dialog>

      <Dialog open={!!detail} onOpenChange={() => setDetail(null)} title={t('mcpServers.detail')} size="lg"
        footer={<Button variant="outline" onClick={() => setDetail(null)}>{t('common.close')}</Button>}>
        {detail && <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 text-xs">
            {[
              [t('common.code'), detail.code], [t('common.name'), detail.name],
              [t('mcpServers.transport'), detail.transport], [t('common.status'), detail.status],
              [t('mcp.health'), detail.health], [t('mcp.endpoint'), detail.endpoint || detail.command || '—'],
              [t('mcpServers.tools'), detail.tool_count], [t('mcpServers.lastSync'), formatDate(detail.last_sync_at, locale)],
            ].map(([k, v]) => <div key={String(k)} className="rounded-lg border px-3 py-2"><p className="text-[10px] text-muted-foreground">{k}</p><p className="mt-0.5 truncate font-medium">{String(v ?? '—')}</p></div>)}
          </div>
          <div><h3 className="mb-1.5 text-xs font-semibold">{t('mcpServers.declaredTools')} ({detail.tools?.length || 0})</h3>
            <div className="flex flex-wrap gap-1">{(detail.tools || []).map((x: any) => <Badge key={x.name} variant="secondary" className="font-mono text-[9px]">{x.name}</Badge>)}
              {!detail.tools?.length && <span className="text-xs text-muted-foreground">—</span>}</div></div>
          <div><h3 className="mb-1.5 text-xs font-semibold">{t('mcpServers.linkedSkills')} ({detail.skills?.length || 0})</h3>
            <div className="flex flex-wrap gap-1">{(detail.skills || []).map((x: any) => <Badge key={x.id} variant="outline" className="font-mono text-[9px]">{x.code} · {x.status}</Badge>)}
              {!detail.skills?.length && <span className="text-xs text-muted-foreground">—</span>}</div></div>
        </div>}
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
      <ConfirmDialog open={confirmClear} onOpenChange={() => setConfirmClear(false)}
        title={t('mcp.clearJournal')} description={t('mcp.confirmClearJournal')} onConfirm={clearJournal} />
    </div>
  )
}
