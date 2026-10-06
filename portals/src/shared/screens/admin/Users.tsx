/** Users: create, disable or enable, reset a password. Every change is audited on the server. */
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { createUser, disableUser, enableUser, listUsers, resetPassword, type AdminUser } from '../../api/admin'
import { departments, type Department } from '../../api/cases'

const ROLE_WORDS: Record<string, string> = {
  DEPT_OFFICER: 'DDO', AG_REVIEWER: 'AG Reviewer', ADMIN: 'Administrator',
}

export function Users() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [depts, setDepts] = useState<Department[]>([])
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ username: '', display_name: '', role: 'DEPT_OFFICER', department_code: 'PUNJAB_POLICE', password: '' })
  const [busy, setBusy] = useState(false)
  const [q, setQ] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const deptName = useMemo(() => Object.fromEntries(depts.map(d => [d.code, d.name])), [depts])
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase()
    return users.filter(u => (!roleFilter || u.role === roleFilter)
      && (!t || [u.username, u.display_name, u.department_code ?? '', deptName[u.department_code ?? ''] ?? ''].some(v => v.toLowerCase().includes(t))))
  }, [users, q, roleFilter, deptName])

  const load = () => listUsers().then(setUsers).catch(e => setError(e instanceof Error ? e.message : String(e)))
  useEffect(() => {
    load()
    departments().then(d => {
      setDepts(d)
      // The select shows the first department; the form must say the same.
      setForm(f => d.some(x => x.code === f.department_code) ? f : { ...f, department_code: d[0]?.code ?? '' })
    }).catch(() => {})
  }, [])

  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setError(null)
    try { await fn(); await load() } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    run(async () => {
      await createUser({ ...form, department_code: form.role === 'DEPT_OFFICER' ? form.department_code : undefined })
      setForm({ ...form, username: '', display_name: '', password: '' })
    })
  }

  return (
    <div className="screen container" style={{ paddingTop: 22 }}>
      <h1>Users</h1>
      <p className="lead">One account per officer. A disabled account is signed out immediately; a password reset ends its sessions.</p>
      {error && <div className="banner bad"><span className="mark">!</span><div className="sub">{error}</div></div>}

      <div className="row" style={{ marginTop: 'var(--s4)', gap: 'var(--s3)' }}>
        <input placeholder="Search by username, name or department" value={q} onChange={e => setQ(e.target.value)} style={{ maxWidth: 380 }} aria-label="Search users" />
        <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)} style={{ maxWidth: 220 }} aria-label="Filter by role">
          <option value="">All roles</option>
          {Object.entries(ROLE_WORDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <span className="register-count"><strong>{shown.length}</strong> of {users.length} accounts</span>
      </div>

      <div className="side-grid" style={{ marginTop: 'var(--s3)' }}>
        <div className="card table-wrap" style={{ padding: 0 }}>
          <table>
            <thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Department</th><th>Portal</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {shown.length === 0 && <tr><td colSpan={7}><div className="empty">No account matches.</div></td></tr>}
              {shown.map(u => (
                <tr key={u.id}>
                  <td className="mono">{u.username}</td>
                  <td>{u.display_name}</td>
                  <td>{ROLE_WORDS[u.role] ?? u.role}</td>
                  <td className="muted" style={{ fontSize: 'var(--t-small)' }} title={u.department_code ?? undefined}>{deptName[u.department_code ?? ''] ?? u.department_code ?? '—'}</td>
                  <td className="mono muted" style={{ fontSize: 'var(--t-small)' }}>{u.portal ?? '—'}</td>
                  <td><span className={`pill ${u.active ? 'low' : 'high'}`}>{u.active ? 'Active' : 'Disabled'}</span></td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {u.active
                      ? <button disabled={busy} style={{ padding: '5px 10px', fontSize: 'var(--t-small)' }}
                                onClick={() => { const r = window.prompt(`Disable ${u.username}? Reason:`); if (r !== null) run(() => disableUser(u.id, r)) }}>Disable</button>
                      : <button disabled={busy} style={{ padding: '5px 10px', fontSize: 'var(--t-small)' }} onClick={() => run(() => enableUser(u.id))}>Enable</button>}
                    {' '}
                    <button disabled={busy} style={{ padding: '5px 10px', fontSize: 'var(--t-small)' }}
                            onClick={() => { const p = window.prompt(`New password for ${u.username} (8+ characters):`); if (p) run(() => resetPassword(u.id, p)) }}>Reset password</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <form className="card stack" onSubmit={submit}>
          <h3 style={{ margin: 0 }}>New user</h3>
          <div className="field"><label className="label" htmlFor="nu-username">Username</label>
            <input id="nu-username" autoComplete="off" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} required /></div>
          <div className="field"><label className="label" htmlFor="nu-name">Display name</label>
            <input id="nu-name" value={form.display_name} onChange={e => setForm({ ...form, display_name: e.target.value })} required /></div>
          <div className="field"><label className="label" htmlFor="nu-role">Role</label>
            <select id="nu-role" value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}>
              {Object.entries(ROLE_WORDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></div>
          {form.role === 'DEPT_OFFICER' && (
            <div className="field"><label className="label" htmlFor="nu-dept">Department</label>
              <select id="nu-dept" value={form.department_code} onChange={e => setForm({ ...form, department_code: e.target.value })}>
                {depts.map(d => <option key={d.code} value={d.code}>{d.name}</option>)}
              </select>
              <div className="hint">The officer sees only this department's cases.</div></div>
          )}
          <div className="field"><label className="label" htmlFor="nu-password">Password (8+ characters)</label>
            <input id="nu-password" type="password" autoComplete="new-password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} required minLength={8} /></div>
          <button className="primary" type="submit" disabled={busy}>Create user</button>
        </form>
      </div>
    </div>
  )
}
