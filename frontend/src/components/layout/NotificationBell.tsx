import { useCallback, useEffect, useState } from 'react'
import { Bell, CheckCheck } from 'lucide-react'
import { useI18n } from '@/i18n'
import { get, post } from '@/lib/api'
import { Button } from '@/components/ui/basic'
import { Dialog } from '@/components/ui/overlay'
import { cn } from '@/lib/utils'
import type { Notification } from '@/types'

const EVENT_COLORS: Record<string, string> = {
  task_created: 'bg-primary/10 text-primary',
  task_result: 'bg-success/10 text-success',
  urged: 'bg-warning/10 text-warning',
  cc: 'bg-muted text-muted-foreground',
  timeout: 'bg-destructive/10 text-destructive',
  instance_completed: 'bg-success/10 text-success',
  withdrawn: 'bg-muted text-muted-foreground',
}

export function NotificationBell() {
  const { t, locale } = useI18n()
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<Notification[]>([])

  const refresh = useCallback(async () => {
    try {
      const r = await get<{ unread: number }>('/notifications/unread-count')
      setUnread(r.unread || 0)
    } catch { /* offline */ }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 30000)
    return () => clearInterval(id)
  }, [refresh])

  const load = async () => {
    try {
      const r = await get<{ notifications: Notification[]; unread: number }>('/notifications?limit=50')
      setItems(r.notifications || [])
      setUnread(r.unread || 0)
    } catch { /* ignore */ }
  }

  const openList = () => { setOpen(true); load() }

  const markAll = async () => {
    await post('/notifications/read', { all: true })
    await load()
  }

  const markOne = async (id: number) => {
    await post('/notifications/read', { ids: [id] })
    await load()
  }

  return (
    <>
      <Button variant="ghost" size="icon" className="relative" title={t('notifications.title')}
        onClick={openList}>
        <Bell className="h-4 w-4" />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[9px] font-bold text-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </Button>
      <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (v) load() }}
        title={t('notifications.title')} description={`${unread} ${t('notifications.unreadHint')}`}
        footer={
          <Button variant="outline" size="sm" onClick={markAll} className="gap-1.5">
            <CheckCheck className="h-3.5 w-3.5" />{t('notifications.markAllRead')}
          </Button>
        }>
        <div className="scroll-thin max-h-[26rem] space-y-2 overflow-y-auto">
          {items.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">{t('notifications.empty')}</p>
          )}
          {items.map((n) => (
            <div key={n.id} onClick={() => !n.read_at && markOne(n.id)}
              className={cn('flex cursor-pointer gap-2.5 rounded-lg border p-2.5 transition-colors hover:bg-accent',
                !n.read_at && 'bg-primary/5')}>
              <span className={cn('mt-1 h-2 w-2 shrink-0 rounded-full',
                n.read_at ? 'bg-transparent' : 'bg-primary')} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className={cn('rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase',
                    EVENT_COLORS[n.event] || 'bg-muted text-muted-foreground')}>{n.event}</span>
                  <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                    {(n.created_at || '').slice(0, 16).replace('T', ' ')}
                  </span>
                </div>
                <p className={cn('mt-1 truncate text-xs', !n.read_at ? 'font-semibold' : 'text-muted-foreground')}>
                  {n.title}
                </p>
                {n.body && <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">{n.body}</p>}
              </div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-center text-[10px] text-muted-foreground">
          {locale === 'zh' ? '点击未读通知可标记为已读 · 更多设置见个人中心' : 'Click an unread item to mark it read · settings in Profile'}
        </p>
      </Dialog>
    </>
  )
}
