import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Bot, BookOpen, ChevronDown, ChevronRight, CircleHelp, Cpu, Database, GitBranch,
  MessageSquare, Plus, RefreshCw, Send, Settings2, Sparkles, Trash2, Wrench,
} from 'lucide-react'
import { PageHeader, SectionTitle } from '@/components/PageHeader'
import {
  Badge, Button, Card, CardContent, EmptyState, Field, Input, Label, Select,
  Switch, Textarea,
} from '@/components/ui/basic'
import { ConfirmDialog, Dialog, Tabs, useToast } from '@/components/ui/overlay'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { del, get, post, put } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { AgentDef, ChatResponse, ChatStep, KbCollection, McpSkill, ToolSpec, WorkflowDef } from '@/types'

interface Message {
  role: 'user' | 'assistant'
  content: string
  steps?: ChatStep[]
  sources?: { doc_id: number; title: string; score: number }[]
  model?: string; provider?: string
}

const SUGGESTIONS = [
  'What is the leave policy? / 请假制度是什么？',
  'List all forms',
  'Run the leave approval workflow',
  'Show platform statistics',
]

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
  const [kb, setKb] = useState<KbCollection[]>([])
  const [skills, setSkills] = useState<McpSkill[]>([])
  const [workflows, setWorkflows] = useState<WorkflowDef[]>([])
  const [config, setConfig] = useState<any>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [newAgent, setNewAgent] = useState({ code: '', name: '', description: '', mode: 'hybrid' })
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})

  const load = async () => {
    try {
      const [a, rt, tv, k, s, w] = await Promise.all([
        get<{ agents: AgentDef[] }>('/agents'),
        get<{ runtime: any; tools: ToolSpec[] }>('/agents/meta/runtime'),
        Promise.resolve(null),
        get<{ collections: KbCollection[] }>('/knowledge/collections'),
        get<{ skills: McpSkill[] }>('/mcp/skills'),
        get<{ workflows: WorkflowDef[] }>('/workflows'),
      ])
      void tv
      setAgents(a.agents || []); setRuntime(rt.runtime); setTools(rt.tools || [])
      setKb(k.collections || []); setSkills(s.skills || []); setWorkflows(w.workflows || [])
      return a.agents || []
    } catch { return [] }
  }
  useEffect(() => { void load() }, [])
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }) }, [messages, sending])

  const select = (a: AgentDef) => {
    setSelected(a)
    setConfig({ name: a.name, description: a.description, mode: a.mode, model: a.model,
      system_prompt: a.system_prompt, temperature: a.temperature,
      kb_ids: [...(a.kb_ids || [])], skill_ids: [...(a.skill_ids || [])], workflow_ids: [...(a.workflow_ids || [])] })
    setMessages([]); setConversationId(null)
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
        sources: r.sources, model: r.model, provider: r.provider }])
    } catch (e: any) { toast(e.message, 'error'); setMessages((p) => [...p, { role: 'assistant', content: `Error: ${e.message}` }]) }
    finally { setSending(false) }
  }

  const create = async () => {
    try {
      const a = await post<AgentDef>('/agents', { ...newAgent, temperature: 0.3,
        system_prompt: 'You are a helpful enterprise assistant.', model: runtime?.model,
        kb_ids: [], skill_ids: [], workflow_ids: [], status: 'active' })
      setCreateOpen(false); setNewAgent({ code: '', name: '', description: '', mode: 'hybrid' })
      await load(); select(a); toast(t('common.createdOk'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const saveConfig = async () => {
    if (!selected || !config) return
    try {
      const a = await put<AgentDef>(`/agents/${selected.id}`, config)
      setSelected(a); setAgents((p) => p.map((x) => x.id === a.id ? a : x)); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const remove = async () => {
    if (!selected) return
    try { await del(`/agents/${selected.id}`); setSelected(null); setMessages([]); await load(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmDelete(false) }
  }
  const toggleBinding = (field: 'kb_ids' | 'skill_ids' | 'workflow_ids', id: number) => {
    setConfig((c: any) => ({ ...c, [field]: (c[field] || []).includes(id) ? c[field].filter((x: number) => x !== id) : [...(c[field] || []), id] }))
  }

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader icon={<Bot className="h-5 w-5" />} title={t('agents.title')} subtitle={t('agents.subtitle')}
        actions={<>
          <Badge variant="success" className="gap-1"><Cpu className="h-3 w-3" />{runtime?.agentscope?.available ? 'AgentScope ' + runtime.agentscope.version : runtime?.provider || 'mock'}</Badge>
          {can('agent:write') && <Button size="sm" onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" />{t('agents.newAgent')}</Button>}
        </>} />

      <div className="grid gap-4 lg:grid-cols-[14rem_minmax(0,1fr)_20rem]">
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
            { value: 'runtime', label: t('agents.runtime'), icon: <Cpu className="h-3 w-3" /> },
            { value: 'tools', label: t('agents.tools'), count: tools.length },
          ]} />
          {rightTab === 'config' && (config && selected ? <div className="space-y-3">
            <Field label={t('agents.agentName')}><Input value={config.name || ''} onChange={(e) => setConfig({ ...config, name: e.target.value })} /></Field>
            <Field label={t('agents.mode')}><Select value={config.mode} onValueChange={(v) => setConfig({ ...config, mode: v })}
              options={['query', 'act', 'hybrid'].map((m) => ({ value: m, label: t(`agents.mode${m.charAt(0).toUpperCase() + m.slice(1)}`) }))} /></Field>
            <Field label={t('agents.model')}><Input value={config.model || ''} onChange={(e) => setConfig({ ...config, model: e.target.value })} /></Field>
            <Field label={t('agents.systemPrompt')}><Textarea rows={4} value={config.system_prompt || ''} onChange={(e) => setConfig({ ...config, system_prompt: e.target.value })} /></Field>
            <Field label={`${t('agents.temperature')}: ${config.temperature}`}>
              <input type="range" min="0" max="1" step="0.1" className="w-full accent-[hsl(var(--primary))]"
                value={config.temperature} onChange={(e) => setConfig({ ...config, temperature: Number(e.target.value) })} />
            </Field>
            <BindingGroup title={t('agents.knowledge')} icon={<Database className="h-3 w-3" />}
              items={kb.map((x) => ({ id: x.id, label: x.name }))} selected={config.kb_ids || []}
              onToggle={(id) => toggleBinding('kb_ids', id)} />
            <BindingGroup title={t('agents.skills')} icon={<Wrench className="h-3 w-3" />}
              items={skills.map((x) => ({ id: x.id, label: x.name }))} selected={config.skill_ids || []}
              onToggle={(id) => toggleBinding('skill_ids', id)} />
            <BindingGroup title={t('agents.workflows')} icon={<GitBranch className="h-3 w-3" />}
              items={workflows.map((x) => ({ id: x.id, label: x.name }))} selected={config.workflow_ids || []}
              onToggle={(id) => toggleBinding('workflow_ids', id)} />
            <div className="flex gap-2">
              <Button size="sm" className="flex-1" onClick={saveConfig} disabled={!can('agent:write')}>{t('common.save')}</Button>
              <Button variant="outline" size="icon" onClick={() => setConfirmDelete(true)} disabled={!can('agent:write')}><Trash2 className="h-3.5 w-3.5 text-destructive" /></Button>
            </div>
          </div> : <p className="py-8 text-center text-xs text-muted-foreground">{t('agents.emptyTitle')}</p>)}

          {rightTab === 'runtime' && <div className="space-y-2 text-xs">
            {[
              ['provider', runtime?.provider], ['model', runtime?.model], ['temperature', runtime?.temperature],
              ['orchestration', runtime?.orchestration], ['tools', runtime?.tools],
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

      <Dialog open={createOpen} onOpenChange={setCreateOpen} title={t('agents.createTitle')}
        footer={<><Button variant="outline" onClick={() => setCreateOpen(false)}>{t('common.cancel')}</Button><Button onClick={create}>{t('common.create')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('agents.agentCode')}><Input value={newAgent.code} onChange={(e) => setNewAgent({ ...newAgent, code: e.target.value })} placeholder="my_agent" /></Field>
          <Field label={t('agents.agentName')}><Input value={newAgent.name} onChange={(e) => setNewAgent({ ...newAgent, name: e.target.value })} /></Field>
          <Field label={t('common.description')}><Textarea value={newAgent.description} onChange={(e) => setNewAgent({ ...newAgent, description: e.target.value })} /></Field>
          <Field label={t('agents.mode')}><Select value={newAgent.mode} onValueChange={(v) => setNewAgent({ ...newAgent, mode: v })}
            options={['query', 'act', 'hybrid'].map((m) => ({ value: m, label: t(`agents.mode${m.charAt(0).toUpperCase() + m.slice(1)}`) }))} /></Field>
        </div>
      </Dialog>
      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} title={t('common.confirmDelete')} onConfirm={remove} />
    </div>
  )
}

function BindingGroup({ title, icon, items, selected, onToggle }: {
  title: string; icon: React.ReactNode; items: { id: number; label: string }[]
  selected: number[]; onToggle: (id: number) => void
}) {
  return (
    <div className="rounded-lg border p-2">
      <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium">{icon}{title}</p>
      <div className="scroll-thin max-h-28 space-y-1 overflow-y-auto">
        {items.map((x) => (
          <label key={x.id} className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-[11px] hover:bg-muted/60">
            <input type="checkbox" className="h-3 w-3 accent-[hsl(var(--primary))]" checked={selected.includes(x.id)} onChange={() => onToggle(x.id)} />
            <span className="truncate">{x.label}</span>
          </label>
        ))}
        {!items.length && <p className="py-1 text-[10px] text-muted-foreground">—</p>}
      </div>
    </div>
  )
}
