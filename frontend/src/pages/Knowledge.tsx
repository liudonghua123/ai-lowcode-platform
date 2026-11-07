import { useEffect, useState } from 'react'
import {
  BookOpen, Database, FileText, Layers3, Plus, RefreshCw, Search, Trash2,
  Eye, Pencil, Sparkles,
} from 'lucide-react'
import { PageHeader, SectionTitle } from '@/components/PageHeader'
import {
  Badge, Button, Card, CardContent, EmptyState, Field, Input, Label, Textarea,
} from '@/components/ui/basic'
import { ConfirmDialog, Dialog, Tabs, useToast } from '@/components/ui/overlay'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { del, get, post, put } from '@/lib/api'
import { cn, formatDate } from '@/lib/utils'
import type { KbCollection, KbDocument, RagHit } from '@/types'

export default function Knowledge() {
  const { t, locale } = useI18n()
  const { can } = useApp()
  const { toast } = useToast()
  const [collections, setCollections] = useState<KbCollection[]>([])
  const [documents, setDocuments] = useState<KbDocument[]>([])
  const [selected, setSelected] = useState<KbCollection | null>(null)
  const [activeDoc, setActiveDoc] = useState<KbDocument | null>(null)
  const [rightTab, setRightTab] = useState('search')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('What is the leave approval policy?')
  const [hits, setHits] = useState<RagHit[]>([])
  const [context, setContext] = useState('')
  const [stats, setStats] = useState<any>(null)
  const [collOpen, setCollOpen] = useState(false)
  const [docOpen, setDocOpen] = useState(false)
  const [viewOpen, setViewOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [newColl, setNewColl] = useState({ code: '', name: '', description: '', chunk_size: 480 })
  const [docForm, setDocForm] = useState({ id: 0, title: '', content: '', source: 'manual' })

  const loadCollections = async () => {
    try {
      const r = await get<{ collections: KbCollection[] }>('/knowledge/collections')
      setCollections(r.collections || [])
      if (!selected && r.collections?.length) setSelected(r.collections[0])
      return r.collections || []
    } catch { return [] }
  }
  const loadDocs = async (collectionId?: number) => {
    const cid = collectionId ?? selected?.id
    if (!cid) return
    try { const r = await get<{ documents: KbDocument[] }>(`/knowledge/documents?collection_id=${cid}&q=${encodeURIComponent(search)}`)
      setDocuments(r.documents || []) } catch { setDocuments([]) }
  }
  useEffect(() => { void loadCollections(); get('/knowledge/stats').then(setStats).catch(() => {}) }, [])
  useEffect(() => { if (selected) void loadDocs(selected.id) }, [selected?.id, search])

  const createCollection = async () => {
    try { await post('/knowledge/collections', newColl); setCollOpen(false)
      setNewColl({ code: '', name: '', description: '', chunk_size: 480 }); await loadCollections(); toast(t('common.createdOk'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
  }
  const openDoc = (doc?: KbDocument) => {
    setDocForm(doc ? { id: doc.id, title: doc.title, content: doc.content, source: doc.source || 'manual' }
      : { id: 0, title: '', content: '', source: 'manual' })
    setDocOpen(true)
  }
  const saveDoc = async () => {
    if (!selected) return
    try {
      if (docForm.id) await put(`/knowledge/documents/${docForm.id}`, { title: docForm.title, content: docForm.content, source: docForm.source })
      else await post('/knowledge/documents', { collection_id: selected.id, title: docForm.title, content: docForm.content, source: docForm.source })
      setDocOpen(false); void loadDocs(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const viewDoc = async (id: number) => {
    try { setActiveDoc(await get<KbDocument>(`/knowledge/documents/${id}`)); setViewOpen(true) } catch (e: any) { toast(e.message, 'error') }
  }
  const deleteDoc = async () => {
    if (!activeDoc) return
    try { await del(`/knowledge/documents/${activeDoc.id}`); setViewOpen(false); void loadDocs(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmDelete(false) }
  }
  const reindex = async (id: number) => {
    try { const r: any = await post(`/knowledge/documents/${id}/reindex`, {}); toast(`${t('knowledge.chunks')}: ${r.chunks}`, 'success'); void loadDocs() }
    catch (e: any) { toast(e.message, 'error') }
  }
  const runSearch = async () => {
    try { const r: any = await post('/knowledge/search', { query, collection_ids: selected ? [selected.id] : undefined, top_k: 4 })
      setHits(r.hits || []); setContext(r.context || ''); setRightTab('search') }
    catch (e: any) { toast(e.message, 'error') }
  }

  return (
    <div className="mx-auto max-w-[1600px]">
      <PageHeader icon={<BookOpen className="h-5 w-5" />} title={t('knowledge.title')} subtitle={t('knowledge.subtitle')}
        actions={<>
          <Button variant="outline" size="sm" onClick={() => { void loadCollections(); void loadDocs() }}><RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>
          {can('knowledge:write') && <Button size="sm" onClick={() => setCollOpen(true)}><Plus className="h-4 w-4" />{t('knowledge.newCollection')}</Button>}
        </>} />

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: t('knowledge.collections'), value: stats?.collections ?? '—', icon: <Database className="h-4 w-4" /> },
          { label: t('knowledge.documents'), value: stats?.documents ?? '—', icon: <FileText className="h-4 w-4" /> },
          { label: t('knowledge.chunks'), value: stats?.chunks ?? '—', icon: <Layers3 className="h-4 w-4" /> },
          { label: t('knowledge.retriever'), value: stats?.retriever || 'bm25-local', icon: <Sparkles className="h-4 w-4" /> },
        ].map((s, i) => (
          <Card key={i} className="p-3"><div className="flex items-center gap-2 text-primary">{s.icon}
            <span className="mono-num text-lg font-semibold text-foreground">{s.value}</span></div>
            <p className="mt-1 text-[11px] text-muted-foreground">{s.label}</p></Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[14rem_minmax(0,1fr)_21rem]">
        <Card><CardContent className="p-3">
          <SectionTitle>{t('knowledge.collections')}</SectionTitle>
          <div className="space-y-1">
            {collections.map((c) => (
              <button key={c.id} onClick={() => { setSelected(c); setActiveDoc(null) }}
                className={cn('flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-all',
                  selected?.id === c.id ? 'bg-primary/10 text-primary' : 'hover:bg-muted')}>
                <Database className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium">{c.name}</span>
                  <span className="block text-[10px] text-muted-foreground">{t('knowledge.documentCount', { count: c.document_count ?? 0 })}</span></span>
              </button>
            ))}
          </div>
        </CardContent></Card>

        <Card className="min-h-[30rem]">
          <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
            <div className="min-w-0 flex-1"><h2 className="truncate text-sm font-semibold">{selected?.name || t('knowledge.emptyTitle')}</h2>
              <p className="truncate text-[11px] text-muted-foreground">{selected?.description}</p></div>
            <Input className="h-8 w-40 text-xs" placeholder={t('common.searchPlaceholder')} value={search} onChange={(e) => setSearch(e.target.value)} />
            {can('knowledge:write') && <Button size="sm" onClick={() => openDoc()} disabled={!selected}><Plus className="h-3.5 w-3.5" />{t('knowledge.newDocument')}</Button>}
          </div>
          <CardContent className="p-3">
            {!selected ? <EmptyState icon={<BookOpen className="h-5 w-5" />} title={t('knowledge.emptyTitle')} description={t('knowledge.emptyText')} /> :
              <div className="space-y-2">
                {documents.map((d) => (
                  <div key={d.id} className="group rounded-lg border p-3 transition-all hover:border-primary/40 hover:bg-muted/30">
                    <div className="flex items-start gap-2">
                      <FileText className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium">{d.title}</p>
                        <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">{d.content_preview || d.content?.slice(0, 160)}</p>
                        <div className="mt-2 flex items-center gap-2 text-[10px] text-muted-foreground">
                          <Badge variant="muted">{d.status}</Badge><span>{t('knowledge.chunks')}: {d.chunk_count ?? 0}</span>
                          <span>·</span><span>{formatDate(d.created_at, locale)}</span>
                        </div>
                      </div>
                      <div className="flex shrink-0 gap-0.5 opacity-60 transition-opacity group-hover:opacity-100">
                        <Button variant="ghost" size="icon-sm" onClick={() => void viewDoc(d.id)}><Eye className="h-3 w-3" /></Button>
                        <Button variant="ghost" size="icon-sm" onClick={() => void openDoc(d)} disabled={!can('knowledge:write')}><Pencil className="h-3 w-3" /></Button>
                        <Button variant="ghost" size="icon-sm" onClick={() => void reindex(d.id)} disabled={!can('knowledge:write')}><RefreshCw className="h-3 w-3" /></Button>
                      </div>
                    </div>
                  </div>
                ))}
                {!documents.length && <p className="py-12 text-center text-xs text-muted-foreground">{t('common.noData')}</p>}
              </div>}
          </CardContent>
        </Card>

        <Card className="h-fit"><CardContent className="p-3">
          <Tabs value={rightTab} onValueChange={setRightTab} className="mb-3 w-full" items={[
            { value: 'search', label: t('knowledge.searchTest') }, { value: 'stats', label: t('knowledge.stats') },
          ]} />
          {rightTab === 'search' && <div className="space-y-3">
            <div className="flex gap-1.5">
              <Input className="h-8 text-xs" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('knowledge.searchPlaceholder')}
                onKeyDown={(e) => e.key === 'Enter' && void runSearch()} />
              <Button size="icon-sm" onClick={runSearch}><Search className="h-3.5 w-3.5" /></Button>
            </div>
            <p className="text-[10px] text-muted-foreground">{t('knowledge.hits')}: {hits.length}</p>
            <div className="scroll-thin max-h-[22rem] space-y-2 overflow-y-auto">
              {hits.map((h, i) => (
                <div key={i} className="rounded-lg border p-2.5">
                  <div className="flex items-start gap-2"><span className="font-mono text-[10px] text-primary">[{i + 1}]</span>
                    <span className="min-w-0 flex-1 truncate text-xs font-medium">{h.title}</span>
                    <Badge variant="secondary" className="mono-num text-[9px]">{h.score}</Badge></div>
                  <p className="mt-1.5 line-clamp-3 text-[11px] leading-relaxed text-muted-foreground">{h.snippet}</p>
                  <p className="mt-1 text-[9px] text-muted-foreground">{h.collection}</p>
                </div>
              ))}
              {!hits.length && <p className="py-10 text-center text-xs text-muted-foreground">{t('knowledge.noHits')}</p>}
            </div>
            {context && <details className="rounded-lg border p-2.5"><summary className="cursor-pointer text-xs font-medium">{t('knowledge.context')}</summary>
              <pre className="scroll-thin mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-muted-foreground">{context}</pre></details>}
          </div>}
          {rightTab === 'stats' && <div className="space-y-2 text-xs">
            {Object.entries(stats || {}).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between rounded-md border px-2.5 py-2">
                <span className="text-muted-foreground">{k}</span><span className="mono-num font-medium">{String(v)}</span>
              </div>
            ))}
          </div>}
        </CardContent></Card>
      </div>

      <Dialog open={collOpen} onOpenChange={setCollOpen} title={t('knowledge.newCollection')}
        footer={<><Button variant="outline" onClick={() => setCollOpen(false)}>{t('common.cancel')}</Button><Button onClick={createCollection}>{t('common.create')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('knowledge.collectionCode')}><Input value={newColl.code} onChange={(e) => setNewColl({ ...newColl, code: e.target.value })} placeholder="my_kb" /></Field>
          <Field label={t('knowledge.collectionName')}><Input value={newColl.name} onChange={(e) => setNewColl({ ...newColl, name: e.target.value })} /></Field>
          <Field label={t('common.description')}><Textarea value={newColl.description} onChange={(e) => setNewColl({ ...newColl, description: e.target.value })} /></Field>
          <Field label={t('knowledge.chunkSize')}><Input type="number" value={newColl.chunk_size} onChange={(e) => setNewColl({ ...newColl, chunk_size: Number(e.target.value) })} /></Field>
        </div>
      </Dialog>

      <Dialog open={docOpen} onOpenChange={setDocOpen} title={docForm.id ? t('knowledge.editDocument') : t('knowledge.createDocument')} size="lg"
        footer={<><Button variant="outline" onClick={() => setDocOpen(false)}>{t('common.cancel')}</Button><Button onClick={saveDoc}>{t('common.save')}</Button></>}>
        <div className="space-y-3">
          <Field label={t('knowledge.docTitle')}><Input value={docForm.title} onChange={(e) => setDocForm({ ...docForm, title: e.target.value })} /></Field>
          <Field label={t('knowledge.content')}><Textarea rows={10} value={docForm.content} onChange={(e) => setDocForm({ ...docForm, content: e.target.value })} /></Field>
          <Field label={t('knowledge.source')}><Input value={docForm.source} onChange={(e) => setDocForm({ ...docForm, source: e.target.value })} /></Field>
        </div>
      </Dialog>

      <Dialog open={viewOpen} onOpenChange={setViewOpen} title={activeDoc?.title || ''} size="lg"
        footer={<><Button variant="outline" onClick={() => setViewOpen(false)}>{t('common.close')}</Button>
          <Button variant="destructive" onClick={() => setConfirmDelete(true)} disabled={!can('knowledge:write')}><Trash2 className="h-3.5 w-3.5" />{t('common.delete')}</Button></>}>
        <div className="space-y-3">
          <div className="flex gap-2 text-[11px] text-muted-foreground"><Badge variant="muted">{activeDoc?.status}</Badge>
            <span>{t('knowledge.chunks')}: {activeDoc?.chunks?.length ?? 0}</span><span>·</span><span>{activeDoc?.source}</span></div>
          <pre className="scroll-thin max-h-80 whitespace-pre-wrap rounded-lg border bg-muted/30 p-3 text-xs leading-relaxed">{activeDoc?.content}</pre>
        </div>
      </Dialog>
      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} title={t('common.confirmDelete')} onConfirm={deleteDoc} />
    </div>
  )
}
