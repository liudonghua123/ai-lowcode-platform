import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ArrowRight, CheckCircle2, ClipboardList, GitBranch, Link2, Loader2,
  LockKeyhole, Send, ShieldAlert, ShieldCheck, Sparkles,
} from 'lucide-react'
import { BrandMark } from '@/components/layout/AppShell'
import { Badge, Button, Card, CardContent } from '@/components/ui/basic'
import { useToast } from '@/components/ui/overlay'
import { SchemaForm } from '@/components/SchemaForm'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { get, post } from '@/lib/api'
import type { FlowTask, ShareInfo, StartSchema } from '@/types'

/**
 * Public, shareable workflow launch page: /#/start/{code}
 *
 * This is the landing target of the auth-gated share URL that the workflow
 * portal copies for integration into other systems. It deliberately has TWO
 * phases:
 *
 *  1. Anonymous — fetch the PUBLIC /workflows/share-info/{code} (no token),
 *     show what the link will launch and explain that sign-in is required.
 *     The CTA goes to /#/login?next=/start/{code}.
 *  2. Authenticated — after the login round-trip the same page fetches the
 *     schema-driven start form and submits /workflows/{id}/start.
 *
 * No business data is exposed before authentication: the public endpoint only
 * returns the workflow name/description/form name, never submissions.
 *
 * Integrating systems may prefill the form via ?data=<base64(json)>, which is
 * useful when the host system already knows the requester / amount / subject.
 */
interface LaunchResult {
  id: number; status: string
  current_nodes?: string[]; pending?: FlowTask[]
  form_code?: string | null
}

/** Decode ?data=<url-safe or standard base64 of a UTF-8 JSON object>. */
function decodePrefill(raw: string | null): Record<string, unknown> {
  if (!raw) return {}
  try {
    const norm = raw.replace(/-/g, '+').replace(/_/g, '/')
    const bin = atob(norm + '='.repeat((4 - (norm.length % 4)) % 4))
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0))
    const obj = JSON.parse(new TextDecoder().decode(bytes))
    return obj && typeof obj === 'object' && !Array.isArray(obj)
      ? obj as Record<string, unknown> : {}
  } catch { return {} }
}

export default function StartWorkflow() {
  const { code = '' } = useParams()
  const { t } = useI18n()
  const { user, can, loading: appLoading } = useApp()
  const { toast } = useToast()
  const navigate = useNavigate()
  const [params] = useSearchParams()

  const [info, setInfo] = useState<ShareInfo | null>(null)
  const [infoError, setInfoError] = useState('')
  const [schema, setSchema] = useState<StartSchema | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<LaunchResult | null>(null)
  const [prefilled, setPrefilled] = useState(false)

  const prefill = useMemo(() => decodePrefill(params.get('data')), [params])

  // Phase 1 — public launch info, no credentials required.
  useEffect(() => {
    let alive = true
    setInfo(null); setInfoError(''); setSchema(null); setResult(null)
    get<ShareInfo>(`/workflows/share-info/${encodeURIComponent(code)}`, { auth: false })
      .then((r) => { if (alive) setInfo(r) })
      .catch((e: any) => { if (alive) setInfoError(String(e?.message || 'Not found')) })
    return () => { alive = false }
  }, [code])

  // Phase 2 — once signed in, load the schema-driven start form.
  useEffect(() => {
    if (!user || !info || appLoading) return
    let alive = true
    setErrors({}); setResult(null)
    get<StartSchema>(`/workflows/${info.workflow_id}/start-schema`)
      .then((r) => {
        if (!alive) return
        setSchema(r)
        if (Object.keys(prefill).length) { setValues({ ...prefill }); setPrefilled(true) }
        else { setValues({}); setPrefilled(false) }
      })
      .catch((e: any) => { if (alive) toast(String(e?.message), 'error') })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, info, appLoading])

  const launch = async () => {
    if (!info || !schema) return
    setSubmitting(true); setErrors({})
    try {
      const r = await post<LaunchResult>(`/workflows/${info.workflow_id}/start`,
        { form_data: values, create_submission: true })
      setResult(r)
      toast(t('startPage.success'), 'success')
    } catch (e: any) {
      const msg = String(e?.message || '')
      const errs: Record<string, string> = {}
      for (const part of msg.split('; ')) {
        const i = part.indexOf(':')
        if (i > 0) errs[part.slice(0, i).trim()] = part.slice(i + 1).trim()
      }
      setErrors(errs); toast(msg, 'error')
    } finally { setSubmitting(false) }
  }

  const goBack = () => navigate('/workflows')
  const reset = () => { setResult(null); setValues({ ...prefill }); setErrors({}) }

  return (
    <div className="relative flex min-h-screen items-center justify-center px-4 py-10">
      <div className="app-bg" />
      <div className="relative w-full max-w-2xl animate-fade-up space-y-4">
        <header className="flex flex-wrap items-center gap-3">
          <BrandMark className="h-9 w-9" />
          <div className="min-w-0">
            <p className="text-sm font-semibold tracking-tight">{t('nav.platform')}</p>
            <p className="text-[11px] text-muted-foreground">{t('startPage.subtitle')}</p>
          </div>
          {user && <Button variant="ghost" size="sm" className="ml-auto gap-1.5" onClick={goBack}>
            {t('startPage.backToPlatform')}<ArrowRight className="h-3.5 w-3.5" /></Button>}
        </header>

        {!info && !infoError && (
          <Card><CardContent className="flex items-center justify-center gap-2 py-14 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />{t('common.loading')}
          </CardContent></Card>
        )}

        {infoError && (
          <Card><CardContent className="space-y-3 py-12 text-center">
            <span className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
              <ShieldAlert className="h-5 w-5" /></span>
            <p className="text-sm font-semibold">{t('startPage.notFound')}</p>
            <p className="text-xs text-muted-foreground">{infoError} · {t('startPage.notFoundHint')}</p>
            <Button variant="outline" size="sm" onClick={() => navigate('/')}>{t('common.back')}</Button>
          </CardContent></Card>
        )}

        {info && (
          <Card className="overflow-hidden">
            <div className="h-1 w-full bg-gradient-to-r from-primary via-cyan-400 to-primary/40" />
            <CardContent className="space-y-4 p-5">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <GitBranch className="h-5 w-5" /></span>
                <div className="min-w-0 flex-1">
                  <h1 className="truncate text-lg font-semibold tracking-tight">{info.name}</h1>
                  <p className="font-mono text-[10px] text-muted-foreground">{info.code}</p>
                </div>
                <Badge variant="outline" className="gap-1 text-[10px]">
                  <LockKeyhole className="h-3 w-3" />{t('portal.authRequired')}</Badge>
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {info.description || '—'}</p>
              <div className="flex flex-wrap gap-1.5">
                {info.form_name && <Badge variant="secondary" className="gap-1 text-[10px]">
                  <ClipboardList className="h-3 w-3" />{t('startPage.boundForm')}: {info.form_name}</Badge>}
                <Badge variant="muted" className="gap-1 text-[10px]">
                  <Link2 className="h-3 w-3" />{t('portal.authRequired')}</Badge>
                {schema?.workflow?.version && <Badge variant="muted" className="text-[10px]">
                  {t('startPage.version')} v{schema.workflow.version}</Badge>}
              </div>

              <div className="border-t pt-4">
                {/* Success */}
                {result && (
                  <div className="space-y-3 animate-scale-in">
                    <div className="flex items-center gap-2.5 rounded-lg border border-success/30 bg-success/5 px-3 py-2.5">
                      <CheckCircle2 className="h-5 w-5 text-success" />
                      <div><p className="text-sm font-semibold">{t('startPage.success')}</p>
                        <p className="text-[11px] text-muted-foreground">{t('startPage.successHint')}</p></div>
                      <Badge variant="success" className="ml-auto font-mono">#{result.id}</Badge>
                    </div>
                    <div className="grid gap-2 rounded-lg border bg-muted/20 p-3 text-xs sm:grid-cols-2">
                      <div><span className="text-muted-foreground">{t('common.status')}: </span>
                        <Badge variant="warning" className="text-[9px]">{result.status}</Badge></div>
                      <div><span className="text-muted-foreground">{t('workflows.instance')}: </span>
                        <span className="font-mono">#{result.id}</span></div>
                      {!!result.current_nodes?.length && <div className="sm:col-span-2">
                        <span className="text-muted-foreground">{t('workflows.currentNodes')}: </span>
                        <span className="font-mono">{result.current_nodes.join(', ')}</span></div>}
                    </div>
                    {!!result.pending?.length && <div className="space-y-1.5">
                      <p className="text-[11px] font-medium">{t('startPage.pendingAt')}</p>
                      {result.pending.map((p) => <div key={p.id}
                        className="flex items-center gap-2 rounded-lg border px-2.5 py-2 text-[11px]">
                        <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                        <span className="min-w-0 flex-1 truncate">{p.node_name}</span>
                        <span className="font-mono text-muted-foreground">{p.assignee}</span>
                      </div>)}
                    </div>}
                    <div className="flex flex-wrap gap-2 pt-1">
                      <Button size="sm" onClick={goBack}>
                        <ClipboardList className="h-3.5 w-3.5" />{t('portal.tabMine')}</Button>
                      <Button variant="outline" size="sm" onClick={reset}>
                        <Sparkles className="h-3.5 w-3.5" />{t('startPage.launchAnother')}</Button>
                    </div>
                  </div>
                )}

                {/* Anonymous — auth gate */}
                {!result && !user && (
                  <div className="space-y-3 animate-fade-up">
                    <div className="flex items-start gap-2.5 rounded-lg border border-primary/25 bg-primary/5 px-3 py-3">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <ShieldCheck className="h-4 w-4" /></span>
                      <div><p className="text-xs font-semibold">{t('startPage.signInRequired')}</p>
                        <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                          {t('startPage.signInHint')}</p></div>
                    </div>
                    <Button className="w-full" onClick={() => {
                      // Preserve ?data= prefill across the sign-in round trip:
                      // backend login_path only carries the bare code, so build
                      // next from the full current hash query instead.
                      const qs = params.toString()
                      const target = `/start/${encodeURIComponent(code)}${qs ? `?${qs}` : ''}`
                      window.location.href = `/#/login?next=${encodeURIComponent(target)}`
                    }}><LockKeyhole className="h-4 w-4" />{t('login.signIn')}
                      <ArrowRight className="h-4 w-4" /></Button>
                    <p className="break-all text-center font-mono text-[10px] text-muted-foreground">
                      {info.share_url}</p>
                  </div>
                )}

                {/* Authenticated — dynamic start form */}
                {!result && user && (
                  <div className="space-y-3">
                    {!schema ? (
                      <div className="flex items-center justify-center gap-2 py-8 text-xs text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />{t('common.loading')}</div>
                    ) : (
                      <>
                        <p className="text-xs text-muted-foreground">{t('workflows.startHint')}</p>
                        {schema.form && <Badge variant="muted" className="text-[10px]">
                          {schema.form.name} · v{schema.form.version}</Badge>}
                        {prefilled && <p className="flex items-center gap-1.5 text-[11px] text-primary">
                          <Sparkles className="h-3 w-3" />{t('startPage.prefilled')}</p>}
                        <SchemaForm fields={schema.fields || []} value={values}
                          onChange={setValues} formId={schema.form?.id}
                          errors={errors} columns={schema.columns || 2} />
                        {!schema.fields?.length && <p className="rounded-lg border bg-muted/20 px-3 py-4 text-center text-xs text-muted-foreground">
                          {schema.hint || t('formFill.noFields')}</p>}
                        {!can('workflow:run') ? (
                          <p className="flex items-center gap-1.5 rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-[11px] text-warning">
                            <ShieldAlert className="h-3.5 w-3.5" />{t('startPage.noPermission')}</p>
                        ) : (
                          <div className="flex flex-wrap gap-2 pt-1">
                            <Button loading={submitting} onClick={() => void launch()}>
                              <Send className="h-3.5 w-3.5" />{t('portal.launch')}</Button>
                            <Button variant="outline" size="sm" onClick={goBack}>
                              {t('common.cancel')}</Button>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        <p className="text-center text-[10px] leading-relaxed text-muted-foreground">
          {info?.note} · {t('settings.license')} · MIT
        </p>
      </div>
    </div>
  )
}
