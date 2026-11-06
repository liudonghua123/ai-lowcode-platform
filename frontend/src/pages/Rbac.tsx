import { useEffect, useState } from 'react'
import {
  Check, Fingerprint, KeyRound, LockKeyhole, Pencil, Plus, RefreshCw,
  ShieldCheck, Trash2, UsersRound,
} from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import {
  Badge, Button, Card, CardContent, Field, Field as F, Input, Label, Select, Switch,
} from '@/components/ui/basic'
import { ConfirmDialog, Dialog, Tabs, useToast } from '@/components/ui/overlay'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useI18n } from '@/i18n'
import { useApp } from '@/store/AppContext'
import { del, get, post, put } from '@/lib/api'
import { cn, formatDate } from '@/lib/utils'
import type { Permission, Role, User } from '@/types'

export default function Rbac() {
  const { t, locale } = useI18n()
  const { user: currentUser, can } = useApp()
  const { toast } = useToast()
  const [tab, setTab] = useState('users')
  const [users, setUsers] = useState<User[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [permissions, setPermissions] = useState<Permission[]>([])
  const [userOpen, setUserOpen] = useState(false)
  const [roleOpen, setRoleOpen] = useState(false)
  const [resetOpen, setResetOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<{ kind: string; id: number } | null>(null)
  const [userForm, setUserForm] = useState<any>({ id: 0, username: '', password: '', email: '', display_name: '', dept: '', role_ids: [], status: 'active' })
  const [roleForm, setRoleForm] = useState<any>({ id: 0, code: '', name: '', description: '', permission_ids: [], mfa_required: false })
  const [resetPwd, setResetPwd] = useState('')

  const load = async () => {
    try {
      const [u, r, p, m] = await Promise.all([
        get<{ users: User[] }>('/rbac/users'), get<{ roles: Role[] }>('/rbac/roles'),
        get<{ permissions: Permission[] }>('/rbac/permissions'), get<any>('/rbac/matrix'),
      ])
      setUsers(u.users || []); setRoles(r.roles || []); setPermissions(p.permissions || [])
      void m
    } catch (e: any) { toast(e.message, 'error') }
  }
  useEffect(() => { void load() }, [])

  const openUser = (u?: User) => {
    setUserForm(u ? { id: u.id, username: u.username, password: '', email: u.email || '', display_name: u.display_name || '',
      dept: u.dept || '', role_ids: u.role_ids || [], status: u.status, provider: u.provider }
      : { id: 0, username: '', password: '', email: '', display_name: '', dept: '', role_ids: [], status: 'active' })
    setUserOpen(true)
  }
  const saveUser = async () => {
    const payload: any = { ...userForm }
    delete payload.id; delete payload.provider
    if (!payload.password) delete payload.password
    try {
      if (userForm.id) await put(`/rbac/users/${userForm.id}`, payload)
      else await post('/rbac/users', payload)
      setUserOpen(false); await load(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const openRole = (r?: Role) => {
    setRoleForm(r ? { id: r.id, code: r.code, name: r.name, description: r.description || '',
      permission_ids: r.permission_ids || [], mfa_required: r.mfa_required }
      : { id: 0, code: '', name: '', description: '', permission_ids: [], mfa_required: false })
    setRoleOpen(true)
  }
  const saveRole = async () => {
    const payload: any = { ...roleForm }; delete payload.id
    if (roleForm.id) delete payload.code
    try {
      if (roleForm.id) await put(`/rbac/roles/${roleForm.id}`, payload)
      else await post('/rbac/roles', payload)
      setRoleOpen(false); await load(); toast(t('common.saved'), 'success')
    } catch (e: any) { toast(e.message, 'error') }
  }
  const togglePermission = async (role: Role, permissionId: number) => {
    if (role.code === 'admin') { toast(t('rbac.adminAll'), 'info'); return }
    const next = role.permission_ids.includes(permissionId)
      ? role.permission_ids.filter((x) => x !== permissionId) : [...role.permission_ids, permissionId]
    try { await put(`/rbac/roles/${role.id}`, { permission_ids: next })
      setRoles((prev) => prev.map((r) => r.id === role.id ? { ...r, permission_ids: next } : r)) }
    catch (e: any) { toast(e.message, 'error') }
  }
  const toggleMfa = async (role: Role) => {
    try { await put(`/rbac/roles/${role.id}`, { mfa_required: !role.mfa_required }); await load() }
    catch (e: any) { toast(e.message, 'error') }
  }
  const remove = async () => {
    if (!confirmDelete) return
    try { await del(`/rbac/${confirmDelete.kind === 'user' ? 'users' : 'roles'}/${confirmDelete.id}`)
      await load(); toast(t('common.deleted'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
    finally { setConfirmDelete(null) }
  }
  const resetPassword = async () => {
    try { await post(`/rbac/users/${userForm.id}/reset-password`, { password: resetPwd })
      setResetOpen(false); setResetPwd(''); toast(t('common.saved'), 'success') }
    catch (e: any) { toast(e.message, 'error') }
  }
  const roleName = (id: number) => roles.find((r) => r.id === id)?.code || `#${id}`
  const grouped = permissions.reduce<Record<string, Permission[]>>((acc, p) => {
    (acc[p.resource] ||= []).push(p); return acc
  }, {})

  return (
    <div className="mx-auto max-w-[1500px]">
      <PageHeader icon={<UsersRound className="h-5 w-5" />} title={t('rbac.title')} subtitle={t('rbac.subtitle')}
        actions={<>
          <Button variant="outline" size="sm" onClick={() => void load()}><RefreshCw className="h-3.5 w-3.5" />{t('common.refresh')}</Button>
          {can('rbac:write') && tab !== 'matrix' && <Button size="sm" onClick={() => tab === 'users' ? openUser() : openRole()}>
            <Plus className="h-4 w-4" />{tab === 'users' ? t('rbac.newUser') : t('rbac.newRole')}</Button>}
        </>} />

      <Tabs value={tab} onValueChange={setTab} className="mb-4" items={[
        { value: 'users', label: t('rbac.users'), icon: <UsersRound className="h-3 w-3" />, count: users.length },
        { value: 'roles', label: t('rbac.roles'), icon: <ShieldCheck className="h-3 w-3" />, count: roles.length },
        { value: 'matrix', label: t('rbac.matrix'), icon: <LockKeyhole className="h-3 w-3" />, count: permissions.length },
      ]} />

      {tab === 'users' && <Card><CardContent className="p-0"><Table>
        <TableHeader><TableRow>
          <TableHead>{t('rbac.username')}</TableHead><TableHead>{t('rbac.displayName')}</TableHead>
          <TableHead>{t('rbac.rolesAssigned')}</TableHead><TableHead>{t('authSettings.security')}</TableHead>
          <TableHead>{t('rbac.status')}</TableHead><TableHead>{t('rbac.lastLogin')}</TableHead><TableHead>{t('common.actions')}</TableHead>
        </TableRow></TableHeader>
        <TableBody>{users.map((u) => <TableRow key={u.id}>
          <TableCell><div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-[10px] font-semibold text-primary">{u.username.slice(0, 2).toUpperCase()}</span>
            <div><p className="text-xs font-medium">{u.username}</p><p className="text-[10px] text-muted-foreground">{u.email || '—'}</p></div>
          </div></TableCell>
          <TableCell className="text-xs">{u.display_name || '—'}<p className="text-[10px] text-muted-foreground">{u.dept || ''}</p></TableCell>
          <TableCell><div className="flex flex-wrap gap-1">{(u.role_ids || []).map((id) => <Badge key={id} variant="secondary" className="text-[9px]">{roleName(id)}</Badge>)}
            {!u.role_ids?.length && <span className="text-[10px] text-muted-foreground">—</span>}</div></TableCell>
          <TableCell><div className="flex gap-1">
            {u.otp_enabled && <Badge variant="success" className="text-[9px]">OTP</Badge>}
            {u.passkey_enabled && <Badge variant="success" className="text-[9px]"><Fingerprint className="h-2.5 w-2.5" />Passkey</Badge>}
            {!u.otp_enabled && !u.passkey_enabled && <span className="text-[10px] text-muted-foreground">—</span>}
          </div></TableCell>
          <TableCell><Badge variant={u.status === 'active' ? 'success' : 'destructive'}>{u.status}</Badge></TableCell>
          <TableCell className="text-[11px] text-muted-foreground">{formatDate(u.last_login_at, locale)}</TableCell>
          <TableCell><div className="flex gap-0.5">
            <Button variant="ghost" size="icon-sm" onClick={() => openUser(u)} disabled={!can('rbac:write')}><Pencil className="h-3 w-3" /></Button>
            <Button variant="ghost" size="icon-sm" onClick={() => { setUserForm({ id: u.id }); setResetOpen(true) }} disabled={!can('rbac:write')}><KeyRound className="h-3 w-3" /></Button>
            <Button variant="ghost" size="icon-sm" onClick={() => setConfirmDelete({ kind: 'user', id: u.id })}
              disabled={!can('rbac:write') || u.id === currentUser?.id}><Trash2 className="h-3 w-3 text-destructive" /></Button>
          </div></TableCell>
        </TableRow>)}</TableBody></Table></CardContent></Card>}

      {tab === 'roles' && <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {roles.map((r) => <Card key={r.id} className="card-hover"><CardContent className="p-4">
          <div className="flex items-start gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary"><ShieldCheck className="h-4 w-4" /></span>
            <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{r.name}</p>
              <p className="font-mono text-[10px] text-muted-foreground">{r.code}</p></div>
            <Badge variant={r.builtin ? 'default' : 'secondary'}>{r.builtin ? t('rbac.builtin') : t('rbac.custom')}</Badge>
          </div>
          <p className="mt-2 min-h-[2rem] text-[11px] text-muted-foreground">{r.description || '—'}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge variant="outline">{t('rbac.permissionCount', { count: r.code === 'admin' ? permissions.length : r.permission_ids.length })}</Badge>
            <Badge variant={r.mfa_required ? 'warning' : 'muted'}>{r.mfa_required ? t('rbac.mfaRequired') : 'MFA off'}</Badge>
          </div>
          <div className="mt-3 flex items-center justify-between border-t pt-3">
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><span>{t('rbac.mfaRequired')}</span>
              <Switch checked={r.mfa_required} onCheckedChange={() => void toggleMfa(r)} disabled={!can('rbac:write')} /></div>
            <div className="flex gap-0.5">
              <Button variant="ghost" size="icon-sm" onClick={() => openRole(r)} disabled={!can('rbac:write')}><Pencil className="h-3 w-3" /></Button>
              <Button variant="ghost" size="icon-sm" onClick={() => setConfirmDelete({ kind: 'role', id: r.id })}
                disabled={!can('rbac:write') || r.builtin}><Trash2 className="h-3 w-3 text-destructive" /></Button>
            </div>
          </div>
        </CardContent></Card>)}
      </div>}

      {tab === 'matrix' && <Card><CardContent className="p-0">
        <div className="border-b px-4 py-2.5 text-xs text-muted-foreground">{t('rbac.matrixHint')} · {t('rbac.adminAll')}</div>
        <div className="scroll-thin overflow-x-auto"><Table>
          <TableHeader><TableRow><TableHead className="sticky left-0 bg-muted/60">{t('rbac.permissions')}</TableHead>
            {roles.map((r) => <TableHead key={r.id} className="text-center">{r.code}</TableHead>)}</TableRow></TableHeader>
          <TableBody>
            {Object.entries(grouped).map(([resource, perms]) => <FragmentRows key={resource} resource={resource}
              perms={perms} roles={roles} toggle={togglePermission} canEdit={can('rbac:write')} />)}
          </TableBody></Table></div>
      </CardContent></Card>}

      <Dialog open={userOpen} onOpenChange={setUserOpen} title={userForm.id ? t('rbac.editUser') : t('rbac.createUser')} size="lg"
        footer={<><Button variant="outline" onClick={() => setUserOpen(false)}>{t('common.cancel')}</Button><Button onClick={saveUser}>{t('common.save')}</Button></>}>
        <div className="grid gap-3 sm:grid-cols-2">
          <F label={t('rbac.username')}><Input value={userForm.username} disabled={!!userForm.id} onChange={(e) => setUserForm({ ...userForm, username: e.target.value })} /></F>
          <F label={t('rbac.password')}><Input type="password" value={userForm.password} onChange={(e) => setUserForm({ ...userForm, password: e.target.value })} placeholder={userForm.id ? 'leave blank to keep' : 'min 8 chars'} /></F>
          <F label={t('rbac.email')}><Input value={userForm.email} onChange={(e) => setUserForm({ ...userForm, email: e.target.value })} /></F>
          <F label={t('rbac.displayName')}><Input value={userForm.display_name} onChange={(e) => setUserForm({ ...userForm, display_name: e.target.value })} /></F>
          <F label={t('rbac.department')}><Input value={userForm.dept} onChange={(e) => setUserForm({ ...userForm, dept: e.target.value })} /></F>
          <F label={t('rbac.status')}><Select value={userForm.status} onValueChange={(v) => setUserForm({ ...userForm, status: v })}
            options={[{ value: 'active', label: 'active' }, { value: 'disabled', label: 'disabled' }]} /></F>
          <div className="sm:col-span-2"><Label>{t('rbac.rolesAssigned')}</Label>
            <div className="mt-1.5 flex flex-wrap gap-2">{roles.map((r) => (
              <label key={r.id} className="flex cursor-pointer items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs hover:bg-muted/50">
                <input type="checkbox" className="h-3 w-3 accent-[hsl(var(--primary))]" checked={userForm.role_ids.includes(r.id)}
                  onChange={() => setUserForm({ ...userForm, role_ids: userForm.role_ids.includes(r.id)
                    ? userForm.role_ids.filter((x: number) => x !== r.id) : [...userForm.role_ids, r.id] })} />{r.code}</label>
            ))}</div></div>
        </div>
      </Dialog>

      <Dialog open={roleOpen} onOpenChange={setRoleOpen} title={roleForm.id ? t('rbac.editRole') : t('rbac.createRole')} size="lg"
        footer={<><Button variant="outline" onClick={() => setRoleOpen(false)}>{t('common.cancel')}</Button><Button onClick={saveRole}>{t('common.save')}</Button></>}>
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <F label={t('rbac.roleCode')}><Input value={roleForm.code} disabled={!!roleForm.id} onChange={(e) => setRoleForm({ ...roleForm, code: e.target.value })} placeholder="my_role" /></F>
            <F label={t('rbac.roleName')}><Input value={roleForm.name} onChange={(e) => setRoleForm({ ...roleForm, name: e.target.value })} /></F>
          </div>
          <F label={t('common.description')}><Input value={roleForm.description} onChange={(e) => setRoleForm({ ...roleForm, description: e.target.value })} /></F>
          <div className="flex items-center justify-between rounded-lg border px-3 py-2"><span className="text-xs">{t('rbac.mfaRequired')}</span>
            <Switch checked={roleForm.mfa_required} onCheckedChange={(v) => setRoleForm({ ...roleForm, mfa_required: v })} /></div>
          <div><Label>{t('rbac.permissions')} ({roleForm.permission_ids.length})</Label>
            <div className="scroll-thin mt-1.5 grid max-h-56 grid-cols-1 gap-1 overflow-y-auto sm:grid-cols-2">
              {permissions.map((p) => <label key={p.id} className="flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-[11px] hover:bg-muted/50">
                <input type="checkbox" className="h-3 w-3 accent-[hsl(var(--primary))]" checked={roleForm.permission_ids.includes(p.id)}
                  onChange={() => setRoleForm({ ...roleForm, permission_ids: roleForm.permission_ids.includes(p.id)
                    ? roleForm.permission_ids.filter((x: number) => x !== p.id) : [...roleForm.permission_ids, p.id] })} />
                <span className="font-mono">{p.code}</span></label>)}
            </div></div>
        </div>
      </Dialog>

      <Dialog open={resetOpen} onOpenChange={setResetOpen} title={t('rbac.resetPassword')} size="sm"
        footer={<><Button variant="outline" onClick={() => setResetOpen(false)}>{t('common.cancel')}</Button><Button onClick={resetPassword}>{t('common.save')}</Button></>}>
        <Field label={t('rbac.newPassword')}><Input type="password" value={resetPwd} onChange={(e) => setResetPwd(e.target.value)} /></Field>
      </Dialog>
      <ConfirmDialog open={confirmDelete !== null} onOpenChange={() => setConfirmDelete(null)}
        title={t('common.confirmDelete')} onConfirm={remove} />
    </div>
  )
}

function FragmentRows({ resource, perms, roles, toggle, canEdit }: {
  resource: string; perms: Permission[]; roles: Role[]
  toggle: (r: Role, p: number) => void; canEdit: boolean
}) {
  return <>
    <TableRow className="bg-muted/30"><TableCell colSpan={roles.length + 1} className="py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{resource}</TableCell></TableRow>
    {perms.map((p) => <TableRow key={p.id}>
      <TableCell className="sticky left-0 bg-card"><span className="font-mono text-[11px]">{p.code}</span>
        <span className="ml-2 text-[10px] text-muted-foreground">{p.name}</span></TableCell>
      {roles.map((r) => {
        const checked = r.code === 'admin' || r.permission_ids.includes(p.id)
        return <TableCell key={r.id} className="text-center">
          <button disabled={!canEdit || r.code === 'admin'} onClick={() => toggle(r, p.id)}
            className={cn('inline-flex h-5 w-5 items-center justify-center rounded border transition-colors',
              checked ? 'border-primary bg-primary text-primary-foreground' : 'border-input hover:border-primary/50')}>
            {checked && <Check className="h-3 w-3" />}
          </button></TableCell>
      })}
    </TableRow>)}
  </>
}
