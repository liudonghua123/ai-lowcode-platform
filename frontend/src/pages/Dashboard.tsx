import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity, ArrowUpRight, BookOpen, Bot, FileText, GitBranch, Layers3,
  Play, Plug, ScrollText, Send, ShieldCheck, UsersRound, Workflow,
} from 'lucide-react'
import { PageHeader, SectionTitle } from '@/components/PageHeader'
import { ActivityChart, DonutRing, StatCard, StatusDot } from '@/components/Charts'
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from '@/components/ui/basic'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { get } from '@/lib/api'
import { formatDate, timeAgo } from '@/lib/utils'
import type { AuditLog, WorkflowInstance } from '@/types'

interface Stats {
  forms: number; form_submissions: number; workflows: number; workflow_instances: number
  kb_collections: number; kb_documents: number; agents: number; mcp_skills: number
  users: number; roles: number; audit_logs: number; published_forms: number; published_workflows: number
  recent_instances: WorkflowInstance[]; recent_logs: AuditLog[]
}

export default function Dashboard() {
  const { t, locale } = useI18n()
  const { user, bootstrap } = useApp()
  const [stats, setStats] = useState<Stats | null>(null)

  useEffect(() => { get<Stats>('/meta/stats').then(setStats).catch(() => {}) }, [])

  const cards = [
    { label: t('dashboard.forms'), value: stats?.forms ?? '—', icon: <FileText className="h-4 w-4" />, hint: `${t('dashboard.publishedForms')}: ${stats?.published_forms ?? 0}` },
    { label: t('dashboard.workflows'), value: stats?.workflows ?? '—', icon: <GitBranch className="h-4 w-4" />, hint: `${t('dashboard.publishedWorkflows')}: ${stats?.published_workflows ?? 0}` },
    { label: t('dashboard.submissions'), value: stats?.form_submissions ?? '—', icon: <Layers3 className="h-4 w-4" /> },
    { label: t('dashboard.instances'), value: stats?.workflow_instances ?? '—', icon: <Activity className="h-4 w-4" /> },
    { label: t('dashboard.documents'), value: stats?.kb_documents ?? '—', icon: <BookOpen className="h-4 w-4" />, hint: `${stats?.kb_collections ?? 0} ${t('knowledge.collections').toLowerCase()}` },
    { label: t('dashboard.agents'), value: stats?.agents ?? '—', icon: <Bot className="h-4 w-4" /> },
    { label: t('dashboard.skills'), value: stats?.mcp_skills ?? '—', icon: <Plug className="h-4 w-4" /> },
    { label: t('dashboard.auditEvents'), value: stats?.audit_logs ?? '—', icon: <ScrollText className="h-4 w-4" /> },
  ]

  const runtime: any = bootstrap?.agents?.runtime || {}
  const activity = [12, 19, 15, 28, 24, 36, 31, 42, 38, 51, 47, 62]
  const labels = ['D-6', '', 'D-5', '', 'D-4', '', 'D-3', '', 'D-2', '', 'D-1', t('common.created').slice(0, 3)]

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader
        icon={<LayoutIcon />}
        title={t('dashboard.title')}
        subtitle={`${t('dashboard.welcome', { name: user?.display_name || user?.username || '' })} · ${t('dashboard.welcomeSubtitle')}`}
        actions={<>
          <StatusDot ok label={t('nav.online')} />
          <Button variant="outline" size="sm" onClick={() => window.open('/docs', '_blank')}>
            <ArrowUpRight className="h-3.5 w-3.5" /> API
          </Button>
        </>} />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {cards.map((c, i) => <StatCard key={i} {...c} />)}
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <div><CardTitle>{t('dashboard.activityTrend')}</CardTitle><p className="mt-1 text-xs text-muted-foreground">{t('dashboard.last7days')}</p></div>
            <Badge variant="success">+18.4%</Badge>
          </CardHeader>
          <CardContent><ActivityChart values={activity} labels={labels} /></CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>{t('dashboard.quickActions')}</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {[
              { to: '/forms', icon: <FileText className="h-4 w-4" />, label: t('dashboard.newForm') },
              { to: '/workflows', icon: <Workflow className="h-4 w-4" />, label: t('dashboard.newWorkflow') },
              { to: '/agents', icon: <Send className="h-4 w-4" />, label: t('dashboard.askAgent') },
              { to: '/knowledge', icon: <BookOpen className="h-4 w-4" />, label: t('dashboard.searchKb') },
            ].map((a) => (
              <Link key={a.to} to={a.to}
                className="group flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-all hover:border-primary/40 hover:bg-primary/5 hover:shadow-sm">
                <span className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/10 text-primary">{a.icon}</span>
                {a.label}<ArrowUpRight className="ml-auto h-3.5 w-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
              </Link>
            ))}
          </CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>{t('dashboard.recentRuns')}</CardTitle>
            <Link to="/workflows" className="text-xs text-primary hover:underline">{t('common.view')}</Link>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader><TableRow>
                <TableHead>ID</TableHead><TableHead>{t('common.status')}</TableHead>
                <TableHead>{t('audit.actor')}</TableHead><TableHead>{t('workflows.logs')}</TableHead>
                <TableHead>{t('audit.time')}</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {(stats?.recent_instances || []).map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-mono text-xs">#{r.id}</TableCell>
                    <TableCell><Badge variant={r.status === 'completed' ? 'success' : r.status === 'failed' ? 'destructive' : 'warning'}>{r.status}</Badge></TableCell>
                    <TableCell className="text-xs">{r.started_by}</TableCell>
                    <TableCell className="mono-num text-xs">{r.logs?.length ?? 0}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{formatDate(r.started_at, locale)}</TableCell>
                  </TableRow>
                ))}
                {!stats?.recent_instances?.length && <TableRow><TableCell colSpan={5} className="py-8 text-center text-xs text-muted-foreground">{t('common.noData')}</TableCell></TableRow>}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>{t('dashboard.systemStatus')}</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-xs">
              {[
                [t('dashboard.api'), 'REST · /api/v1'],
                [t('dashboard.mcp'), `streamable-http · ${bootstrap?.mcp?.mode || 'fastmcp'}`],
                [t('dashboard.llm'), `${runtime?.provider || 'mock'} · ${runtime?.model || '—'}`],
                [t('dashboard.retriever'), 'bm25-local'],
                [t('dashboard.users'), String(stats?.users ?? '—')],
                [t('dashboard.skills'), `${bootstrap?.mcp?.tool_count ?? 12} tools`],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-2">
                  <span className="text-muted-foreground">{k}</span>
                  <span className="inline-flex items-center gap-1.5 font-mono text-[11px]"><span className="h-1.5 w-1.5 rounded-full bg-success" />{v}</span>
                </div>
              ))}
              <div className="pt-2"><DonutRing value={stats?.published_forms ?? 0} max={Math.max(stats?.forms ?? 1, 1)}
                label={t('dashboard.publishedForms')} sub={`${stats?.published_forms ?? 0} / ${stats?.forms ?? 0}`} /></div>
            </CardContent>
          </Card>
        </div>
      </div>

      <Card className="mt-4">
        <CardHeader><CardTitle>{t('dashboard.recentActivity')}</CardTitle></CardHeader>
        <CardContent>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {(stats?.recent_logs || []).map((log) => (
              <div key={log.id} className="flex items-start gap-2.5 rounded-lg border px-3 py-2 transition-colors hover:bg-muted/40">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                  {log.action.startsWith('auth') ? <ShieldCheck className="h-3.5 w-3.5" /> :
                   log.action.includes('workflow') ? <Play className="h-3.5 w-3.5" /> : <UsersRound className="h-3.5 w-3.5" />}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium">{log.action}</p>
                  <p className="truncate text-[11px] text-muted-foreground">{log.actor} · {log.resource || '—'}</p>
                </div>
                <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">{timeAgo(log.created_at, locale)}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function LayoutIcon() { return <Activity className="h-5 w-5" /> }
