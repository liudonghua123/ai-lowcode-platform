import { cva, type VariantProps } from 'class-variance-authority'
import { ChevronDown } from 'lucide-react'
import type {
  ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode,
  SelectHTMLAttributes, TextareaHTMLAttributes,
} from 'react'
import { cn } from '@/lib/utils'

export const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all duration-200 focus-ring disabled:pointer-events-none disabled:opacity-50 active:scale-[.98] [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground shadow-sm hover:bg-primary/90 hover:shadow-md',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        outline: 'border border-input bg-background/60 hover:bg-accent hover:text-accent-foreground',
        ghost: 'hover:bg-accent hover:text-accent-foreground',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        success: 'bg-success text-success-foreground hover:bg-success/90',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-9 px-4 py-2',
        sm: 'h-8 rounded-md px-3 text-xs',
        lg: 'h-11 rounded-lg px-6',
        icon: 'h-9 w-9 p-0',
        'icon-sm': 'h-7 w-7 p-0',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  loading?: boolean
}
export function Button({ className, variant, size, loading, disabled, children, ...props }: ButtonProps) {
  return (
    <button className={cn(buttonVariants({ variant, size }), className)} disabled={disabled || loading} {...props}>
      {loading && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  )
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input className={cn(
      'flex h-9 w-full rounded-md border border-input bg-background/70 px-3 py-1 text-sm shadow-sm transition-colors',
      'placeholder:text-muted-foreground focus-ring focus-visible:border-primary/50 disabled:cursor-not-allowed disabled:opacity-50',
      className)} {...props} />
  )
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea className={cn(
      'flex min-h-[80px] w-full rounded-md border border-input bg-background/70 px-3 py-2 text-sm shadow-sm transition-colors',
      'placeholder:text-muted-foreground focus-ring focus-visible:border-primary/50', className)} {...props} />
  )
}

export function Label({ className, children, ...props }: HTMLAttributes<HTMLLabelElement>) {
  return <label className={cn('text-xs font-medium text-muted-foreground', className)} {...props}>{children}</label>
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-lg border bg-card text-card-foreground shadow-soft', className)} {...props} />
}
export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex flex-col gap-1 p-5 pb-3', className)} {...props} />
}
export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn('text-base font-semibold leading-none tracking-tight', className)} {...props} />
}
export function CardDescription({ className, ...props }: HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn('text-sm text-muted-foreground', className)} {...props} />
}
export function CardContent({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-5 pt-0', className)} {...props} />
}
export function CardFooter({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex items-center gap-2 p-5 pt-0', className)} {...props} />
}

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-tight transition-colors',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary/10 text-primary',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        outline: 'border-border bg-transparent text-foreground',
        success: 'border-transparent bg-success/15 text-success',
        warning: 'border-transparent bg-warning/20 text-warning',
        destructive: 'border-transparent bg-destructive/10 text-destructive',
        muted: 'border-transparent bg-muted text-muted-foreground',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)
export function Badge({ className, variant, ...props }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export function Switch({ checked, onCheckedChange, disabled, className }: {
  checked: boolean; onCheckedChange?: (v: boolean) => void; disabled?: boolean; className?: string
}) {
  return (
    <button type="button" role="switch" aria-checked={checked} disabled={disabled}
      onClick={() => onCheckedChange?.(!checked)}
      className={cn('relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border-2 border-transparent transition-colors focus-ring disabled:opacity-50',
        checked ? 'bg-primary' : 'bg-input', className)}>
      <span className={cn('pointer-events-none block h-4 w-4 rounded-full bg-background shadow-sm ring-0 transition-transform',
        checked ? 'translate-x-4' : 'translate-x-0')} />
    </button>
  )
}

export interface SelectOption { value: string; label: string }
export function Select({ value, onValueChange, options, placeholder, className, disabled, ...props }: {
  value?: string; onValueChange?: (v: string) => void; options: SelectOption[]
  placeholder?: string; className?: string; disabled?: boolean
} & Omit<SelectHTMLAttributes<HTMLSelectElement>, 'value' | 'onChange' | 'options'>) {
  return (
    <div className={cn('relative', className)}>
      <select value={value ?? ''} disabled={disabled}
        onChange={(e) => onValueChange?.(e.target.value)}
        className="h-9 w-full appearance-none rounded-md border border-input bg-background/70 pl-3 pr-8 text-sm shadow-sm transition-colors focus-ring focus-visible:border-primary/50 disabled:opacity-50"
        {...props}>
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
    </div>
  )
}

export function Separator({ className, vertical = false }: { className?: string; vertical?: boolean }) {
  return <div className={cn('bg-border', vertical ? 'h-full w-px' : 'h-px w-full', className)} />
}

export function Progress({ value = 0, className }: { value?: number; className?: string }) {
  return (
    <div className={cn('h-1.5 w-full overflow-hidden rounded-full bg-secondary', className)}>
      <div className="h-full rounded-full bg-primary transition-all duration-500" style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-md bg-muted', className)} />
}

export function Avatar({ name, className, src }: { name?: string; className?: string; src?: string }) {
  const text = (name || '?').trim().split(/[\s/]+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join('').toUpperCase()
  return (
    <div className={cn('flex h-8 w-8 items-center justify-center overflow-hidden rounded-full bg-primary/10 text-xs font-semibold text-primary', className)}>
      {src ? <img src={src} alt="" className="h-full w-full object-cover" /> : text}
    </div>
  )
}

export function Field({ label, hint, children, className }: {
  label?: ReactNode; hint?: ReactNode; children: ReactNode; className?: string
}) {
  return (
    <div className={cn('space-y-1.5', className)}>
      {label && <Label className="block">{label}</Label>}
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  )
}

export function Segmented<T extends string>({ value, onChange, options, className }: {
  value: T; onChange: (v: T) => void
  options: { value: T; label: ReactNode; icon?: ReactNode }[]; className?: string
}) {
  return (
    <div className={cn('inline-flex items-center gap-0.5 rounded-lg border bg-muted/60 p-0.5', className)}>
      {options.map((o) => (
        <button key={o.value} type="button" onClick={() => onChange(o.value)}
          className={cn('inline-flex h-7 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition-all',
            value === o.value ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}>
          {o.icon}{o.label}
        </button>
      ))}
    </div>
  )
}

export function EmptyState({ icon, title, description, action, className }: {
  icon?: ReactNode; title: string; description?: string; action?: ReactNode; className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-2 px-6 py-14 text-center', className)}>
      {icon && <div className="mb-1 flex h-12 w-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">{icon}</div>}
      <p className="text-sm font-medium">{title}</p>
      {description && <p className="max-w-sm text-xs text-muted-foreground">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}
