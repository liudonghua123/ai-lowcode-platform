import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function StatCard({ icon, label, value, hint, accent, className }: {
  icon: ReactNode; label: string; value: ReactNode; hint?: ReactNode
  accent?: string; className?: string
}) {
  return (
    <div className={cn('glass-card card-hover group relative overflow-hidden p-4 animate-fade-up', className)}>
      <div className="absolute -right-6 -top-6 h-20 w-20 rounded-full opacity-0 blur-2xl transition-opacity duration-500 group-hover:opacity-100"
        style={{ background: accent || 'hsl(var(--primary) / .25)' }} />
      <div className="flex items-start justify-between gap-2">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg border bg-background/60 text-primary shadow-sm">{icon}</div>
        {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
      </div>
      <div className="mt-3">
        <p className="mono-num text-2xl font-semibold tracking-tight">{value}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{label}</p>
      </div>
    </div>
  )
}

export function ActivityChart({ values, labels }: { values: number[]; labels?: string[] }) {
  const max = Math.max(...values, 1)
  const w = 560, h = 140, pad = 8
  const points = values.map((v, i) => {
    const x = pad + (i * (w - pad * 2)) / Math.max(values.length - 1, 1)
    const y = h - pad - (v / max) * (h - pad * 2 - 14)
    return [x, y] as const
  })
  const line = points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')
  const area = `${line} L ${points[points.length - 1]?.[0] ?? 0} ${h - pad} L ${points[0]?.[0] ?? 0} ${h - pad} Z`
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-36 w-full" preserveAspectRatio="none" role="img" aria-label="Activity chart">
      <defs>
        <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.28" />
          <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="chartLine" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="hsl(var(--primary))" />
          <stop offset="100%" stopColor="hsl(190 85% 50%)" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((f) => (
        <line key={f} x1="0" x2={w} y1={h * f} y2={h * f} stroke="hsl(var(--border))" strokeDasharray="4 5" strokeWidth="1" />
      ))}
      <path d={area} fill="url(#chartFill)" />
      <path d={line} fill="none" stroke="url(#chartLine)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      {points.map(([x, y], i) => (
        <g key={i}>
          <circle cx={x} cy={y} r="3" fill="hsl(var(--card))" stroke="hsl(var(--primary))" strokeWidth="2" />
          {labels?.[i] && <text x={x} y={h - 1} textAnchor="middle" fontSize="9" fill="hsl(var(--muted-foreground))">{labels[i]}</text>}
        </g>
      ))}
    </svg>
  )
}

export function DonutRing({ value, max = 100, label, sub }: {
  value: number; max?: number; label: string; sub?: string
}) {
  const pct = Math.min(1, max ? value / max : 0)
  const r = 38, c = 2 * Math.PI * r
  return (
    <div className="flex items-center gap-4">
      <div className="relative h-24 w-24 shrink-0">
        <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
          <circle cx="50" cy="50" r={r} fill="none" stroke="hsl(var(--secondary))" strokeWidth="9" />
          <circle cx="50" cy="50" r={r} fill="none" stroke="hsl(var(--primary))" strokeWidth="9"
            strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - pct)}
            style={{ transition: 'stroke-dashoffset .8s cubic-bezier(.22,1,.36,1)' }} />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="mono-num text-lg font-semibold">{Math.round(pct * 100)}%</span>
        </div>
      </div>
      <div>
        <p className="text-sm font-medium">{label}</p>
        {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
      </div>
    </div>
  )
}

export function StatusDot({ ok = true, label }: { ok?: boolean; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className="relative flex h-2 w-2">
        <span className={cn('absolute inline-flex h-full w-full rounded-full opacity-60 animate-pulse-ring',
          ok ? 'bg-success' : 'bg-destructive')} />
        <span className={cn('relative inline-flex h-2 w-2 rounded-full', ok ? 'bg-success' : 'bg-destructive')} />
      </span>
      {label}
    </span>
  )
}
