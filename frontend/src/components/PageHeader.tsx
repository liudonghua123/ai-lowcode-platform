import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function PageHeader({ title, subtitle, actions, icon, className }: {
  title: string; subtitle?: string; actions?: ReactNode; icon?: ReactNode; className?: string
}) {
  return (
    <div className={cn('mb-5 flex flex-wrap items-end justify-between gap-3 animate-fade-up', className)}>
      <div className="flex items-start gap-3">
        {icon && <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg border bg-card/70 text-primary shadow-sm">{icon}</div>}
        <div>
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
          {subtitle && <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function SectionTitle({ children, right, className }: {
  children: ReactNode; right?: ReactNode; className?: string
}) {
  return (
    <div className={cn('mb-3 flex items-center justify-between gap-2', className)}>
      <h2 className="text-sm font-semibold tracking-tight">{children}</h2>
      {right}
    </div>
  )
}
