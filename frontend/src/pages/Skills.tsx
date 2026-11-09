import { useEffect, useState } from 'react'
import {
  Braces, CheckCircle2, Download, Eye, FileCode2, FilePlus2, FileText,
  FolderOpen, Globe2, Layers, Package, Plus, RefreshCw, Save, Terminal,
  Trash2, XCircle, Server,
} from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { Badge, Button, Card, CardContent, Field, Input, Label, Select, Switch, Textarea } from '@/components/ui/basic'
import { ConfirmDialog, Dialog, Dropdown, Tabs, useToast } from '@/components/ui/overlay'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { del, get, post, put } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import type { CatalogSkill, McpServer, McpSkill, SkillFile } from '@/types'

const fileUrl = (skillId: number, path: string) =>
  `/skills/${skillId}/files/${path.split('/').map(encodeURIComponent).join('/')}`

const jsonText = (value: unknown) => {
  try { return JSON.stringify(value ?? {}, null, 2) } catch { return String(value) }
}

export default function Skills() {
  const { t, locale } = useI18n()
  const { can } = useApp()
  const { toast } = useToast()
  const [tab, setTab] = useState('installed')
  const [skills, setSkills] = useState<McpSkill[]>([])
  const [catalog, setCatalog] = useState<CatalogSkill[]>([])
  const [servers, setServers] = useState<McpServer[]>([])
  const [skillOpen, setSkillOpen] = useState(false)
  const [skillForm, setSkillForm] = useState<any>({})
  const [detail, setDetail] = useState<any>(null)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)
  const [confirmUninstall, setConfirmUninstall] = useState<number | null>(null)
  const [filesSkill, setFilesSkill] = useState<McpSkill | null>(null)
  const [files, setFiles] = useState<SkillFile[]>([])
  const [diskPath, setDiskPath] = useState('')
  const [activeFile, setActiveFile] = useState('')
  const [fileContent, setFileContent] = useState('')
  const [fileDirty, setFileDirty] = useState(false)
  const [newFileOpen, setNewFileOpen] = useState(false)
  const [newFilePath, setNewFilePath] = useState('')
  const [syncMessage, setSyncMessage] = useState('')

  const load = async () => {
    try {
      const [sl, cat, srv] = await Promise.all([
        get<{ skills: McpSkill[]; servers: { id: number; code: string; name: string }[] }>('/skills'),
        get<{ catalog: CatalogSkill[] }>('/skills/catalog'),
        get<{ servers: McpServer[] }>('/mcp/servers'),
      ])
      setSkills(sl.skills || []); setCatalog(cat.catalog || []); setServers(srv.servers || [])
    } catch (e: any) { toast(e.message, 'error') }
  }
  useEffect(() => { void load() }, [])

  const statusLabel = (s: string) => s === 'installed' ? t('mcp.installed')
    : s === 'disabled' ? t('mcp.disabled')
      : s === 'uninstalled' ? t('mcp.uninstalled') : s

  const lifecycle = async (s: McpSkill, action: string) => {
    try {
      await post(`/skills/${s.id}/${action}`, {})
      await load(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const installFromCatalog = async (code: string) => {
    try { await post('/skills/install', { code }); await load(); toast(t('common.saved'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
  }
  const sync = async (s: McpSkill) => {
    try {
      const r: any = await post(`/skills/${s.id}/sync`, {})
      setSyncMessage(`${s.code}: ${r.health} — ${r.message}`)
      await load(); toast(t('mcp.syncResult') + ': ' + r.health, 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const remove = async () => {
    if (!confirmDelete) return
    try { await del(`/skills/${confirmDelete}`); await load(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmDelete(null) }
  }
  const uninstall = async () => {
    if (!confirmUninstall) return
    try { await post(`/skills/${confirmUninstall}/uninstall`, {}); await load(); toast(t('common.saved'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmUninstall(null) }
  }
  const saveSkill = async () => {
    const payload: any = {
      code: skillForm.code, name: skillForm.name, type: skillForm.type,
      endpoint: skillForm.endpoint || null, command: skillForm.command || null,
      enabled: skillForm.enabled, auth_config: skillForm.auth_config || {},
      description: skillForm.description || '', version: skillForm.version || '1.0.0',
      server_id: skillForm.server_id || null,
    }
    try {
      if (skillForm.id) await put(`/skills/${skillForm.id}`, payload)
      else await post('/skills', payload)
      setSkillOpen(false); await load(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const openSkill = (s?: McpSkill) => {
    setSkillForm(s ? {
      id: s.id, code: s.code, name: s.name, type: s.type, endpoint: s.endpoint || '',
      command: s.command || '', enabled: s.enabled, auth_config: s.auth_config || {},
      description: s.description || '', version: s.version || '1.0.0',
      server_id: s.server_id || 0,
    } : { id: 0, code: '', name: '', type: 'http', endpoint: '', command: '', enabled: true,
      auth_config: {}, description: '', version: '1.0.0', server_id: 0 })
    setSkillOpen(true)
  }
  const openDetail = async (s: McpSkill) => {
    try { setDetail(await get(`/skills/${s.id}`)) } catch (e: any) { toast(e.message, 'error') }
  }
  const selectFile = async (skillId: number, path: string) => {
    try {
      const f = await get<SkillFile>(fileUrl(skillId, path))
      setActiveFile(path); setFileContent(f.content || ''); setFileDirty(false)
    } catch (e: any) { toast(e.message, 'error') }
  }
  const openFiles = async (s: McpSkill) => {
    try {
      const d = await get<{ files: SkillFile[]; disk_path: string }>(`/skills/${s.id}/files`)
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
    const path = newFilePath.trim()
    try {
      await put(fileUrl(filesSkill.id, path), { content: '' })
      setNewFileOpen(false); setNewFilePath(''); await openFiles(filesSkill)
      await selectFile(filesSkill.id, path)
      toast(t('mcp.fileSaved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const removeFile = async () => {
    if (!filesSkill || !activeFile) return
    try { await del(fileUrl(filesSkill.id, activeFile)); toast(t('mcp.fileDeleted'), 'success'); await openFiles(filesSkill) }
    catch (e: any) { toast(e.message, 'error') }
  }
  const reloadFiles = async () => {
    if (!filesSkill) return
    try { await post(`/skills/${filesSkill.id}/files/reload`, {}); await openFiles(filesSkill) }
    catch (e: any) { toast(e.message, 'error') }
  }

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader icon={<Package className="h-5 w-5" />} title={t('skills.title')} subtitle={t('skills.subtitle')}
        actions={<>
          <Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>
          {can('mcp:write') && <Button size="sm" onClick={() => setTab('catalog')}><Download className="h-4 w-4" />{t('skills.installFromCatalog')}</Button>}
          {can('mcp:write') && <Button size="sm" variant="outline" onClick={() => openSkill()}><Plus className="h-4 w-4" />{t('skills.newSkill')}</Button>}
        </>} />

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: t('skills.installed'), value: skills.filter((s) => s.status === 'installed').length, icon: <CheckCircle2 className="h-4 w-4" /> },
          { label: t('skills.disabled'), value: skills.filter((s) => s.status === 'disabled').length, icon: <XCircle className="h-4 w-4" /> },
          { label: t('skills.catalog'), value: catalog.length, icon: <Package className="h-4 w-4" /> },
          { label: t('skills.linkedServers'), value: skills.filter((s) => !!s.server_id).length, icon: <Server className="h-4 w-4" /> },
        ].map((s, i) => <Card key={i} className="p-3"><div className="flex items-center gap-2 text-primary">{s.icon}
          <span className="mono-num text-sm font-semibold text-foreground">{s.value}</span></div>
          <p className="mt-1 text-[11px] text-muted-foreground">{s.label}</p></Card>)}
      </div>

      <Tabs value={tab} onValueChange={setTab} className="mb-4" items={[
        { value: 'installed', label: t('skills.registered'), icon: <Package className="h-3 w-3" />, count: skills.length },
        { value: 'catalog', label: t('skills.catalog'), icon: <Layers className="h-3 w-3" />, count: catalog.length },
      ]} />

      {tab === 'installed' && <>
        <p className="mb-3 text-xs text-muted-foreground">{t('skills.hint')}</p>
        {syncMessage && <div className="mb-3 rounded-lg border bg-muted/40 px-3 py-2 font-mono text-[11px]">{syncMessage}</div>}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {skills.map((s) => (
            <Card key={s.id} className="card-hover"><CardContent className="p-4">
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
                  {s.status === 'installed' ? <CheckCircle2 className="h-2.5 w-2.5" /> : <XCircle className="h-2.5 w-2.5" />}{statusLabel(s.status)}</Badge>
                <Badge variant="outline"><FileCode2 className="h-2.5 w-2.5" />{t('mcp.fileCount', { count: s.file_count ?? 0 })}</Badge>
                <Badge variant="outline">{t('mcp.tools')}: {s.tools?.length ?? 0}</Badge>
                {s.server && <Badge variant="secondary" className="font-mono text-[9px]"><Server className="h-2.5 w-2.5" />{s.server.code}</Badge>}
              </div>
              {s.description && <p className="mt-2 line-clamp-2 text-[11px] text-muted-foreground">{s.description}</p>}
              <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t pt-3">
                <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => void openDetail(s)}><Eye className="h-3 w-3" />{t('mcp.viewDetail')}</Button>
                <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => void openFiles(s)}><FolderOpen className="h-3 w-3" />{t('mcp.files')}</Button>
                {can('mcp:write') && <div className="ml-auto"><Dropdown trigger={<Button variant="ghost" size="sm" className="h-7 text-xs">···</Button>} items={[
                  { label: t('common.edit'), icon: <FileText className="h-3 w-3" />, onClick: () => openSkill(s) },
                  { label: t('skills.syncFromServer'), icon: <RefreshCw className="h-3 w-3" />, onClick: () => void sync(s) },
                  ...(s.status === 'installed' || s.status === 'disabled'
                    ? [{ label: t('mcp.uninstall'), icon: <Trash2 className="h-3 w-3" />, destructive: true, onClick: () => setConfirmUninstall(s.id) }]
                    : [{ label: t('mcp.reinstall'), icon: <RefreshCw className="h-3 w-3" />, onClick: () => void lifecycle(s, 'reinstall') }]),
                  { label: t('common.delete'), icon: <Trash2 className="h-3 w-3" />, destructive: true, separator: true, onClick: () => setConfirmDelete(s.id) },
                ]} /></div>}
              </div>
            </CardContent></Card>
          ))}
          {!skills.length && <Card className="p-8 text-center text-sm text-muted-foreground md:col-span-2 xl:col-span-3">{t('mcp.emptySkills')}</Card>}
        </div>
      </>}

      {tab === 'catalog' && <>
        <p className="mb-3 text-xs text-muted-foreground">{t('mcp.catalogHint')}</p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
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

      <Dialog open={skillOpen} onOpenChange={setSkillOpen} title={skillForm.id ? t('mcp.editTitle') : t('skills.createTitle')}
        footer={<><Button variant="outline" onClick={() => setSkillOpen(false)}>{t('common.cancel')}</Button><Button onClick={saveSkill}>{t('common.save')}</Button></>}>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('mcp.skillCode')}><Input value={skillForm.code} disabled={!!skillForm.id} onChange={(e) => setSkillForm({ ...skillForm, code: e.target.value })} placeholder="my_skill" /></Field>
            <Field label={t('mcp.skillName')}><Input value={skillForm.name} onChange={(e) => setSkillForm({ ...skillForm, name: e.target.value })} /></Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('mcp.skillType')}><Select value={skillForm.type} onValueChange={(v) => setSkillForm({ ...skillForm, type: v })}
              options={['builtin', 'http', 'sse', 'stdio'].map((x) => ({ value: x, label: x }))} /></Field>
            <Field label={t('common.version')}><Input value={skillForm.version} onChange={(e) => setSkillForm({ ...skillForm, version: e.target.value })} /></Field>
          </div>
          <Field label={t('skills.linkedServer')}><Select value={String(skillForm.server_id || '')}
            onValueChange={(v) => setSkillForm({ ...skillForm, server_id: Number(v) || 0 })}
            options={[{ value: '', label: t('common.none') }, ...servers.map((s) => ({ value: String(s.id), label: `${s.name} (${s.code})` }))]} /></Field>
          <Field label={t('common.description')}><Input value={skillForm.description} onChange={(e) => setSkillForm({ ...skillForm, description: e.target.value })} /></Field>
          {skillForm.type !== 'stdio' && <Field label={t('mcp.endpoint')}><Input value={skillForm.endpoint} onChange={(e) => setSkillForm({ ...skillForm, endpoint: e.target.value })} /></Field>}
          {skillForm.type === 'stdio' && <Field label={t('mcp.command')}><Input value={skillForm.command} onChange={(e) => setSkillForm({ ...skillForm, command: e.target.value })} /></Field>}
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
              [t('skills.linkedServer'), detail.server?.code || '—'], [t('mcp.installedAt'), formatDate(detail.installed_at, locale)],
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
          <div className="grid grid-cols-1 gap-3 md:grid-cols-[16rem_1fr]">
            <div className="scroll-thin max-h-[26rem] space-y-1 overflow-y-auto rounded-lg border p-2">
              {files.map((f) => <button key={f.path} onClick={() => void selectFile(filesSkill!.id, f.path)}
                className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[11px] transition-colors ${activeFile === f.path ? 'bg-primary/10 text-primary' : 'hover:bg-accent'}`}>
                <FileCode2 className="h-3 w-3 shrink-0" /><span className="min-w-0 flex-1 truncate font-mono">{f.path}</span>
                <span className="text-[9px] text-muted-foreground">{f.size}B</span></button>)}
              {!files.length && <p className="p-3 text-center text-xs text-muted-foreground">{t('common.noData')}</p>}
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

      <ConfirmDialog open={confirmDelete !== null} onOpenChange={() => setConfirmDelete(null)} title={t('common.confirmDelete')} onConfirm={remove} />
      <ConfirmDialog open={confirmUninstall !== null} onOpenChange={() => setConfirmUninstall(null)}
        title={t('mcp.uninstall')} description={t('mcp.confirmUninstall')} onConfirm={uninstall} />
    </div>
  )
}
