import { Navigate, Route, Routes, useSearchParams } from 'react-router-dom'
import { AppShell, BrandMark } from '@/components/layout/AppShell'
import { useApp } from '@/store/AppContext'
import Login from '@/pages/Login'
import SsoCallback from '@/pages/SsoCallback'
import StartWorkflow from '@/pages/StartWorkflow'
import Dashboard from '@/pages/Dashboard'
import Forms from '@/pages/Forms'
import Workflows from '@/pages/Workflows'
import Knowledge from '@/pages/Knowledge'
import Agents from '@/pages/Agents'
import McpServers from '@/pages/McpServers'
import Skills from '@/pages/Skills'
import ModelProviders from '@/pages/ModelProviders'
import Rbac from '@/pages/Rbac'
import AuthSettings from '@/pages/AuthSettings'
import Audit from '@/pages/Audit'
import Settings from '@/pages/Settings'

/** Only allow in-app relative redirects (blocks //evil.com open redirects). */
export function safeNext(raw: string | null): string {
  return raw && raw.startsWith('/') && !raw.startsWith('//') ? raw : '/'
}

/**
 * A share link (/start/{code}) sends anonymous users here with ?next=. Once a
 * session exists we bounce straight back to that target instead of "/", which
 * completes the "share URL -> sign in -> return to start form" round trip.
 */
function LoginRoute() {
  const { user } = useApp()
  const [params] = useSearchParams()
  if (!user) return <Login />
  return <Navigate to={safeNext(params.get('next'))} replace />
}

function Splash() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4">
      <div className="app-bg" />
      <div className="relative">
        <span className="absolute inset-0 animate-pulse-ring rounded-xl bg-primary/20" />
        <BrandMark className="relative h-12 w-12 animate-float-slow" />
      </div>
      <p className="text-sm text-muted-foreground">AI Low-Code Platform</p>
    </div>
  )
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/forms" element={<Forms />} />
      <Route path="/workflows" element={<Workflows />} />
      <Route path="/knowledge" element={<Knowledge />} />
      <Route path="/agents" element={<Agents />} />
      <Route path="/mcp" element={<McpServers />} />
      <Route path="/skills" element={<Skills />} />
      <Route path="/models" element={<ModelProviders />} />
      <Route path="/rbac" element={<Rbac />} />
      <Route path="/auth" element={<AuthSettings />} />
      <Route path="/audit" element={<Audit />} />
      <Route path="/settings" element={<Settings />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  const { user, loading } = useApp()
  if (loading) return <Splash />
  return (
    <Routes>
      <Route path="/login" element={<LoginRoute />} />
      <Route path="/sso/callback" element={<SsoCallback />} />
      {/* Public, auth-gated share landing: renders for anonymous users too. */}
      <Route path="/start/:code" element={<StartWorkflow />} />
      <Route path="/*" element={user ? <AppShell><AppRoutes /></AppShell> : <Navigate to="/login" replace />} />
    </Routes>
  )
}
