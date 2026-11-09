import { useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import {
  BookOpen, Bot, ChevronDown, Cpu, ExternalLink, FileText, GitBranch, LayoutDashboard,
  LogOut, Menu, Monitor, Moon, Package, ScrollText, Server, Settings2, ShieldCheck,
  Sun, User, UsersRound, X, Languages, Sparkles,
} from 'lucide-react'
import { useI18n } from '@/i18n'
import { useTheme } from '@/theme/ThemeProvider'
import { useApp } from '@/store/AppContext'
import { cn } from '@/lib/utils'
import { Avatar, Badge, Button } from '@/components/ui/basic'
import { Dropdown, useToast } from '@/components/ui/overlay'
import { NotificationBell } from './NotificationBell'

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={cn('h-8 w-8', className)} aria-hidden="true">
      <defs>
        <linearGradient id="brandGrad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="hsl(243 75% 60%)" />
          <stop offset="100%" stopColor="hsl(190 85% 52%)" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="38" height="38" rx="11" fill="url(#brandGrad)" />
      <g stroke="white" strokeWidth="1.8" strokeLinecap="round" opacity=".92">
        <path d="M12 13h6M18 13v14M18 20h9M18 27h9" fill="none" />
      </g>
      <g fill="white">
        <circle cx="11" cy="13" r="2.6" /><circle cx="28" cy="20" r="2.6" /><circle cx="28" cy="27" r="2.6" />
      </g>
      <circle cx="18" cy="13" r="2.2" fill="white" opacity=".8" />
    </svg>
  )
}

interface NavItem { to: string; icon: ReactNode; key: string; perm: string }

export function AppShell({ children }: { children: ReactNode }) {
  const { t, locale, setLocale } = useI18n()
  const { theme, setTheme } = useTheme()
  const { user, can, logout } = useApp()
  const location = useLocation()
  const navigate = useNavigate()
  const { toast } = useToast()
  const [mobileOpen, setMobileOpen] = useState(false)

  const groups: { key: string; items: NavItem[] }[] = [
    { key: 'nav.workspace', items: [
      { to: '/', icon: <LayoutDashboard className="h-4 w-4" />, key: 'nav.dashboard', perm: 'dashboard:view' },
      { to: '/profile', icon: <User className="h-4 w-4" />, key: 'nav.profile', perm: '' },
    ] },
    { key: 'nav.build', items: [
      { to: '/forms', icon: <FileText className="h-4 w-4" />, key: 'nav.forms', perm: 'form:read' },
      { to: '/workflows', icon: <GitBranch className="h-4 w-4" />, key: 'nav.workflows', perm: 'workflow:read' },
    ] },
    { key: 'nav.intelligence', items: [
      { to: '/knowledge', icon: <BookOpen className="h-4 w-4" />, key: 'nav.knowledge', perm: 'knowledge:read' },
      { to: '/agents', icon: <Bot className="h-4 w-4" />, key: 'nav.agents', perm: 'agent:read' },
      { to: '/mcp', icon: <Server className="h-4 w-4" />, key: 'nav.mcp', perm: 'mcp:read' },
      { to: '/skills', icon: <Package className="h-4 w-4" />, key: 'nav.skills', perm: 'mcp:read' },
      { to: '/models', icon: <Cpu className="h-4 w-4" />, key: 'nav.models', perm: 'mcp:read' },
    ] },
    { key: 'nav.governance', items: [
      { to: '/rbac', icon: <UsersRound className="h-4 w-4" />, key: 'nav.rbac', perm: 'rbac:read' },
      { to: '/auth', icon: <ShieldCheck className="h-4 w-4" />, key: 'nav.auth', perm: 'auth:config' },
      { to: '/audit', icon: <ScrollText className="h-4 w-4" />, key: 'nav.audit', perm: 'audit:read' },
      { to: '/settings', icon: <Settings2 className="h-4 w-4" />, key: 'nav.settings', perm: '' },
    ] },
  ]

  const current = groups.flatMap((g) => g.items).find((i) =>
    i.to === '/' ? location.pathname === '/' : location.pathname.startsWith(i.to))

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2.5 border-b px-4 py-4">
        <BrandMark />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-tight">{t('nav.platform')}</p>
          <p className="text-[10px] text-muted-foreground">{t('nav.version')} · MIT</p>
        </div>
        <Button variant="ghost" size="icon-sm" className="ml-auto lg:hidden" onClick={() => setMobileOpen(false)}><X className="h-4 w-4" /></Button>
      </div>

      <nav className="scroll-thin flex-1 overflow-y-auto px-2.5 py-4">
        {groups.map((group) => {
          const items = group.items.filter((i) => !i.perm || can(i.perm))
          if (!items.length) return null
          return (
            <div key={group.key} className="mb-4">
              <p className="mb-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">{t(group.key)}</p>
              <div className="space-y-0.5">
                {items.map((item) => {
                  const active = current?.to === item.to
                  return (
                    <Link key={item.to} to={item.to} onClick={() => setMobileOpen(false)}
                      className={cn('group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-all',
                        active ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground')}>
                      {active && <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r-full bg-primary" />}
                      {item.icon}
                      <span className="truncate">{t(item.key)}</span>
                    </Link>
                  )
                })}
              </div>
            </div>
          )
        })}
      </nav>

      <div className="border-t px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute h-full w-full animate-pulse-ring rounded-full bg-success" />
              <span className="relative h-1.5 w-1.5 rounded-full bg-success" />
            </span>
            {t('nav.online')}
          </span>
          <span className="font-mono text-[10px] text-muted-foreground/70">/mcp</span>
        </div>
      </div>
    </div>
  )

  return (
    <div className="flex min-h-screen">
      <div className="app-bg" />
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 border-r bg-card/70 backdrop-blur-xl lg:block">{sidebar}</aside>
      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-foreground/40 backdrop-blur-sm animate-fade-in" onClick={() => setMobileOpen(false)} />
          <aside className="relative h-full w-64 border-r bg-card shadow-2xl animate-scale-in">{sidebar}</aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b bg-background/80 px-3 backdrop-blur-xl sm:px-5">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileOpen(true)}><Menu className="h-5 w-5" /></Button>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">{current ? t(current.key) : t('nav.platform')}</p>
            <p className="hidden truncate text-[11px] text-muted-foreground sm:block">
              {user?.display_name || user?.username} · {user?.role_codes?.join(', ')}
            </p>
          </div>

          <a href="/docs" target="_blank" rel="noreferrer"
            className="hidden items-center gap-1 rounded-md px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground sm:inline-flex">
            API <ExternalLink className="h-3 w-3" />
          </a>

          <NotificationBell />

          <Button variant="ghost" size="sm" className="gap-1.5 px-2" title={t('common.language')}
            onClick={() => setLocale(locale === 'en' ? 'zh' : 'en')}>
            <Languages className="h-4 w-4" /><span className="hidden sm:inline">{locale === 'en' ? 'EN' : '中文'}</span>
          </Button>

          <Dropdown align="right" trigger={
            <Button variant="ghost" size="icon" title={t('common.theme')}>
              {theme === 'light' ? <Sun className="h-4 w-4" /> : theme === 'dark' ? <Moon className="h-4 w-4" /> : <Monitor className="h-4 w-4" />}
            </Button>
          } items={[
            { label: t('common.system'), icon: <Monitor className="h-3.5 w-3.5" />, onClick: () => setTheme('system') },
            { label: t('common.light'), icon: <Sun className="h-3.5 w-3.5" />, onClick: () => setTheme('light') },
            { label: t('common.dark'), icon: <Moon className="h-3.5 w-3.5" />, onClick: () => setTheme('dark') },
          ]} />

          <div className="mx-1 hidden h-5 w-px bg-border sm:block" />

          <Dropdown align="right" trigger={
            <button className="focus-ring flex items-center gap-2 rounded-lg px-1.5 py-1 transition-colors hover:bg-accent">
              <Avatar name={user?.display_name || user?.username} className="h-7 w-7" />
              <ChevronDown className="hidden h-3 w-3 text-muted-foreground sm:block" />
            </button>
          } items={[
            { label: t('nav.settings'), icon: <Settings2 className="h-3.5 w-3.5" />, onClick: () => navigate('/settings') },
            { label: t('common.copy') + ' JWT', icon: <Sparkles className="h-3.5 w-3.5" />, onClick: async () => {
              try { await navigator.clipboard.writeText(localStorage.getItem('ailp_token') || ''); toast(t('common.copied'), 'success') }
              catch { toast(t('common.operationFailed'), 'error') }
            } },
            { label: t('nav.logout'), icon: <LogOut className="h-3.5 w-3.5" />, destructive: true, separator: true,
              onClick: () => { logout(); navigate('/login') } },
          ]} />
        </header>

        <main className="min-w-0 flex-1 px-3 py-5 sm:px-6 sm:py-6">{children}</main>

        <footer className="flex flex-wrap items-center justify-between gap-2 border-t px-5 py-3 text-[11px] text-muted-foreground">
          <span>{t('nav.platform')} · {t('settings.license')}</span>
          <span className="font-mono">FastAPI · fastmcp · AgentScope · Vite · shadcn/ui</span>
        </footer>
      </div>
    </div>
  )
}

export function RoleBadge({ roles }: { roles?: string[] }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {(roles || []).map((r) => <Badge key={r} variant="secondary" className="capitalize">{r}</Badge>)}
    </span>
  )
}
