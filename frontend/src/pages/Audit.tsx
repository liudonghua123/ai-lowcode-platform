import { useEffect, useState } from 'react'
import { Braces, Filter, RefreshCw, ScrollText } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { Badge, Button, Card, CardContent, Input, Select } from '@/components/ui/basic'
import { Dialog, useToast } from '@/components/ui/overlay'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useI18n } from '@/i18n'
import { get } from '@/lib/api'
import { formatDate, timeAgo } from '@/lib/utils'
import type { AuditLog } from '@/types'

export default function Audit() {
  const { t, locale } = useI18n()
  const { toast } = useToast()
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [actions, setActions] = useState<string[]>([])
  const [q, setQ] = useState('')
  const [level, setLevel] = useState('')
  const [action, setAction] = useState('')
  const [detail, setDetail] = useState<AuditLog | null>(null)

  const load = async () => {
    try {
      const params = new URLSearchParams({ limit: '200' })
      if (q) params.set('q', q)
      if (level) params.set('level', level)
      if (action) params.set('action', action)
      const [l, a] = await Promise.all([
        get<{ logs: AuditLog[] }>(`/audit/logs?${params.toString()}`),
        get<{ actions: string[] }>('/audit/actions'),
      ])
      setLogs(l.logs || []); setActions(a.actions || [])
    } catch (e: any) { toast(e.message, 'error') }
  }
  useEffect(() => { void load() }, [q, level, action])

  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeader icon={<ScrollText className="h-5 w-5" />} title={t('audit.title')} subtitle={t('audit.subtitle')}
        actions={<Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>} />

      <Card className="mb-4"><CardContent className="flex flex-wrap items-center gap-2 py-3">
        <Filter className="h-3.5 w-3.5 text-muted-foreground" />
        <Input className="h-8 w-full max-w-xs text-xs" placeholder={t('audit.searchPlaceholder')} value={q} onChange={(e) => setQ(e.target.value)} />
        <Select className="h-8 w-36 text-xs" value={level} onValueChange={setLevel}
          options={[{ value: '', label: `${t('audit.level')}: ${t('common.all')}` },
            { value: 'info', label: t('audit.info') }, { value: 'warn', label: t('audit.warn') }, { value: 'error', label: t('audit.error') }]} />
        <Select className="h-8 w-48 text-xs" value={action} onValueChange={setAction}
          options={[{ value: '', label: `${t('audit.action')}: ${t('common.all')}` },
            ...actions.map((a) => ({ value: a, label: a }))]} />
        <Badge variant="secondary" className="ml-auto">{logs.length} {t('common.total')}</Badge>
      </CardContent></Card>

      <Card><CardContent className="p-0"><Table>
        <TableHeader><TableRow>
          <TableHead>{t('audit.time')}</TableHead><TableHead>{t('audit.actor')}</TableHead>
          <TableHead>{t('audit.action')}</TableHead><TableHead>{t('audit.resource')}</TableHead>
          <TableHead>{t('audit.level')}</TableHead><TableHead>{t('audit.ip')}</TableHead><TableHead>{t('audit.details')}</TableHead>
        </TableRow></TableHeader>
        <TableBody>{logs.map((l) => <TableRow key={l.id}>
          <TableCell className="whitespace-nowrap text-[11px] text-muted-foreground" title={formatDate(l.created_at, locale)}>{timeAgo(l.created_at, locale)}</TableCell>
          <TableCell className="text-xs font-medium">{l.actor}</TableCell>
          <TableCell><Badge variant="outline" className="font-mono text-[10px]">{l.action}</Badge></TableCell>
          <TableCell className="max-w-[14rem] truncate font-mono text-[10px] text-muted-foreground">{l.resource || '—'}</TableCell>
          <TableCell><Badge variant={l.level === 'error' ? 'destructive' : l.level === 'warn' ? 'warning' : 'success'}>{l.level}</Badge></TableCell>
          <TableCell className="font-mono text-[10px] text-muted-foreground">{l.ip || '—'}</TableCell>
          <TableCell><Button variant="ghost" size="icon-sm" onClick={() => setDetail(l)}><Braces className="h-3 w-3" /></Button></TableCell>
        </TableRow>)}
        {!logs.length && <TableRow><TableCell colSpan={7} className="py-10 text-center text-xs text-muted-foreground">{t('common.noData')}</TableCell></TableRow>}
        </TableBody></Table></CardContent></Card>

      <Dialog open={!!detail} onOpenChange={() => setDetail(null)} title={`${detail?.action} · #${detail?.id}`} size="md">
        <pre className="scroll-thin max-h-80 overflow-auto rounded-lg border bg-muted/30 p-3 font-mono text-[11px]">{JSON.stringify(detail, null, 2)}</pre>
      </Dialog>
    </div>
  )
}
