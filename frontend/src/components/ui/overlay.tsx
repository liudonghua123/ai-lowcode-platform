import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { Button } from './basic'
import { cn } from '@/lib/utils'
import { useI18n } from '@/i18n'

/* -------------------------------------------------------------------------- */
/* Dialog                                                                      */
/* -------------------------------------------------------------------------- */
const dialogSizes = {
  sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-2xl', xl: 'max-w-4xl', full: 'max-w-6xl',
}
export function Dialog({ open, onOpenChange, title, description, footer, children,
                         size = 'md', className }: {
  open: boolean; onOpenChange: (v: boolean) => void
  title?: ReactNode; description?: ReactNode; footer?: ReactNode; children: ReactNode
  size?: keyof typeof dialogSizes; className?: string
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onOpenChange(false) }
    document.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = previous }
  }, [open, onOpenChange])

  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-foreground/40 backdrop-blur-sm animate-fade-in" onClick={() => onOpenChange(false)} />
      <div className={cn('relative z-10 flex max-h-[88vh] w-full flex-col overflow-hidden rounded-xl border bg-card shadow-2xl animate-scale-in',
        dialogSizes[size], className)}>
        {(title || description) && (
          <div className="flex items-start justify-between gap-4 border-b px-5 py-4">
            <div className="space-y-1">
              {title && <h2 className="text-base font-semibold tracking-tight">{title}</h2>}
              {description && <p className="text-xs text-muted-foreground">{description}</p>}
            </div>
            <Button variant="ghost" size="icon-sm" onClick={() => onOpenChange(false)} aria-label="Close">
              <X className="h-4 w-4" />
            </Button>
          </div>
        )}
        <div className="scroll-thin flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 border-t bg-muted/30 px-5 py-3">{footer}</div>}
      </div>
    </div>, document.body)
}

export function ConfirmDialog({ open, onOpenChange, title, description, onConfirm,
                                confirmLabel, danger = true, loading }: {
  open: boolean; onOpenChange: (v: boolean) => void; title: string; description?: string
  onConfirm: () => void; confirmLabel?: string; danger?: boolean; loading?: boolean
}) {
  const { t } = useI18n()
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={title} description={description} size="sm"
      footer={<>
        <Button variant="outline" onClick={() => onOpenChange(false)}>{t('common.cancel')}</Button>
        <Button variant={danger ? 'destructive' : 'default'} loading={loading} onClick={onConfirm}>{confirmLabel || t('common.confirm')}</Button>
      </>}>
      <p className="text-sm text-muted-foreground">{description}</p>
    </Dialog>
  )
}

/* -------------------------------------------------------------------------- */
/* Tabs                                                                        */
/* -------------------------------------------------------------------------- */
export function Tabs({ value, onValueChange, items, className }: {
  value: string; onValueChange: (v: string) => void
  items: { value: string; label: ReactNode; icon?: ReactNode; count?: number }[]
  className?: string
}) {
  return (
    <div className={cn('scroll-thin inline-flex max-w-full items-center gap-1 overflow-x-auto rounded-lg border bg-muted/50 p-1', className)}>
      {items.map((item) => (
        <button key={item.value} type="button" onClick={() => onValueChange(item.value)}
          className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition-all',
            value === item.value ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}>
          {item.icon}{item.label}
          {item.count !== undefined && <span className="rounded-full bg-primary/10 px-1.5 text-[10px] text-primary">{item.count}</span>}
        </button>
      ))}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Toasts                                                                      */
/* -------------------------------------------------------------------------- */
type ToastVariant = 'success' | 'error' | 'info'
interface ToastItem { id: number; title: string; description?: string; variant: ToastVariant }
interface ToastValue { toast: (title: string, variant?: ToastVariant, description?: string) => void }
const ToastContext = createContext<ToastValue>({ toast: () => {} })

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const toast = useCallback((title: string, variant: ToastVariant = 'success', description?: string) => {
    const id = Date.now() + Math.random()
    setItems((prev) => [...prev, { id, title, description, variant }])
    setTimeout(() => setItems((prev) => prev.filter((i) => i.id !== id)), 3800)
  }, [])
  const value = useMemo(() => ({ toast }), [toast])
  return (
    <ToastContext.Provider value={value}>
      {children}
      {createPortal(
        <div className="pointer-events-none fixed right-4 top-4 z-[100] flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-2">
          {items.map((i) => (
            <div key={i.id} className="pointer-events-auto flex items-start gap-3 rounded-lg border bg-card p-3 shadow-lg animate-scale-in">
              {i.variant === 'success' && <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />}
              {i.variant === 'error' && <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />}
              {i.variant === 'info' && <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{i.title}</p>
                {i.description && <p className="mt-0.5 break-words text-xs text-muted-foreground">{i.description}</p>}
              </div>
              <button className="text-muted-foreground hover:text-foreground"
                onClick={() => setItems((prev) => prev.filter((x) => x.id !== i.id))}><X className="h-3.5 w-3.5" /></button>
            </div>
          ))}
        </div>, document.body)}
    </ToastContext.Provider>
  )
}
export function useToast() { return useContext(ToastContext) }

/* -------------------------------------------------------------------------- */
/* Dropdown                                                                    */
/* -------------------------------------------------------------------------- */
export function Dropdown({ trigger, items, align = 'right', className }: {
  trigger: ReactNode; items: { label: string; icon?: ReactNode; onClick: () => void; destructive?: boolean; separator?: boolean }[]
  align?: 'left' | 'right'; className?: string
}) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [open])
  return (
    <div className="relative" onClick={(e) => e.stopPropagation()}>
      <div onClick={() => setOpen((v) => !v)}>{trigger}</div>
      {open && (
        <div className={cn('absolute top-full z-40 mt-1.5 min-w-[11rem] overflow-hidden rounded-lg border bg-popover p-1 shadow-lg animate-scale-in',
          align === 'right' ? 'right-0' : 'left-0', className)}>
          {items.map((item, idx) => (
            <div key={idx}>
              {item.separator && <div className="my-1 h-px bg-border" />}
              <button onClick={() => { item.onClick(); setOpen(false) }}
                className={cn('flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs transition-colors hover:bg-accent',
                  item.destructive && 'text-destructive hover:bg-destructive/10')}>
                {item.icon}{item.label}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
