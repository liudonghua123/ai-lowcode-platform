import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Bot, BookOpen, CheckCircle2, ChevronDown, ChevronRight, ClipboardList, Cpu,
  Database, GitBranch, Lock, MessageSquare, Package, Plus, Search, Send,
  Server, Settings2, ShieldCheck, Sparkles, Trash2, Wrench, X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { PageHeader, SectionTitle } from '@/components/PageHeader'
import { SchemaForm } from '@/components/SchemaForm'
import {
  Badge, Button, Card, CardContent, EmptyState, Field, Input, Label, Select,
  Textarea,
} from '@/components/ui/basic'
import { ConfirmDialog, Dialog, useToast } from '@/components/ui/overlay'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { del, get, post, put } from '@/lib/api'
import { cn } from '@/lib/utils'
import type {
  ActionRequest, AgentActionResult, AgentBindings, AgentDef, BindableItem,
  CapabilityMatrix, ChatResponse, ChatStep, Conversation, ToolSpec,
} from '@/types'

interface Message {
  role: 'user' | 'assistant'
  content: string
  steps?: ChatStep[]
  sources?: { doc_id: number; title: string; score: number }[]
  model?: string; provider?: string
  actionRequest?: ActionRequest | null
  actionDone?: boolean
}

const SUGGESTIONS = [
  '查询我的审批及进度 / Show my approvals and progress',
  '我是谁，有哪些权限？ / Who am I and what can I do?',
  '帮我创建一个费用报销流程 / Create an expense claim workflow',
  '有哪些可发起的流程？ / Which workflows can I start?',
  'Show platform statistics',
]

interface BindingConfig {
  name: string; description: string; mode: string; model: string
  system_prompt: string; temperature: number
  kb_ids: number[]; skill_ids: number[]; server_ids: number[]; workflow_ids: number[]
}

const emptyConfig = (): BindingConfig => ({
  name: '', description: '', mode: 'hybrid', model: '',
  system_prompt: 'You are a helpful enterprise assistant.', temperature: 0.3,
  kb_ids: [], skill_ids: [], server_ids: [], workflow_ids: [],
})

type BindingField = 'server_ids' | 'skill_ids' | 'kb_ids' | 'workflow_ids'
type PanelKey = BindingField | 'settings' | 'capabilities' | 'tools' | 'runtime'
type ConfirmState =
  | { kind: 'deleteSession'; id: number; agentId: number }
  | { kind: 'clearSessions'; agentId: number; agentName: string }
  | { kind: 'deleteAgent' }

const toggleId = (list: number[], id: number) =>
  list.includes(id) ? list.filter((x) => x !== id) : [...list, id]

const fmtTime = (s?: string) => (s || '').replace('T', ' ').slice(5, 16)

const configOf = (a: AgentDef): BindingConfig => ({
  name: a.name, description: a.description || '', mode: a.mode,
  model: a.model || '', system_prompt: a.system_prompt || '', temperature: a.temperature,
  kb_ids: [...(a.kb_ids || [])], skill_ids: [...(a.skill_ids || [])],
  server_ids: [...(a.server_ids || [])], workflow_ids: [...(a.workflow_ids || [])],
})

export default function Agents() {
  const { t } = useI18n()
  const { can } = useApp()
  const { toast } = useToast()
  const scrollRef = useRef<HTMLDivElement>(null)
  const [searchParams] = useSearchParams()

  const [agents, setAgents] = useState<AgentDef[]>([])
  const [selected, setSelected] = useState<AgentDef | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [sessions, setSessions] = useState<Record<number, Conversation[]>>({})
  const [groupsOpen, setGroupsOpen] = useState<Record<number, boolean>>({})
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [panel, setPanel] = useState<PanelKey | null>(null)
  const [runtime, setRuntime] = useState<any>(null)
  const [tools, setTools] = useState<ToolSpec[]>([])
  const [capabilities, setCapabilities] = useState<CapabilityMatrix | null>(null)
  const [capOpen, setCapOpen] = useState<Record<string, boolean>>({})
  const [bindings, setBindings] = useState<AgentBindings | null>(null)
  const [config, setConfig] = useState<BindingConfig | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState<any>({})
  const [confirm, setConfirm] = useState<ConfirmState | null>(null)
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})
  const [actionValues, setActionValues] = useState<Record<string, Record<string, unknown>>>({})
  const [actionErrors, setActionErrors] = useState<Record<string, Record<string, string>>>({})
  const [actionBusy, setActionBusy] = useState<string | null>(null)

  const capPct = Math.round(((capabilities?.available_tools ?? 0)
    / Math.max(1, capabilities?.total_tools ?? 1)) * 100)

  const bindingPanels: {
    key: BindingField; field: BindingField; label: string; icon: LucideIcon
    items: BindableItem[]
  }[] = [
    { key: 'server_ids', field: 'server_ids', label: t('agents.mcpServers'), icon: Server,
      items: bindings?.servers || [] },
    { key: 'skill_ids', field: 'skill_ids', label: t('agents.skills'), icon: Package,
      items: bindings?.skills || [] },
    { key: 'kb_ids', field: 'kb_ids', label: t('agents.knowledge'), icon: Database,
      items: bindings?.collections || [] },
    { key: 'workflow_ids', field: 'workflow_ids', label: t('agents.workflows'), icon: GitBranch,
      items: bindings?.workflows || [] },
  ]
  const infoPanels: { key: PanelKey; label: string; icon: LucideIcon }[] = [
    { key: 'settings', label: t('agents.agentSettings'), icon: Settings2 },
    { key: 'capabilities', label: t('agents.capabilities'), icon: ShieldCheck },
    { key: 'tools', label: t('agents.toolCatalog'), icon: Wrench },
    { key: 'runtime', label: t('agents.runtimeInfo'), icon: Cpu },
  ]
  const activeBinding = bindingPanels.find((p) => p.key === panel)
  const ActiveIcon = activeBinding?.icon
  const selectedCount = config
    ? (config.server_ids.length + config.skill_ids.length + config.kb_ids.length + config.workflow_ids.length)
    : 0
  const currentSession = selected && conversationId
    ? (sessions[selected.id] || []).find((c) => c.id === conversationId) || null
    : null

  /* ---------------------------------------------------------------- data --- */

  const refreshSessions = async (agentId: number) => {
    try {
      const d = await get<{ conversations: Conversation[] }>(`/agents/${agentId}/conversations`)
      setSessions((p) => ({ ...p, [agentId]: d.conversations || [] }))
    } catch { /* keep the last known list */ }
  }

  const load = async () => {
    try {
      const [a, rt, b] = await Promise.all([
        get<{ agents: AgentDef[] }>('/agents'),
        get<{ runtime: any; tools: ToolSpec[]; capabilities: CapabilityMatrix }>('/agents/meta/runtime'),
        get<AgentBindings>('/agents/meta/bindings'),
      ])
      const list = a.agents || []
      setAgents(list); setRuntime(rt.runtime); setTools(rt.tools || [])
      setCapabilities(rt.capabilities || null); setBindings(b)
      const pairs = await Promise.all(list.map(async (x): Promise<[number, Conversation[]]> => {
        try {
          const d = await get<{ conversations: Conversation[] }>(`/agents/${x.id}/conversations`)
          return [x.id, d.conversations || []]
        } catch { return [x.id, []] }
      }))
      const map: Record<number, Conversation[]> = {}
      for (const [id, rows] of pairs) map[id] = rows
      setSessions(map)
      return list
    } catch { return [] }
  }
  useEffect(() => { void load() }, [])
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }) }, [messages, sending])

  /* ------------------------------------------------------------- sessions --- */

  const applyAgent = (a: AgentDef) => {
    setSelected(a); setConfig(configOf(a))
    setActionValues({}); setActionErrors({})
  }

  const select = (a: AgentDef) => {
    applyAgent(a); setMessages([]); setConversationId(null)
    setGroupsOpen((p) => ({ ...p, [a.id]: true }))
    setPanel(null)
  }

  // Deep link: /#/agents?agent=general_copilot opens a specific agent.
  useEffect(() => {
    const code = searchParams.get('agent')
    if (!code || !agents.length) return
    const target = agents.find((a) => a.code === code)
    if (target && selected?.id !== target.id) select(target)
  }, [agents, searchParams, selected?.id])

  const openSession = async (a: AgentDef, c: Conversation) => {
    applyAgent(a)
    setGroupsOpen((p) => ({ ...p, [a.id]: true }))
    setPanel(null)
    try {
      const d = await get<Conversation>(`/agents/conversations/${c.id}`)
      setMessages((d.messages || []).map((m) => ({ role: m.role, content: m.content })))
      setConversationId(c.id)
    } catch (e: any) { toast(e.message, 'error') }
  }

  const newSession = async (agentId?: number) => {
    const id = agentId ?? selected?.id
    if (!id) return
    const a = agents.find((x) => x.id === id)
    if (!a) return
    // Reuse an existing empty session instead of piling up blank records.
    const existing = (sessions[id] || []).find((c) => !(c.messages || []).length && !(c.title || '').trim())
    applyAgent(a); setGroupsOpen((p) => ({ ...p, [id]: true }))
    setPanel(null); setMessages([])
    if (existing) { setConversationId(existing.id); return }
    try {
      const d = await post<{ conversation: Conversation }>(`/agents/${id}/conversations`, { title: '' })
      await refreshSessions(id)
      setConversationId(d.conversation.id)
    } catch (e: any) { toast(e.message, 'error'); setConversationId(null) }
  }

  const deleteSession = async (id: number, agentId: number) => {
    try {
      await del(`/agents/conversations/${id}`)
      await refreshSessions(agentId)
      if (conversationId === id) { setMessages([]); setConversationId(null) }
      toast(t('common.deleted'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }

  const clearSessions = async (agentId: number) => {
    try {
      await del(`/agents/${agentId}/conversations`)
      setSessions((p) => ({ ...p, [agentId]: [] }))
      if (selected?.id === agentId) { setMessages([]); setConversationId(null) }
      toast(t('common.deleted'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }

  const runConfirm = () => {
    if (!confirm) return
    const c = confirm
    setConfirm(null)
    if (c.kind === 'deleteSession') void deleteSession(c.id, c.agentId)
    else if (c.kind === 'clearSessions') void clearSessions(c.agentId)
    else void remove()
  }

  /* ------------------------------------------------------------------ chat --- */

  const send = async (text?: string) => {
    const content = (text ?? input).trim()
    if (!content || !selected || sending) return
    setMessages((p) => [...p, { role: 'user', content }]); setInput(''); setSending(true)
    try {
      const r = await post<ChatResponse>(`/agents/${selected.id}/chat`, { message: content, conversation_id: conversationId })
      setConversationId(r.conversation_id)
      setMessages((p) => [...p, { role: 'assistant', content: r.answer, steps: r.steps,
        sources: r.sources, model: r.model, provider: r.provider,
        actionRequest: r.action_request || null }])
      await refreshSessions(selected.id)
    } catch (e: any) { toast(e.message, 'error'); setMessages((p) => [...p, { role: 'assistant', content: `Error: ${e.message}` }]) }
    finally { setSending(false) }
  }

  // Execute the action collected by a schema-driven dynamic form. The chat
  // endpoint only PLANNED the request; /actions creates the real side effect.
  const submitAction = async (m: Message, index: number) => {
    const ar = m.actionRequest
    if (!ar || !selected || actionBusy) return
    const data = actionValues[ar.id] || {}
    setActionBusy(ar.id)
    setActionErrors((p) => ({ ...p, [ar.id]: {} }))
    try {
      const r = await post<AgentActionResult>(`/agents/${selected.id}/actions`, {
        kind: ar.kind, code: ar.code, data, conversation_id: conversationId,
      })
      if (r.conversation_id) setConversationId(r.conversation_id)
      setMessages((p) => p.map((x, i) => i === index ? { ...x, actionDone: true } : x)
        .concat({ role: 'assistant', content: r.answer, provider: 'action' }))
      await refreshSessions(selected.id)
      toast(t('agents.actionFormDone'), 'success')
    } catch (e: any) {
      const msg = String(e?.message || '')
      const errs: Record<string, string> = {}
      for (const part of msg.split('; ')) {
        const j = part.indexOf(':')
        if (j > 0) errs[part.slice(0, j).trim()] = part.slice(j + 1).trim()
      }
      setActionErrors((p) => ({ ...p, [ar.id]: errs }))
      toast(msg, 'error')
    } finally { setActionBusy(null) }
  }

  /* --------------------------------------------------------------- agents --- */

  const openCreate = () => {
    setCreateForm({ code: '', ...emptyConfig(), model: runtime?.model || '', status: 'active' })
    setCreateOpen(true)
  }
  const create = async () => {
    try {
      const a = await post<AgentDef>('/agents', createForm)
      setCreateOpen(false); await load(); select(a); toast(t('common.createdOk'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const saveConfig = async () => {
    if (!selected || !config) return
    try {
      const a = await put<AgentDef>(`/agents/${selected.id}`, config)
      setSelected(a); setAgents((p) => p.map((x) => x.id === a.id ? a : x))
      toast(t('common.saved'), 'success'); setPanel(null)
    } catch (e: any) { toast(e.message, 'error') }
  }
  const remove = async () => {
    if (!selected) return
    const id = selected.id
    try {
      await del(`/agents/${id}`)
      setSelected(null); setMessages([]); setConversationId(null); setPanel(null)
      setSessions((p) => { const n = { ...p }; delete n[id]; return n })
      await load(); toast(t('common.deleted'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }

  const bindingGroups = (cfg: BindingConfig, setter: (fn: (c: any) => any) => void) =>
    bindingPanels.map((g) => <BindingGroup key={g.field} title={g.label} icon={<g.icon className="h-3 w-3" />}
      items={g.items} selected={(cfg[g.field] as number[]) || []}
      onToggle={(id) => setter((c: any) => ({ ...c, [g.field]: toggleId(c[g.field] || [], id) }))} />)

  const panelTitle = activeBinding
    ? `${t('agents.configure')} · ${activeBinding.label}`
    : panel === 'settings' ? t('agents.agentSettings')
      : panel === 'capabilities' ? t('agents.capabilities')
        : panel === 'tools' ? t('agents.toolCatalog')
          : panel === 'runtime' ? t('agents.runtimeInfo') : ''

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader icon={<Bot className="h-5 w-5" />} title={t('agents.title')} subtitle={t('agents.subtitle')}
        actions={<>
          <Badge variant="success" className="gap-1"><Cpu className="h-3 w-3" />{runtime?.agentscope?.available ? 'AgentScope ' + runtime.agentscope.version : runtime?.provider || 'mock'}</Badge>
          {can('agent:write') && <Button size="sm" onClick={openCreate}><Plus className="h-4 w-4" />{t('agents.newAgent')}</Button>}
        </>} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[17rem_minmax(0,1fr)]">
        {/* ---------------------------------------------- agents + sessions --- */}
        <Card><CardContent className="p-3">
          <div className="flex items-center justify-between gap-2">
            <SectionTitle>{t('agents.agentList')}</SectionTitle>
            {can('agent:write') && <Button variant="ghost" size="icon-sm" title={t('agents.newAgent')} onClick={openCreate}>
              <Plus className="h-3.5 w-3.5" /></Button>}
          </div>
          <div className="scroll-thin max-h-[20rem] space-y-1.5 overflow-y-auto lg:max-h-[42rem]">
            {agents.map((a) => {
              const rows = sessions[a.id] || []
              const open = !!groupsOpen[a.id]
              return (
                <div key={a.id} className={cn('rounded-lg border transition-colors',
                  selected?.id === a.id ? 'border-primary/40 bg-primary/[0.04]' : 'border-border')}>
                  <div className="flex items-center gap-0.5 px-1 py-1">
                    <button type="button" onClick={() => setGroupsOpen((p) => ({ ...p, [a.id]: !p[a.id] }))}
                      title={open ? t('agents.collapse') : t('agents.expand')}
                      className="flex h-7 w-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground">
                      {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                    </button>
                    <button type="button" onClick={() => select(a)}
                      className={cn('flex min-w-0 flex-1 items-center gap-1.5 rounded px-1 py-1 text-left',
                        selected?.id === a.id ? 'text-primary' : 'hover:bg-muted')}>
                      <Bot className="h-3.5 w-3.5 shrink-0" />
                      <span className="min-w-0 flex-1 truncate text-xs font-medium">{a.name}</span>
                      <Badge variant="outline" className="shrink-0 text-[8px]">{rows.length}</Badge>
                    </button>
                    <button type="button" title={t('agents.newSession')} onClick={() => void newSession(a.id)}
                      className="flex h-7 w-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-primary">
                      <Plus className="h-3 w-3" /></button>
                    <button type="button" title={t('agents.clearSessions')} disabled={!rows.length}
                      onClick={() => setConfirm({ kind: 'clearSessions', agentId: a.id, agentName: a.name })}
                      className="flex h-7 w-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-destructive/10 hover:text-destructive disabled:opacity-30">
                      <Trash2 className="h-3 w-3" /></button>
                  </div>
                  {open && <div className="space-y-0.5 border-t px-1.5 pb-1.5 pt-1">
                    {rows.map((c) => (
                      <div key={c.id} className={cn('group flex items-center gap-1 rounded-md px-1.5 py-1',
                        conversationId === c.id && selected?.id === a.id ? 'bg-primary/10 text-primary' : 'hover:bg-muted')}>
                        <MessageSquare className="h-3 w-3 shrink-0 opacity-60" />
                        <button type="button" onClick={() => void openSession(a, c)} className="min-w-0 flex-1 text-left">
                          <span className="block truncate text-[11px] font-medium">{c.title || t('agents.untitledSession')}</span>
                          <span className="block truncate text-[9px] text-muted-foreground">
                            {(c.messages || []).length} {t('agents.messagesUnit')} · {fmtTime(c.created_at)}</span>
                        </button>
                        <button type="button" title={t('agents.deleteSession')}
                          onClick={() => setConfirm({ kind: 'deleteSession', id: c.id, agentId: a.id })}
                          className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100 focus:opacity-100">
                          <X className="h-3 w-3" /></button>
                      </div>
                    ))}
                    {!rows.length && <p className="px-1.5 py-2 text-[10px] text-muted-foreground">{t('agents.noSessions')}</p>}
                    <button type="button" onClick={() => void newSession(a.id)}
                      className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-[10px] text-muted-foreground hover:bg-muted hover:text-primary">
                      <Plus className="h-3 w-3" />{t('agents.newSession')}</button>
                  </div>}
                </div>
              )
            })}
            {!agents.length && <p className="py-6 text-center text-xs text-muted-foreground">{t('common.noData')}</p>}
          </div>
          <div className="mt-3 border-t pt-3">
            <Button variant="outline" size="sm" className="w-full" disabled={!selected} onClick={() => void newSession()}>
              <Plus className="h-3.5 w-3.5" />{t('agents.newSession')}</Button>
          </div>
        </CardContent></Card>

        {/* ------------------------------------------------------------ chat --- */}
        <Card className="flex min-h-[34rem] flex-col">
          {!selected ? (
            <EmptyState icon={<Bot className="h-5 w-5" />} title={t('agents.emptyTitle')} description={t('agents.emptyText')} />
          ) : (
            <>
              <div className="flex items-center gap-2 border-b px-4 py-3">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Bot className="h-4 w-4" /></span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold">{selected.name}</p>
                  <p className="truncate text-[11px] text-muted-foreground">
                    {currentSession ? `${currentSession.title || t('agents.untitledSession')} · ` : ''}{selected.description}</p>
                </div>
                <Badge variant="secondary">{selected.mode}</Badge>
                <Button variant="ghost" size="icon-sm" title={t('agents.newSession')} onClick={() => void newSession()}>
                  <Plus className="h-3.5 w-3.5" /></Button>
                {conversationId && <Button variant="ghost" size="icon-sm" title={t('agents.deleteSession')}
                  onClick={() => setConfirm({ kind: 'deleteSession', id: conversationId, agentId: selected.id })}>
                  <Trash2 className="h-3.5 w-3.5 text-destructive" /></Button>}
              </div>

              <div ref={scrollRef} className="scroll-thin flex-1 space-y-4 overflow-y-auto p-4" style={{ maxHeight: '34rem' }}>
                {!messages.length && (
                  <div className="flex h-full flex-col items-center justify-center gap-3 py-10 text-center">
                    <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary"><Sparkles className="h-6 w-6" /></span>
                    <p className="text-sm font-medium">{t('agents.welcome')}</p>
                    <p className="max-w-sm text-xs text-muted-foreground">{t('agents.welcomeHint')}</p>
                    <div className="mt-2 flex max-w-lg flex-wrap justify-center gap-1.5">
                      {SUGGESTIONS.map((s) => <button key={s} onClick={() => void send(s)}
                        className="rounded-full border px-3 py-1.5 text-[11px] text-muted-foreground transition-all hover:border-primary/40 hover:bg-primary/5 hover:text-primary">{s}</button>)}
                    </div>
                  </div>
                )}
                {messages.map((m, i) => (
                  <div key={i} className={cn('flex gap-2.5 animate-fade-up', m.role === 'user' && 'flex-row-reverse')}>
                    <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[11px] font-semibold',
                      m.role === 'user' ? 'bg-secondary text-secondary-foreground' : 'bg-primary/12 text-primary')}>
                      {m.role === 'user' ? 'U' : <Bot className="h-3.5 w-3.5" />}
                    </span>
                    <div className={cn('max-w-[85%] min-w-0', m.role === 'user' && 'text-right')}>
                      <div className={cn('inline-block rounded-xl px-3.5 py-2.5 text-left text-xs leading-relaxed shadow-sm',
                        m.role === 'user' ? 'bg-primary text-primary-foreground' : 'border bg-card')}>
                        <div className="whitespace-pre-wrap break-words">{m.content}</div>
                      </div>
                      {m.role === 'assistant' && m.actionRequest && (
                        <div className="mt-2 rounded-xl border border-primary/30 bg-primary/[0.03] p-3 text-left shadow-sm animate-scale-in">
                          <div className="flex items-start gap-2">
                            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                              <ClipboardList className="h-3.5 w-3.5" /></span>
                            <div className="min-w-0 flex-1">
                              <p className="text-xs font-semibold">{m.actionRequest.title}</p>
                              <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                                {m.actionRequest.description}</p>
                            </div>
                            <Badge variant="secondary" className="shrink-0 text-[9px]">
                              {t('agents.actionFormTag')}</Badge>
                          </div>
                          {m.actionDone ? (
                            <p className="mt-3 flex items-center gap-1.5 rounded-lg border border-success/30 bg-success/5 px-2.5 py-2 text-[11px] text-success">
                              <CheckCircle2 className="h-3.5 w-3.5" />{t('agents.actionFormDone')}</p>
                          ) : (
                            <>
                              <div className="mt-3 border-t pt-3">
                                <SchemaForm fields={m.actionRequest.schema || []}
                                  value={actionValues[m.actionRequest.id] || {}}
                                  onChange={(v) => { const id = m.actionRequest!.id; setActionValues((p) => ({ ...p, [id]: v })) }}
                                  formId={m.actionRequest.form_id}
                                  errors={actionErrors[m.actionRequest.id]}
                                  compact columns={2} />
                              </div>
                              <div className="mt-3 flex flex-wrap items-center gap-2">
                                <Button size="sm" loading={actionBusy === m.actionRequest.id}
                                  onClick={() => void submitAction(m, i)}>
                                  <Send className="h-3 w-3" />{m.actionRequest.submit_label || t('agents.actionFormSubmit')}</Button>
                                <span className="text-[10px] text-muted-foreground">{t('agents.actionFormHint')}</span>
                              </div>
                            </>
                          )}
                        </div>
                      )}
                      {m.role === 'assistant' && (m.steps?.length || m.sources?.length || m.model) ? (
                        <div className="mt-2 space-y-2 text-left">
                          {!!m.sources?.length && <div className="flex flex-wrap gap-1">
                            {m.sources.map((s) => <Badge key={s.doc_id} variant="secondary" className="gap-1 text-[9px]"><BookOpen className="h-2.5 w-2.5" />{s.title} · {s.score}</Badge>)}
                          </div>}
                          {!!m.steps?.length && <div className="rounded-lg border bg-muted/30">
                            <button onClick={() => setExpanded((p) => ({ ...p, [i]: !p[i] }))}
                              className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-[10px] font-medium">
                              {expanded[i] ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                              <Wrench className="h-3 w-3" />{t('agents.stepsCount', { count: m.steps.length })}
                            </button>
                            {expanded[i] && <div className="scroll-thin max-h-52 space-y-1.5 overflow-y-auto border-t p-2">
                              {m.steps.map((s, j) => <div key={j} className="rounded-md bg-background/70 p-2 font-mono text-[10px]">
                                <span className="font-semibold text-primary">{s.tool}</span>
                                <pre className="mt-1 whitespace-pre-wrap break-all text-muted-foreground">{JSON.stringify(s.arguments)}</pre>
                                <pre className="mt-1 max-h-20 overflow-hidden whitespace-pre-wrap break-all text-success">→ {JSON.stringify(s.result).slice(0, 260)}</pre>
                              </div>)}
                            </div>}
                          </div>}
                          {m.model && <p className="text-[10px] text-muted-foreground">{t('agents.answerBy', { model: m.model, provider: m.provider || 'mock' })}</p>}
                        </div>
                      ) : null}
                    </div>
                  </div>
                ))}
                {sending && <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />{t('agents.thinking')}</div>}
              </div>

              {/* Icon toolbar: all agent configuration lives above the composer. */}
              <div className="border-t p-3">
                <div className="mb-2 flex flex-wrap items-center gap-1">
                  {bindingPanels.map((p) => {
                    const n = config ? (config[p.field] || []).length : 0
                    return (
                      <button key={p.key} type="button" title={`${t('agents.configure')} · ${p.label}`}
                        onClick={() => setPanel(p.key)}
                        className={cn('relative inline-flex h-8 items-center gap-1.5 rounded-lg border px-2 text-[11px] font-medium transition-all',
                          panel === p.key ? 'border-primary/50 bg-primary/10 text-primary' : 'text-muted-foreground hover:border-primary/40 hover:text-foreground')}>
                        <p.icon className="h-3.5 w-3.5 shrink-0" />
                        <span className="hidden xl:inline">{p.label}</span>
                        {n > 0 && <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary/15 px-1 font-mono text-[9px] text-primary">{n}</span>}
                      </button>
                    )
                  })}
                  <span className="mx-1 hidden h-5 w-px bg-border sm:block" />
                  {infoPanels.map((p) => (
                    <button key={p.key} type="button" title={p.label} onClick={() => setPanel(p.key)}
                      className={cn('inline-flex h-8 w-8 items-center justify-center rounded-lg border transition-all',
                        panel === p.key ? 'border-primary/50 bg-primary/10 text-primary' : 'text-muted-foreground hover:border-primary/40 hover:text-foreground')}>
                      <p.icon className="h-3.5 w-3.5" /></button>
                  ))}
                  <span className="ml-auto hidden text-[10px] text-muted-foreground md:inline">
                    {t('agents.boundResources', { count: selectedCount })} · {t('agents.attachHint')}
                  </span>
                </div>
                <div className="flex items-end gap-2">
                  <Textarea rows={2} className="min-h-[68px] resize-none text-xs" value={input}
                    placeholder={t('agents.placeholder')} onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send() } }} />
                  <Button size="icon" className="h-[68px] w-11" onClick={() => void send()} disabled={sending || !input.trim()}><Send className="h-4 w-4" /></Button>
                </div>
                <p className="mt-1.5 text-[10px] text-muted-foreground">Enter to send · Shift+Enter for a new line</p>
              </div>
            </>
          )}
        </Card>
      </div>

      {/* -------------------------------------------------- configuration dialogs --- */}
      <Dialog open={panel !== null && !!selected} onOpenChange={(v) => { if (!v) setPanel(null) }}
        title={panelTitle} size={panel === 'capabilities' || panel === 'settings' ? 'lg' : 'md'}
        footer={(activeBinding || panel === 'settings') ? <>
          <Button variant="outline" onClick={() => setPanel(null)}>{t('common.cancel')}</Button>
          <Button onClick={() => void saveConfig()} disabled={!can('agent:write')}>{t('common.save')}</Button>
        </> : <Button variant="outline" onClick={() => setPanel(null)}>{t('common.close')}</Button>}>
        {!selected ? <p className="py-8 text-center text-xs text-muted-foreground">{t('agents.emptyTitle')}</p> : <>
          {activeBinding && ActiveIcon && config && <div className="space-y-3">
            <p className="text-xs leading-relaxed text-muted-foreground">{t('agents.bindingsHint')}</p>
            <BindingGroup large title={activeBinding.label} icon={<ActiveIcon className="h-3 w-3" />}
              items={activeBinding.items} selected={config[activeBinding.field] || []}
              onToggle={(id) => setConfig((c) => c ? { ...c, [activeBinding.field]: toggleId(c[activeBinding.field] || [], id) } : c)} />
            <div className="flex flex-wrap gap-1">
              {bindingPanels.map((p) => <Badge key={p.key} variant="secondary">
                {p.label}: {(config[p.field] || []).length}</Badge>)}
            </div>
          </div>}

          {panel === 'settings' && config && <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-3">
              <Field label={t('agents.agentName')}><Input value={config.name || ''} onChange={(e) => setConfig({ ...config, name: e.target.value })} /></Field>
              <Field label={t('agents.mode')}><Select value={config.mode} onValueChange={(v) => setConfig({ ...config, mode: v })}
                options={['query', 'act', 'hybrid'].map((m) => ({ value: m, label: t(`agents.mode${m.charAt(0).toUpperCase() + m.slice(1)}`) }))} /></Field>
              <Field label={t('agents.model')}><Select value={config.model || ''} onValueChange={(v) => setConfig({ ...config, model: v })}
                options={[{ value: '', label: t('agents.modelDefault') },
                  ...(bindings?.models || []).map((m) => ({ value: m.model || '', label: `${m.name} · ${m.model || 'env'}` }))]} /></Field>
            </div>
            <div className="space-y-3">
              <Field label={t('agents.systemPrompt')}><Textarea rows={5} value={config.system_prompt || ''} onChange={(e) => setConfig({ ...config, system_prompt: e.target.value })} /></Field>
              <Field label={`${t('agents.temperature')}: ${config.temperature}`}>
                <input type="range" min="0" max="1" step="0.1" className="w-full accent-[hsl(var(--primary))]"
                  value={config.temperature} onChange={(e) => setConfig({ ...config, temperature: Number(e.target.value) })} />
              </Field>
              {can('agent:write') && <Button variant="outline" className="w-full text-destructive"
                onClick={() => setConfirm({ kind: 'deleteAgent' })}>
                <Trash2 className="h-3.5 w-3.5" />{t('agents.deleteAgent')}</Button>}
            </div>
          </div>}

          {panel === 'capabilities' && <div className="scroll-thin max-h-[60vh] space-y-2 overflow-y-auto pr-0.5">
            <div className="rounded-lg border bg-muted/40 p-2.5">
              <p className="flex items-center gap-1.5 text-[11px] font-medium">
                <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-primary" />
                <span className="min-w-0">{t('capabilities.permissionDriven')}</span>
              </p>
              <div className="mt-1.5 flex items-end justify-between gap-2">
                <span className="text-[10px] text-muted-foreground">
                  {capabilities?.available_tools ?? 0} / {capabilities?.total_tools ?? 0} {t('capabilities.tools')}</span>
                <span className="font-mono text-[10px] text-primary">{capPct}%</span>
              </div>
              <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${capPct}%` }} />
              </div>
              <p className="mt-1.5 break-words text-[10px] leading-relaxed text-muted-foreground">{t('capabilities.legend')}</p>
            </div>
            {Object.entries(capabilities?.domains || {}).map(([domain, d]) => (
              <div key={domain} className="rounded-lg border p-2">
                <button type="button" onClick={() => setCapOpen({ ...capOpen, [domain]: !capOpen[domain] })}
                  className="flex w-full items-center justify-between gap-2 text-left">
                  <span className="flex min-w-0 items-center gap-1.5">
                    {capOpen[domain] ? <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                      : <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />}
                    <span className="truncate text-[11px] font-medium capitalize">{domain}</span>
                  </span>
                  <span className={cn('shrink-0 font-mono text-[10px]',
                    d.available === d.total ? 'text-emerald-600 dark:text-emerald-400' : 'text-primary')}>
                    {d.available}/{d.total}</span>
                </button>
                <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-primary/70"
                    style={{ width: `${Math.round(d.available / Math.max(1, d.total) * 100)}%` }} />
                </div>
                {!!d.permissions.length && <div className="mt-1.5 flex flex-wrap gap-1">
                  {d.permissions.map((p) => <Badge key={p} variant="outline" className="text-[9px]">{p}</Badge>)}
                </div>}
                {capOpen[domain] && <div className="mt-1.5 space-y-1">
                  {d.tools.map((tool) => (
                    <div key={tool.name} className="flex items-start gap-1.5 rounded border px-1.5 py-1">
                      {tool.available ? <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-500" />
                        : <Lock className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />}
                      <div className="min-w-0 flex-1">
                        <p className={cn('break-words font-mono text-[10px]',
                          tool.available ? 'text-primary' : 'text-muted-foreground')}>{tool.name}</p>
                        <p className="break-words text-[9px] leading-relaxed text-muted-foreground">{tool.description}</p>
                        {tool.permission && <p className="font-mono text-[9px] text-muted-foreground">
                          {tool.permission}{!tool.available && ` · ${t('capabilities.locked')}`}</p>}
                      </div>
                    </div>
                  ))}
                </div>}
              </div>
            ))}
            {!capabilities && <p className="py-6 text-center text-xs text-muted-foreground">—</p>}
          </div>}

          {panel === 'tools' && <div className="scroll-thin max-h-[60vh] space-y-1.5 overflow-y-auto">
            {tools.map((tool) => <div key={tool.name} className="rounded-lg border p-2">
              <p className="font-mono text-[11px] font-medium text-primary">{tool.name}</p>
              <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">{tool.description}</p>
              <p className="mt-1 break-words font-mono text-[9px] text-muted-foreground">
                {Object.keys(tool.inputSchema?.properties || {}).join(', ') || '—'}</p>
            </div>)}
          </div>}

          {panel === 'runtime' && <div className="space-y-2 text-xs">
            {[
              ['provider', runtime?.provider], ['model', runtime?.model], ['temperature', runtime?.temperature],
              ['config_source', runtime?.config_source], ['orchestration', runtime?.orchestration], ['tools', runtime?.tools],
              ['AgentScope', runtime?.agentscope?.available ? `v${runtime.agentscope.version}` : 'unavailable'],
              ['modules', runtime?.agentscope?.modules?.length ?? 0], ['has_api_key', String(runtime?.has_api_key ?? false)],
            ].map(([k, v]) => <div key={String(k)} className="flex items-start justify-between gap-2 rounded-md border px-2.5 py-2">
              <span className="text-muted-foreground">{k}</span>
              <span className="max-w-[60%] break-words text-right font-mono text-[10px]">{String(v ?? '—')}</span></div>)}
            <p className="pt-1 text-[10px] leading-relaxed text-muted-foreground">{t('agents.welcomeHint')}</p>
          </div>}
        </>}
      </Dialog>

      <Dialog open={createOpen} onOpenChange={setCreateOpen} title={t('agents.createTitle')} size="lg"
        footer={<><Button variant="outline" onClick={() => setCreateOpen(false)}>{t('common.cancel')}</Button><Button onClick={create}>{t('common.create')}</Button></>}>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="space-y-3">
            <Field label={t('agents.agentCode')}><Input value={createForm.code} onChange={(e) => setCreateForm({ ...createForm, code: e.target.value })} placeholder="my_agent" /></Field>
            <Field label={t('agents.agentName')}><Input value={createForm.name} onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })} /></Field>
            <Field label={t('common.description')}><Textarea rows={2} value={createForm.description} onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })} /></Field>
            <Field label={t('agents.mode')}><Select value={createForm.mode} onValueChange={(v) => setCreateForm({ ...createForm, mode: v })}
              options={['query', 'act', 'hybrid'].map((m) => ({ value: m, label: t(`agents.mode${m.charAt(0).toUpperCase() + m.slice(1)}`) }))} /></Field>
            <Field label={t('agents.model')}><Select value={createForm.model || ''} onValueChange={(v) => setCreateForm({ ...createForm, model: v })}
              options={[{ value: '', label: t('agents.modelDefault') },
                ...(bindings?.models || []).map((m) => ({ value: m.model || '', label: `${m.name} · ${m.model || 'env'}` }))]} /></Field>
            <Field label={t('agents.systemPrompt')}><Textarea rows={3} value={createForm.system_prompt} onChange={(e) => setCreateForm({ ...createForm, system_prompt: e.target.value })} /></Field>
            <Field label={`${t('agents.temperature')}: ${createForm.temperature}`}>
              <input type="range" min="0" max="1" step="0.1" className="w-full accent-[hsl(var(--primary))]"
                value={createForm.temperature} onChange={(e) => setCreateForm({ ...createForm, temperature: Number(e.target.value) })} />
            </Field>
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between"><Label className="text-xs">{t('agents.bindings')}</Label>
              <Badge variant="outline" className="text-[9px]">{t('agents.selectedCount', { count:
                (createForm.server_ids?.length || 0) + (createForm.skill_ids?.length || 0)
                + (createForm.kb_ids?.length || 0) + (createForm.workflow_ids?.length || 0) })}</Badge></div>
            <p className="text-[10px] text-muted-foreground">{t('agents.bindingsHint')}</p>
            {bindingGroups(createForm as BindingConfig, setCreateForm)}
          </div>
        </div>
      </Dialog>

      <ConfirmDialog open={!!confirm} onOpenChange={(v) => { if (!v) setConfirm(null) }}
        title={confirm?.kind === 'deleteSession' ? t('agents.deleteSession')
          : confirm?.kind === 'clearSessions' ? t('agents.clearSessions') : t('agents.deleteAgent')}
        description={confirm?.kind === 'deleteSession' ? t('agents.confirmDeleteSession')
          : confirm?.kind === 'clearSessions' ? t('agents.confirmClearSessions') : t('agents.confirmDeleteAgent')}
        onConfirm={runConfirm} />
    </div>
  )
}

function BindingGroup({ title, icon, items, selected, onToggle, large = false }: {
  title: string; icon: React.ReactNode; items: BindableItem[]
  selected: number[]; onToggle: (id: number) => void; large?: boolean
}) {
  const [query, setQuery] = useState('')
  const filtered = items.filter((x) => `${x.name} ${x.code}`.toLowerCase().includes(query.toLowerCase()))
  return (
    <div className="rounded-lg border p-2">
      <p className="mb-1.5 flex items-center justify-between gap-1.5 text-[11px] font-medium">
        <span className="flex items-center gap-1.5">{icon}{title}</span>
        <span className="font-mono text-[9px] text-muted-foreground">{selected.length}/{items.length}</span>
      </p>
      <div className="relative mb-1.5">
        <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
        <Input className="h-7 pl-7 text-[11px]" placeholder="…" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <div className={cn('scroll-thin space-y-1 overflow-y-auto', large ? 'max-h-72' : 'max-h-28')}>
        {filtered.map((x) => (
          <label key={x.id} className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-[11px] hover:bg-muted/60">
            <input type="checkbox" className="h-3 w-3 accent-[hsl(var(--primary))]" checked={selected.includes(x.id)} onChange={() => onToggle(x.id)} />
            <span className="min-w-0 flex-1 truncate">{x.name}</span>
            <span className="shrink-0 font-mono text-[9px] text-muted-foreground">{x.code}</span>
          </label>
        ))}
        {!filtered.length && <p className="py-1 text-[10px] text-muted-foreground">—</p>}
      </div>
    </div>
  )
}
