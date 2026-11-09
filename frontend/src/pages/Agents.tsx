import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Bot, BookOpen, CheckCircle2, ChevronDown, ChevronRight, ClipboardList, Cpu,
  Database, GitBranch, Package, MessageSquare, Plus, RefreshCw, Search, Send,
  Server, Settings2, Sparkles, Trash2, Wrench,
} from 'lucide-react'
import { PageHeader, SectionTitle } from '@/components/PageHeader'
import { SchemaForm } from '@/components/SchemaForm'
import {
  Badge, Button, Card, CardContent, EmptyState, Field, Input, Label, Select,
  Switch, Textarea,
} from '@/components/ui/basic'
import { ConfirmDialog, Dialog, Tabs, useToast } from '@/components/ui/overlay'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { del, get, post, put } from '@/lib/api'
import { cn } from '@/lib/utils'
import type {
  ActionRequest, AgentActionResult, AgentBindings, AgentDef, BindableItem,
  ChatResponse, ChatStep, ToolSpec,
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
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [rightTab, setRightTab] = useState('config')
  const [runtime, setRuntime] = useState<any>(null)
  const [tools, setTools] = useState<ToolSpec[]>([])
  const [bindings, setBindings] = useState<AgentBindings | null>(null)
  const [config, setConfig] = useState<BindingConfig | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState<any>({})
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})
  const [actionValues, setActionValues] = useState<Record<string, Record<string, unknown>>>({})
  const [actionErrors, setActionErrors] = useState<Record<string, Record<string, string>>>({})
  const [actionBusy, setActionBusy] = useState<string | null>(null)

  const load = async () => {
    try {
      const [a, rt, b] = await Promise.all([
        get<{ agents: AgentDef[] }>('/agents'),
        get<{ runtime: any; tools: ToolSpec[] }>('/agents/meta/runtime'),
        get<AgentBindings>('/agents/meta/bindings'),
      ])
      setAgents(a.agents || []); setRuntime(rt.runtime); setTools(rt.tools || [])
      setBindings(b)
      return a.agents || []
    } catch { return [] }
  }
  useEffect(() => { void load() }, [])
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }) }, [messages, sending])

  const select = (a: AgentDef) => {
    setSelected(a)
    setConfig({ name: a.name, description: a.description || '', mode: a.mode,
      model: a.model || '', system_prompt: a.system_prompt || '', temperature: a.temperature,
      kb_ids: [...(a.kb_ids || [])], skill_ids: [...(a.skill_ids || [])],
      server_ids: [...(a.server_ids || [])], workflow_ids: [...(a.workflow_ids || [])] })
    setMessages([]); setConversationId(null)
    setActionValues({}); setActionErrors({})
  }

  // Deep link: /#/agents?agent=general_copilot opens a specific agent.
  useEffect(() => {
    const code = searchParams.get('agent')
    if (!code || !agents.length) return
    const target = agents.find((a) => a.code === code)
    if (target && selected?.id !== target.id) select(target)
  }, [agents, searchParams, selected?.id])

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
      setSelected(a); setAgents((p) => p.map((x) => x.id === a.id ? a : x)); toast(t('common.saved'), 'success')
      await load()
    } catch (e: any) { toast(e.message, 'error') }
  }
  const remove = async () => {
    if (!selected) return
    try { await del(`/agents/${selected.id}`); setSelected(null); setMessages([]); await load(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmDelete(false) }
  }
  const toggleBinding = (setter: (fn: (c: any) => any) => void, field: keyof BindingConfig, id: number) => {
    setter((c: any) => ({ ...c, [field]: (c[field] || []).includes(id)
      ? c[field].filter((x: number) => x !== id) : [...(c[field] || []), id] }))
  }

  const bindingGroups = (cfg: BindingConfig, setter: (fn: (c: any) => any) => void) => [
    { field: 'server_ids' as const, title: t('agents.mcpServers'), icon: <Server className="h-3 w-3" />,
      items: bindings?.servers || [] },
    { field: 'skill_ids' as const, title: t('agents.skills'), icon: <Package className="h-3 w-3" />,
      items: bindings?.skills || [] },
    { field: 'kb_ids' as const, title: t('agents.knowledge'), icon: <Database className="h-3 w-3" />,
      items: bindings?.collections || [] },
    { field: 'workflow_ids' as const, title: t('agents.workflows'), icon: <GitBranch className="h-3 w-3" />,
      items: bindings?.workflows || [] },
  ].map((g) => <BindingGroup key={g.field} title={g.title} icon={g.icon} items={g.items}
    selected={(cfg[g.field] as number[]) || []}
    onToggle={(id) => toggleBinding(setter, g.field, id)} />)

  const selectedCount = config
    ? (config.server_ids.length + config.skill_ids.length + config.kb_ids.length + config.workflow_ids.length)
    : 0

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader icon={<Bot className="h-5 w-5" />} title={t('agents.title')} subtitle={t('agents.subtitle')}
        actions={<>
          <Badge variant="success" className="gap-1"><Cpu className="h-3 w-3" />{runtime?.agentscope?.available ? 'AgentScope ' + runtime.agentscope.version : runtime?.provider || 'mock'}</Badge>
          {can('agent:write') && <Button size="sm" onClick={openCreate}><Plus className="h-4 w-4" />{t('agents.newAgent')}</Button>}
        </>} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[14rem_minmax(0,1fr)_22rem]">
        <Card><CardContent className="p-3">
          <SectionTitle>{t('agents.agentList')}</SectionTitle>
          <div className="space-y-1">
            {agents.map((a) => (
              <button key={a.id} onClick={() => select(a)}
                className={cn('flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-all',
                  selected?.id === a.id ? 'bg-primary/10 text-primary' : 'hover:bg-muted')}>
                <Bot className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium">{a.name}</span>
                  <span className="block truncate text-[10px] text-muted-foreground">{a.mode} · {a.model}</span></span>
                <Badge variant="outline" className="shrink-0 text-[8px]">{(a.server_ids || []).length}</Badge>
              </button>
            ))}
          </div>
          <div className="mt-3 border-t pt-3">
            <Button variant="outline" size="sm" className="w-full" onClick={() => { setMessages([]); setConversationId(null); setInput('') }}>
              <Plus className="h-3.5 w-3.5" />{t('agents.newChat')}
            </Button>
          </div>
        </CardContent></Card>

        <Card className="flex min-h-[34rem] flex-col">
          {!selected ? (
            <EmptyState icon={<Bot className="h-5 w-5" />} title={t('agents.emptyTitle')} description={t('agents.emptyText')} />
          ) : (
            <>
              <div className="flex items-center gap-2 border-b px-4 py-3">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary"><Bot className="h-4 w-4" /></span>
                <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{selected.name}</p>
                  <p className="truncate text-[11px] text-muted-foreground">{selected.description}</p></div>
                <Badge variant="secondary">{selected.mode}</Badge>
                <Button variant="ghost" size="icon-sm" title={t('agents.newChat')} onClick={() => { setMessages([]); setConversationId(null) }}><RefreshCw className="h-3.5 w-3.5" /></Button>
              </div>

              <div ref={scrollRef} className="scroll-thin flex-1 space-y-4 overflow-y-auto p-4" style={{ maxHeight: '32rem' }}>
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

              <div className="border-t p-3">
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

        <Card className="h-fit"><CardContent className="p-3">
          <Tabs value={rightTab} onValueChange={setRightTab} className="mb-3 w-full" items={[
            { value: 'config', label: t('agents.config'), icon: <Settings2 className="h-3 w-3" /> },
            { value: 'bindings', label: t('agents.bindings'), icon: <Server className="h-3 w-3" />, count: selectedCount },
            { value: 'runtime', label: t('agents.runtime'), icon: <Cpu className="h-3 w-3" /> },
            { value: 'tools', label: t('agents.tools'), count: tools.length },
          ]} />
          {rightTab === 'config' && (config && selected ? <div className="space-y-3">
            <Field label={t('agents.agentName')}><Input value={config.name || ''} onChange={(e) => setConfig({ ...config, name: e.target.value })} /></Field>
            <Field label={t('agents.mode')}><Select value={config.mode} onValueChange={(v) => setConfig({ ...config, mode: v })}
              options={['query', 'act', 'hybrid'].map((m) => ({ value: m, label: t(`agents.mode${m.charAt(0).toUpperCase() + m.slice(1)}`) }))} /></Field>
            <Field label={t('agents.model')}><Select value={config.model || ''} onValueChange={(v) => setConfig({ ...config, model: v })}
              options={[{ value: '', label: t('agents.modelDefault') },
                ...(bindings?.models || []).map((m) => ({ value: m.model || '', label: `${m.name} · ${m.model || 'env'}` }))]} /></Field>
            <Field label={t('agents.systemPrompt')}><Textarea rows={3} value={config.system_prompt || ''} onChange={(e) => setConfig({ ...config, system_prompt: e.target.value })} /></Field>
            <Field label={`${t('agents.temperature')}: ${config.temperature}`}>
              <input type="range" min="0" max="1" step="0.1" className="w-full accent-[hsl(var(--primary))]"
                value={config.temperature} onChange={(e) => setConfig({ ...config, temperature: Number(e.target.value) })} />
            </Field>
            <div className="flex gap-2">
              <Button size="sm" className="flex-1" onClick={saveConfig} disabled={!can('agent:write')}>{t('common.save')}</Button>
              <Button variant="outline" size="icon" onClick={() => setConfirmDelete(true)} disabled={!can('agent:write')}><Trash2 className="h-3.5 w-3.5 text-destructive" /></Button>
            </div>
          </div> : <p className="py-8 text-center text-xs text-muted-foreground">{t('agents.emptyTitle')}</p>)}

          {rightTab === 'bindings' && (config && selected ? <div className="space-y-2">
            <p className="text-[10px] text-muted-foreground">{t('agents.bindingsHint')}</p>
            {bindingGroups(config, setConfig)}
            <div className="flex flex-wrap gap-1 pt-1">
              <Badge variant="secondary">{t('agents.mcpServers')}: {config.server_ids.length}</Badge>
              <Badge variant="secondary">{t('agents.skills')}: {config.skill_ids.length}</Badge>
              <Badge variant="secondary">{t('agents.knowledge')}: {config.kb_ids.length}</Badge>
              <Badge variant="secondary">{t('agents.workflows')}: {config.workflow_ids.length}</Badge>
            </div>
            <Button size="sm" className="w-full" onClick={saveConfig} disabled={!can('agent:write')}>{t('common.save')}</Button>
          </div> : <p className="py-8 text-center text-xs text-muted-foreground">{t('agents.emptyTitle')}</p>)}

          {rightTab === 'runtime' && <div className="space-y-2 text-xs">
            {[
              ['provider', runtime?.provider], ['model', runtime?.model], ['temperature', runtime?.temperature],
              ['config_source', runtime?.config_source], ['orchestration', runtime?.orchestration], ['tools', runtime?.tools],
              ['AgentScope', runtime?.agentscope?.available ? `v${runtime.agentscope.version}` : 'unavailable'],
              ['modules', runtime?.agentscope?.modules?.length ?? 0], ['has_api_key', String(runtime?.has_api_key ?? false)],
            ].map(([k, v]) => <div key={String(k)} className="flex items-start justify-between gap-2 rounded-md border px-2.5 py-2">
              <span className="text-muted-foreground">{k}</span><span className="max-w-[60%] break-words text-right font-mono text-[10px]">{String(v ?? '—')}</span></div>)}
            <p className="pt-1 text-[10px] leading-relaxed text-muted-foreground">{t('agents.welcomeHint')}</p>
          </div>}

          {rightTab === 'tools' && <div className="scroll-thin max-h-[30rem] space-y-1.5 overflow-y-auto">
            {tools.map((tool) => <div key={tool.name} className="rounded-lg border p-2">
              <p className="font-mono text-[11px] font-medium text-primary">{tool.name}</p>
              <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">{tool.description}</p>
              <p className="mt-1 font-mono text-[9px] text-muted-foreground">{Object.keys(tool.inputSchema?.properties || {}).join(', ') || '—'}</p>
            </div>)}
          </div>}
        </CardContent></Card>
      </div>

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
      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} title={t('common.confirmDelete')} onConfirm={remove} />
    </div>
  )
}

function BindingGroup({ title, icon, items, selected, onToggle }: {
  title: string; icon: React.ReactNode; items: BindableItem[]
  selected: number[]; onToggle: (id: number) => void
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
      <div className="scroll-thin max-h-28 space-y-1 overflow-y-auto">
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
