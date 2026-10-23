/** Users: create, disable or enable, reset a password, give an AG account its tier and wing (C4,
 *  9 Oct 2026). Every change is audited on the server. */
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { createUser, disableUser, enableUser, listUsers, resetPassword, setUserRole, setUsername, wingCoverage, type AdminUser, type WingCoverage } from '../../api/admin'
import { departments, type Department } from '../../api/cases'
import { useSession } from '../../auth/AuthProvider'
import { PasswordField } from '../../components/PasswordField'

/** The roles in the order the office speaks of them. AG_REVIEWER is the Accountant General's own
 *  desk (9 Oct 2026): no wing, no tier, acts wherever a case is; its one login is shared by the
 *  office's senior officers. */
export const ROLE_WORDS: Record<string, string> = {
  AG_SENIOR_AUDITOR: 'Senior Auditor', AG_ASSISTANT_AO: 'Assistant Accounts Officer', AG_AO: 'Accounts Officer',
  AG_DAG: 'Deputy AG (Pension)', AG_REVIEWER: 'AG / Additional AG and senior officers (all wings, every tier)', DEPT_OFFICER: 'DDO', ADMIN: 'Administrator',
}
export const CREATABLE_ROLES = ['AG_SENIOR_AUDITOR', 'AG_ASSISTANT_AO', 'AG_AO', 'AG_DAG', 'AG_REVIEWER', 'DEPT_OFFICER', 'ADMIN']
export const TIER_ROLES = ['AG_SENIOR_AUDITOR', 'AG_ASSISTANT_AO', 'AG_AO']
export const WINGS = ['Pension-I', 'Pension-II', 'Pension-III', 'Pension-IV', 'Pension-V']
/** A wing officer has a wing and no department; a DDO a department and no wing; the rest neither. */
export const needsWing = (role: string) => TIER_ROLES.includes(role)
export const needsDepartment = (role: string) => role === 'DEPT_OFFICER'

//: What a username may be, as api/v2.py's create_user and set_username both require it. Here
//: so the form can refuse before the server does, not instead of it.
const USERNAME = /^[a-z0-9._-]{3,40}$/

export function Users() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [depts, setDepts] = useState<Department[]>([])
  const [coverage, setCoverage] = useState<WingCoverage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ username: '', display_name: '', role: 'AG_SENIOR_AUDITOR', department_code: 'PUNJAB_POLICE', pension_wing: 'Pension-I', password: '' })
  const [busy, setBusy] = useState(false)
  const [q, setQ] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [wingFilter, setWingFilter] = useState('')
  // Disable and reset used to go through window.prompt: a password typed into a browser prompt is
  // shown in clear, cannot be a password field, and the prompt is blocked by some browsers
  // (audit 6 Oct 2026, L9). They are ordinary forms now, with the password masked.
  const [ask, setAsk] = useState<{ kind: 'disable' | 'reset' | 'enable' | 'role' | 'rename'; user: AdminUser } | null>(null)
  // The shortest password the server accepts (one rule, told at sign-in; F14).
  const { passwordMinLength } = useSession()
  const [answer, setAnswer] = useState('')
  const [reason, setReason] = useState('')
  const [newRole, setNewRole] = useState({ role: 'AG_SENIOR_AUDITOR', pension_wing: 'Pension-I' })
  const deptName = useMemo(() => Object.fromEntries(depts.map(d => [d.code, d.name])), [depts])
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase()
    return users.filter(u => (!roleFilter || u.role === roleFilter) && (!wingFilter || u.pension_wing === wingFilter)
      && (!t || [u.username, u.display_name, u.department_code ?? '', deptName[u.department_code ?? ''] ?? '', u.pension_wing ?? ''].some(v => v.toLowerCase().includes(t))))
  }, [users, q, roleFilter, wingFilter, deptName])

  const load = () => Promise.all([listUsers().then(setUsers), wingCoverage().then(setCoverage)])
    .catch(e => setError(e instanceof Error ? e.message : String(e)))
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
      await createUser({
        username: form.username, display_name: form.display_name, role: form.role, password: form.password,
        department_code: needsDepartment(form.role) ? form.department_code : undefined,
        pension_wing: needsWing(form.role) ? form.pension_wing : undefined,
      })
      setForm({ ...form, username: '', display_name: '', password: '' })
    })
  }

  function answerAsk(e: FormEvent) {
    e.preventDefault()
    if (!ask) return
    const { kind, user } = ask
    const value = answer
    if (kind === 'reset' && (value.length < passwordMinLength || reason.trim().length < 10)) return
    if (kind === 'role' && reason.trim().length < 10) return
    if (kind === 'rename' && (!USERNAME.test(value) || value === user.username || reason.trim().length < 10)) return
    setAsk(null); setAnswer(''); setReason('')
    run(() => kind === 'disable' ? disableUser(user.id, value)
      : kind === 'enable' ? enableUser(user.id)
      : kind === 'role' ? setUserRole(user.id, { role: newRole.role, pension_wing: needsWing(newRole.role) ? newRole.pension_wing : undefined, reason: reason.trim() })
      : kind === 'rename' ? setUsername(user.id, value.trim().toLowerCase(), reason.trim())
      : resetPassword(user.id, value, reason.trim()))
  }

  const gaps = coverage?.gaps ?? []

  return (
    <div className="screen container" style={{ paddingTop: 22 }}>
      <h1>Users</h1>
      <p className="lead">One account per officer. A disabled account is signed out immediately; a password reset ends its sessions. An AG officer belongs to one pension wing and one tier; the wing is not a department.</p>
      {error && <div className="banner bad"><span className="mark">!</span><div className="sub">{error}</div></div>}

      {/* Wing coverage (C4): a tier with no active officer stops that wing's cases there. */}
      {coverage && (
        <div className={`card${gaps.length ? ' is-bad' : ''}`} style={{ marginTop: 'var(--s4)' }} aria-label="Wing coverage">
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
            <h3 style={{ margin: 0 }}>Wing coverage</h3>
            <span className="muted" style={{ fontSize: 'var(--t-small)' }}>Active officers per tier · Deputy AG: {coverage.deputy_ag}</span>
          </div>
          {gaps.length > 0 && (
            <div className="banner bad" style={{ marginTop: 8 }} role="alert"><span className="mark">!</span>
              <div className="sub"><strong>{gaps.length} tier{gaps.length === 1 ? '' : 's'} with nobody:</strong>{' '}
                {gaps.map(g => `${g.wing} — ${coverage.tier_labels[g.tier]}`).join('; ')}. That wing's cases would stop there.</div></div>
          )}
          <table style={{ marginTop: 8 }}>
            <thead><tr><th>Wing</th>{['SENIOR_AUDITOR', 'ASSISTANT_AO', 'AO'].map(t => <th key={t}>{coverage.tier_labels[t]}</th>)}</tr></thead>
            <tbody>
              {coverage.wings.map(w => (
                <tr key={w.wing}>
                  <td><strong>{w.wing}</strong></td>
                  {['SENIOR_AUDITOR', 'ASSISTANT_AO', 'AO'].map(t => (
                    <td key={t}>{w.tiers[t] ? <span className="pill low">{w.tiers[t]}</span> : <span className="pill high" title="No active officer at this tier">none</span>}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="row" style={{ marginTop: 'var(--s4)', gap: 'var(--s3)' }}>
        <input placeholder="Search by username, name, department or wing" value={q} onChange={e => setQ(e.target.value)} style={{ maxWidth: 380 }} aria-label="Search users" />
        <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)} style={{ maxWidth: 240 }} aria-label="Filter by role">
          <option value="">All roles</option>
          {Object.entries(ROLE_WORDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={wingFilter} onChange={e => setWingFilter(e.target.value)} style={{ maxWidth: 180 }} aria-label="Filter by pension wing">
          <option value="">All wings</option>
          {WINGS.map(w => <option key={w} value={w}>{w}</option>)}
        </select>
        <span className="register-count"><strong>{shown.length}</strong> of {users.length} accounts</span>
      </div>

      {ask && (
        <form className="card stack" style={{ marginTop: 'var(--s3)' }} onSubmit={answerAsk}
              aria-label={ask.kind === 'disable' ? 'Disable account' : ask.kind === 'enable' ? 'Enable account' : ask.kind === 'role' ? 'Change role and wing'
                : ask.kind === 'rename' ? 'Change username' : 'Reset password'}>
          <h3 style={{ margin: 0 }}>{ask.kind === 'disable' ? `Disable ${ask.user.username}` : ask.kind === 'enable' ? `Enable ${ask.user.username}?`
            : ask.kind === 'role' ? `Tier and wing of ${ask.user.username}`
            : ask.kind === 'rename' ? `New username for ${ask.user.display_name}` : `New password for ${ask.user.username}`}</h3>
          {ask.kind === 'disable' && (
            <div className="field"><label className="label" htmlFor="ask-reason">Reason (goes on the audit trail)</label>
              <input id="ask-reason" autoFocus autoComplete="off" value={answer} onChange={e => setAnswer(e.target.value)} required /></div>
          )}
          {/* Enabling is confirmed (F14): the account can sign in again the moment it is pressed. */}
          {ask.kind === 'enable' && (
            <p className="help" style={{ margin: 0 }}>{ask.user.display_name} will be able to sign in again at once. This is audited.</p>
          )}
          {ask.kind === 'reset' && (<>
            <PasswordField id="ask-password" label="Password (the officer is asked to change it)" value={answer} onChange={setAnswer}
                           minLength={passwordMinLength} username={ask.user.username} autoFocus />
            <div className="field"><label className="label" htmlFor="ask-reset-reason">Reason (at least 10 characters; goes on the audit trail)</label>
              <input id="ask-reset-reason" autoComplete="off" value={reason} onChange={e => setReason(e.target.value)} required minLength={10} /></div>
          </>)}
          {ask.kind === 'rename' && (<>
            <div className="field"><label className="label" htmlFor="ask-username">Username</label>
              <input id="ask-username" autoFocus autoComplete="off" autoCapitalize="none" autoCorrect="off" spellCheck={false}
                     value={answer} onChange={e => setAnswer(e.target.value.toLowerCase())}
                     aria-describedby="ask-username-help" aria-invalid={!!answer && !USERNAME.test(answer)} required />
              <p className="help" id="ask-username-help" style={{ margin: '6px 0 0' }}>
                Signs in as <strong className="mono">{ask.user.username}</strong> today. 3 to 40 characters: letters,
                digits, and . _ -
              </p></div>
            <div className="field"><label className="label" htmlFor="ask-rename-reason">Reason (at least 10 characters; goes on the audit trail)</label>
              <input id="ask-rename-reason" autoComplete="off" value={reason} onChange={e => setReason(e.target.value)} required minLength={10} /></div>
            <p className="help" style={{ margin: 0 }}>
              The account's sessions end and the officer signs in with the new username. Its work does not move:
              every case, decision and audit entry already names the account itself, not the word it signs in with.
            </p>
          </>)}
          {ask.kind === 'role' && (<>
            <div className="field"><label className="label" htmlFor="ask-role">Role</label>
              <select id="ask-role" value={newRole.role} onChange={e => setNewRole({ ...newRole, role: e.target.value })}>
                {['AG_SENIOR_AUDITOR', 'AG_ASSISTANT_AO', 'AG_AO', 'AG_DAG', 'AG_REVIEWER'].map(k => <option key={k} value={k}>{ROLE_WORDS[k]}</option>)}
              </select></div>
            {needsWing(newRole.role) && (
              <div className="field"><label className="label" htmlFor="ask-wing">Pension wing</label>
                <select id="ask-wing" value={newRole.pension_wing} onChange={e => setNewRole({ ...newRole, pension_wing: e.target.value })}>
                  {WINGS.map(w => <option key={w} value={w}>AG {w}</option>)}
                </select></div>
            )}
            <div className="field"><label className="label" htmlFor="ask-role-reason">Reason (at least 10 characters; goes on the audit trail)</label>
              <input id="ask-role-reason" autoComplete="off" value={reason} onChange={e => setReason(e.target.value)} required minLength={10} /></div>
            <p className="help" style={{ margin: 0 }}>The officer's sessions end; they sign in again with the new tier.</p>
          </>)}
          <div className="row" style={{ gap: 'var(--s2)' }}>
            <button className="primary" type="submit" disabled={busy || (ask.kind === 'reset' && (answer.length < passwordMinLength || reason.trim().length < 10))
                                                                 || (ask.kind === 'role' && reason.trim().length < 10)
                                                                 || (ask.kind === 'rename' && (!USERNAME.test(answer) || answer === ask.user.username || reason.trim().length < 10))}>
              {ask.kind === 'disable' ? 'Disable account' : ask.kind === 'enable' ? 'Enable account' : ask.kind === 'role' ? 'Set tier and wing'
                : ask.kind === 'rename' ? 'Change username' : 'Set password'}
            </button>
            <button type="button" onClick={() => { setAsk(null); setAnswer(''); setReason('') }}>Cancel</button>
          </div>
        </form>
      )}

      <div className="side-grid" style={{ marginTop: 'var(--s3)' }}>
        <div className="card table-wrap" style={{ padding: 0 }}>
          <table>
            <thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Wing / department</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {shown.length === 0 && <tr><td colSpan={6}><div className="empty">No account matches.</div></td></tr>}
              {shown.map(u => (
                <tr key={u.id}>
                  <td className="mono">{u.username}</td>
                  <td>{u.display_name}</td>
                  <td>{ROLE_WORDS[u.role] ?? u.role}</td>
                  <td className="muted" style={{ fontSize: 'var(--t-small)' }} title={u.department_code ?? u.pension_wing ?? undefined}>
                    {u.pension_wing ? `AG ${u.pension_wing}` : deptName[u.department_code ?? ''] ?? u.department_code ?? '—'}</td>
                  <td><span className={`pill ${u.active ? 'low' : 'high'}`}>{u.active ? 'Active' : 'Disabled'}</span></td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {u.active
                      ? <button disabled={busy} style={{ padding: '5px 10px', fontSize: 'var(--t-small)' }}
                                onClick={() => { setAsk({ kind: 'disable', user: u }); setAnswer('') }}>Disable</button>
                      : <button disabled={busy} style={{ padding: '5px 10px', fontSize: 'var(--t-small)' }} onClick={() => { setAsk({ kind: 'enable', user: u }); setAnswer('') }}>Enable</button>}
                    {' '}
                    <button disabled={busy} style={{ padding: '5px 10px', fontSize: 'var(--t-small)' }}
                            onClick={() => { setAsk({ kind: 'reset', user: u }); setAnswer(''); setReason('') }}>Reset password</button>
                    {' '}
                    <button disabled={busy} style={{ padding: '5px 10px', fontSize: 'var(--t-small)' }}
                            onClick={() => { setAsk({ kind: 'rename', user: u }); setAnswer(u.username); setReason('') }}>Username</button>
                    {u.role !== 'DEPT_OFFICER' && u.role !== 'ADMIN' && <>
                      {' '}
                      <button disabled={busy} style={{ padding: '5px 10px', fontSize: 'var(--t-small)' }}
                              onClick={() => { setAsk({ kind: 'role', user: u }); setReason(''); setNewRole({ role: TIER_ROLES.includes(u.role) || u.role === 'AG_DAG' || u.role === 'AG_REVIEWER' ? u.role : 'AG_SENIOR_AUDITOR', pension_wing: u.pension_wing ?? 'Pension-I' }) }}>
                        Tier / wing</button>
                    </>}
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
              {CREATABLE_ROLES.map(k => <option key={k} value={k}>{ROLE_WORDS[k]}</option>)}
            </select></div>
          {needsWing(form.role) && (
            <div className="field"><label className="label" htmlFor="nu-wing">Pension wing</label>
              <select id="nu-wing" value={form.pension_wing} onChange={e => setForm({ ...form, pension_wing: e.target.value })}>
                {WINGS.map(w => <option key={w} value={w}>AG {w}</option>)}
              </select>
              <div className="hint">The officer sees and acts on this wing's cases only, at this tier. A wing is not a department.</div></div>
          )}
          {needsDepartment(form.role) && (
            <div className="field"><label className="label" htmlFor="nu-dept">Department</label>
              <select id="nu-dept" value={form.department_code} onChange={e => setForm({ ...form, department_code: e.target.value })}>
                {depts.map(d => <option key={d.code} value={d.code}>{d.name}</option>)}
              </select>
              <div className="hint">The officer sees only this department's cases.</div></div>
          )}
          <PasswordField id="nu-password" label="Password" value={form.password} onChange={v => setForm({ ...form, password: v })}
                         minLength={passwordMinLength} username={form.username} />
          <button className="primary" type="submit" disabled={busy || form.password.length < passwordMinLength}>Create user</button>
        </form>
      </div>
    </div>
  )
}
