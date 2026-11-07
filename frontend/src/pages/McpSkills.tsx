import { useEffect, useState } from 'react'
import {
  Activity, Braces, CheckCircle2, Copy, Globe2, Layers, Play, Plug, Plus,
  RefreshCw, Terminal, Trash2, Wrench, XCircle,
} from 'lucide-react'
import { PageHeader, SectionTitle } from '@/components/PageHeader'
import {
  Badge, Button, Card, CardContent, Field, Input, Label, Select, Switch, Textarea,
} from '@/components/ui/basic'
import { ConfirmDialog, Dialog, Tabs, useToast } from '@/components/ui/overlay'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { del, get, post, put } from '@/lib/api'
import { copyText, formatDate, safeParse } from '@/lib/utils'
import type { McpSkill, ToolSpec } from '@/types'

export default function McpSkills() {
  const { t, locale } = useI18n()
  const { can } = useApp()
  const { toast } = useToast()
  const [tab, setTab] = useState('tools')
  const [tools, setTools] = useState<ToolSpec[]>([])
  const [permissions, setPermissions] = useState<Record<string, string>>({})
  const [skills, setSkills] = useState<McpSkill[]>([])
  const [status, setStatus] = useState<any>(null)
  const [skillOpen, setSkillOpen] = useState(false)
  const [invokeOpen, setInvokeOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)
  const [skillForm, setSkillForm] = useState<any>({ id: 0, code: '', name: '', type: 'http', endpoint: '', command: '', enabled: true, auth_config: {} })
  const [invokeTool, setInvokeTool] = useState('get_stats')
  const [invokeArgs, setInvokeArgs] = useState('{}')
  const [invokeResult, setInvokeResult] = useState<any>(null)
  const [syncMessage, setSyncMessage] = useState('')

  const load = async () => {
    try {
      const [tl, sl, st] = await Promise.all([
        get<{ tools: ToolSpec[]; permissions: Record<string, string> }>('/mcp/tools'),
        get<{ skills: McpSkill[] }>('/mcp/skills'),
        get<any>('/mcp/status'),
      ])
      setTools(tl.tools || []); setPermissions(tl.permissions || {})
      setSkills(sl.skills || []); setStatus(st)
    } catch (e: any) { toast(e.message, 'error') }
  }
  useEffect(() => { void load() }, [])

  const saveSkill = async () => {
    const payload: any = { code: skillForm.code, name: skillForm.name, type: skillForm.type,
      endpoint: skillForm.endpoint || null, command: skillForm.command || null,
      enabled: skillForm.enabled, auth_config: skillForm.auth_config || {} }
    try {
      if (skillForm.id) await put(`/mcp/skills/${skillForm.id}`, payload)
      else await post('/mcp/skills', payload)
      setSkillOpen(false); await load(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const openSkill = (s?: McpSkill) => {
    setSkillForm(s ? { id: s.id, code: s.code, name: s.name, type: s.type, endpoint: s.endpoint || '',
      command: s.command || '', enabled: s.enabled, auth_config: s.auth_config || {} }
      : { id: 0, code: '', name: '', type: 'http', endpoint: '', command: '', enabled: true, auth_config: {} })
    setSkillOpen(true)
  }
  const sync = async (id: number) => {
    try { const r: any = await post(`/mcp/skills/${id}/sync`, {}); setSyncMessage(`${r.health}: ${r.message}`)
      toast(t('mcp.syncResult') + ': ' + r.health, r.health === 'healthy' ? 'success' : 'info'); await load() }
    catch (e: any) { toast(e.message, 'error') }
  }
  const remove = async () => {
    if (!confirmDelete) return
    try { await del(`/mcp/skills/${confirmDelete}`); await load(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmDelete(null) }
  }
  const toggleEnabled = async (s: McpSkill) => {
    try { await put(`/mcp/skills/${s.id}`, { enabled: !s.enabled }); await load() }
    catch (e: any) { toast(e.message, 'error') }
  }
  const invoke = async () => {
    try { const r: any = await post('/mcp/invoke', { tool: invokeTool, arguments: safeParse(invokeArgs, {}) })
      setInvokeResult(r.result) } catch (e: any) { setInvokeResult({ error: e.message }); toast(e.message, 'error') }
  }

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader icon={<Plug className="h-5 w-5" />} title={t('mcp.title')} subtitle={t('mcp.subtitle')}
        actions={<>
          <Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>
          {can('mcp:invoke') && <Button variant="outline" size="sm" onClick={() => { setInvokeResult(null); setInvokeOpen(true) }}><Play className="h-3.5 w-3.5" />{t('mcp.invoke')}</Button>}
          {can('mcp:write') && <Button size="sm" onClick={() => openSkill()}><Plus className="h-4 w-4" />{t('mcp.newSkill')}</Button>}
        </>} />

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: t('mcp.status'), value: status?.enabled ? t('common.enabled') : t('common.disabled'), icon: <Activity className="h-4 w-4" /> },
          { label: t('mcp.transport'), value: status?.transport || 'streamable-http', icon: <Globe2 className="h-4 w-4" /> },
          { label: t('mcp.protocol'), value: status?.protocol_version || '2025-06-18', icon: <Layers className="h-4 w-4" /> },
          { label: t('mcp.toolCount'), value: status?.tool_count ?? tools.length, icon: <Wrench className="h-4 w-4" /> },
        ].map((s, i) => <Card key={i} className="p-3"><div className="flex items-center gap-2 text-primary">{s.icon}
          <span className="mono-num text-sm font-semibold text-foreground">{s.value}</span></div>
          <p className="mt-1 text-[11px] text-muted-foreground">{s.label}</p></Card>)}
      </div>

      <Tabs value={tab} onValueChange={setTab} className="mb-4" items={[
        { value: 'tools', label: t('mcp.platformTools'), icon: <Braces className="h-3 w-3" />, count: tools.length },
        { value: 'skills', label: t('mcp.registered'), icon: <Plug className="h-3 w-3" />, count: skills.length },
      ]} />

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

      {tab === 'skills' && <>
        <p className="mb-3 text-xs text-muted-foreground">{t('mcp.externalHint')}</p>
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
                    <p className="truncate font-mono text-[10px] text-muted-foreground">{s.code} · {s.type}</p></div>
                  <Switch checked={s.enabled} onCheckedChange={() => void toggleEnabled(s)} disabled={!can('mcp:write')} />
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  <Badge variant={s.health === 'healthy' ? 'success' : s.health === 'unreachable' ? 'destructive' : 'muted'}>
                    {s.health === 'healthy' ? <CheckCircle2 className="h-2.5 w-2.5" /> : <XCircle className="h-2.5 w-2.5" />}{s.health}
                  </Badge>
                  <Badge variant="outline">{t('mcp.tools')}: {s.tools?.length ?? 0}</Badge>
                  {s.enabled ? <Badge variant="success">{t('common.enabled')}</Badge> : <Badge variant="muted">{t('common.disabled')}</Badge>}
                </div>
                <p className="mt-2 truncate font-mono text-[10px] text-muted-foreground">{s.endpoint || s.command || '—'}</p>
                {!!s.tools?.length && <div className="scroll-thin mt-2 flex max-h-20 flex-wrap gap-1 overflow-y-auto">
                  {s.tools.slice(0, 12).map((tool: any) => <Badge key={tool.name} variant="secondary" className="font-mono text-[9px]">{tool.name}</Badge>)}
                </div>}
                <div className="mt-3 flex items-center gap-1.5 border-t pt-3">
                  <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => void sync(s.id)} disabled={!can('mcp:write')}>
                    <RefreshCw className="h-3 w-3" />{t('mcp.syncNow')}</Button>
                  <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => openSkill(s)} disabled={!can('mcp:write')}>{t('common.edit')}</Button>
                  <Button variant="ghost" size="icon-sm" className="ml-auto" onClick={() => setConfirmDelete(s.id)} disabled={!can('mcp:write')}>
                    <Trash2 className="h-3 w-3 text-destructive" /></Button>
                </div>
                {s.last_sync_at && <p className="mt-1.5 text-[9px] text-muted-foreground">{formatDate(s.last_sync_at, locale)}</p>}
              </CardContent>
            </Card>
          ))}
        </div>
      </>}

      <Dialog open={skillOpen} onOpenChange={setSkillOpen} title={skillForm.id ? t('mcp.editTitle') : t('mcp.createTitle')}
        footer={<><Button variant="outline" onClick={() => setSkillOpen(false)}>{t('common.cancel')}</Button><Button onClick={saveSkill}>{t('common.save')}</Button></>}>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('mcp.skillCode')}><Input value={skillForm.code} disabled={!!skillForm.id} onChange={(e) => setSkillForm({ ...skillForm, code: e.target.value })} placeholder="my_mcp" /></Field>
            <Field label={t('mcp.skillName')}><Input value={skillForm.name} onChange={(e) => setSkillForm({ ...skillForm, name: e.target.value })} /></Field>
          </div>
          <Field label={t('mcp.skillType')}><Select value={skillForm.type} onValueChange={(v) => setSkillForm({ ...skillForm, type: v })}
            options={(status?.types || ['builtin', 'http', 'sse', 'stdio']).map((x: string) => ({ value: x, label: x }))} /></Field>
          {skillForm.type !== 'stdio' && <Field label={t('mcp.endpoint')}><Input value={skillForm.endpoint} onChange={(e) => setSkillForm({ ...skillForm, endpoint: e.target.value })} placeholder="http://127.0.0.1:9100/mcp" /></Field>}
          {skillForm.type === 'stdio' && <Field label={t('mcp.command')}><Input value={skillForm.command} onChange={(e) => setSkillForm({ ...skillForm, command: e.target.value })} placeholder="npx -y @modelcontextprotocol/server-filesystem ./data" /></Field>}
          <Field label={t('mcp.authToken')}><Input value={skillForm.auth_config?.token || ''} onChange={(e) => setSkillForm({ ...skillForm, auth_config: { ...skillForm.auth_config, token: e.target.value } })} /></Field>
          <div className="flex items-center justify-between rounded-lg border px-3 py-2"><span className="text-xs">{t('common.enabled')}</span>
            <Switch checked={skillForm.enabled} onCheckedChange={(v) => setSkillForm({ ...skillForm, enabled: v })} /></div>
        </div>
      </Dialog>

      <Dialog open={invokeOpen} onOpenChange={setInvokeOpen} title={t('mcp.invoke')} size="lg"
        footer={<><Button variant="outline" onClick={() => setInvokeOpen(false)}>{t('common.close')}</Button><Button onClick={invoke}><Play className="h-3.5 w-3.5" />{t('mcp.invokeNow')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('mcp.tools')}><Select value={invokeTool} onValueChange={setInvokeTool}
            options={tools.map((x) => ({ value: x.name, label: x.name }))} /></Field>
          <Field label={t('mcp.arguments')}><Textarea rows={5} className="font-mono text-xs" value={invokeArgs} onChange={(e) => setInvokeArgs(e.target.value)} /></Field>
          {invokeResult !== null && <div className="space-y-1.5">
            <div className="flex items-center justify-between"><Label>{t('mcp.result')}</Label>
              <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => void copyText(JSON.stringify(invokeResult, null, 2))}><Copy className="h-3 w-3" />{t('common.copy')}</Button></div>
            <pre className="scroll-thin max-h-64 overflow-auto rounded-lg border bg-muted/30 p-3 font-mono text-[11px]">{JSON.stringify(invokeResult, null, 2)}</pre>
          </div>}
        </div>
      </Dialog>

      <ConfirmDialog open={confirmDelete !== null} onOpenChange={() => setConfirmDelete(null)} title={t('common.confirmDelete')} onConfirm={remove} />
    </div>
  )
}
