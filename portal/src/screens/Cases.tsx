/** Screen 0 — the case register. SOP §4.2: "proper monitoring for proper disposal".
 *
 *  The portal opened on an upload box, which made it a tool for one case at a time. An
 *  Accounts Office does not work one case at a time: it works a queue, and the first
 *  question of the morning is which cases are waiting on it and which are waiting on
 *  somebody else. That question is what this screen answers.
 */
import { useEffect, useState, type CSSProperties } from 'react'
import { fetchCases, removeCase, type CaseRow, type Role } from '../api'
import { caseTypeLabel } from '../labels'

/** How each state reads, and how urgently. Wording is the office's, not the engine's. */
const STATUS: Record<CaseRow['status'], { label: string; pill: string; note: string }> = {
  RUNNING: { label: 'Reading', pill: 'neutral', note: 'The AI is reading the papers.' },
  FAILED: { label: 'Failed', pill: 'high', note: 'The run stopped before it produced a report.' },
  AWAITING_REVIEW: { label: 'Awaiting review', pill: 'medium', note: 'Read and reported. No decision recorded yet.' },
  APPROVED: { label: 'Approved', pill: 'low', note: 'Forwarded to the AG determination queue.' },
  RETURNED: { label: 'Returned', pill: 'high', note: 'Sent back to the department for correction.' },
  ON_HOLD: { label: 'On hold', pill: 'medium', note: 'Parked in the exceptional-case lane.' },
}

/** What this role is waiting on. §4.1 answers for shortcomings; §4.2 disposes of the queue. */
const MINE_FOR: Record<Role, CaseRow['status'][]> = {
  ACCOUNTS_OFFICE: ['AWAITING_REVIEW'],
  ADMIN_DEPARTMENT: ['RETURNED'],
}

const ago = (t: number) => {
  if (!t) return '—'
  const mins = Math.round((Date.now() / 1000 - t) / 60)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

export function Cases(
  { role, onOpen, onNew }:
  { role: Role; onOpen: (runId: string) => void; onNew: () => void },
) {
  const [rows, setRows] = useState<CaseRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'mine' | 'all'>('mine')
  // A register is searched, not read. An office working a queue looks for one case by the
  // claimant's name or the reference a pensioner quoted down a telephone, and works a batch
  // by kind -- every family pension, everything still awaiting review.
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')

  async function load() {
    try { setRows(await fetchCases()); setError(null) }
    catch (e) { setError(String(e)) }
  }

  // The "×": off the register, not off the disk. The papers, report and decisions stay, and
  // the same case taken up again comes back.
  const [removing, setRemoving] = useState<string | null>(null)
  async function remove(r: CaseRow) {
    const name = r.claimant ?? r.run_id.toUpperCase()
    if (!window.confirm(`Remove ${name} from the register?\n\nIts files are kept; the case comes back if it is taken up again.`)) return
    setRemoving(r.run_id)
    try {
      await removeCase(r.run_id, role)
      setRows(rs => (rs ?? []).filter(x => x.run_id !== r.run_id))
      setError(null)
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setRemoving(null) }
  }
  // A register with a run in progress is stale within seconds, so it refreshes itself.
  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [])

  const mine = MINE_FOR[role]
  const waiting = (rows ?? []).filter(r => mine.includes(r.status))

  // Only the kinds actually present. A dropdown offering eight case types on an office
  // holding two teaches the officer that most of it is furniture.
  const kinds = Array.from(new Set((rows ?? []).map(r => r.case_type).filter(Boolean)))
    .sort() as string[]
  const statuses = Array.from(new Set((rows ?? []).map(r => r.status))) as CaseRow['status'][]

  const matches = (r: CaseRow) => {
    if (kind && r.case_type !== kind) return false
    if (status && r.status !== status) return false
    if (!query.trim()) return true
    // Searched over what an officer would have to hand: the claimant, the file they
    // uploaded, and the reference. Case-folded, because nobody types a case id in capitals.
    const q = query.trim().toLowerCase()
    return [r.claimant, r.file, r.run_id, r.case_type, r.case_variant]
      .some(v => (v ?? '').toLowerCase().includes(q))
  }

  const base = filter === 'mine' ? waiting : (rows ?? [])
  const shown = base.filter(matches)
  const filtering = Boolean(query.trim() || kind || status)

  return (
    <div className="screen container" style={{ paddingTop: 22 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end',
                    gap: 'var(--s4)', flexWrap: 'wrap' }}>
        <div>
          <h1>Pension Case Register</h1>
          <p className="lead">
            {role === 'ACCOUNTS_OFFICE'
              ? 'Cases received from administrative departments, and where each one stands.'
              : 'Cases this department has submitted, and what the Accounts Office found in them.'}
          </p>
        </div>
        <div className="row" style={{ gap: 'var(--s2)' }}>
          {role === 'ADMIN_DEPARTMENT' && (
            <button className="primary" onClick={onNew}>＋ Submit a new case</button>
          )}
        </div>
      </div>

      <div className="tabs" role="tablist" style={{ marginTop: 'var(--s5)' }}>
        <button className="tab" role="tab" aria-selected={filter === 'mine'}
                onClick={() => setFilter('mine')}>
          {role === 'ACCOUNTS_OFFICE' ? 'Awaiting my review' : 'Needing my attention'}
          <span className={`count${waiting.length ? ' alert' : ''}`}>{waiting.length}</span>
        </button>
        <button className="tab" role="tab" aria-selected={filter === 'all'}
                onClick={() => setFilter('all')}>
          All cases<span className="count">{rows?.length ?? 0}</span>
        </button>
      </div>

      <div className="row" style={{ marginBottom: 'var(--s4)', alignItems: 'flex-end' }}>
        <label className="field" style={{ flex: '1 1 260px', minWidth: 220 }}>
          <span className="label">Search</span>
          <input
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Claimant, file name or case reference"
          />
        </label>
        <label className="field" style={{ width: 240 }}>
          <span className="label">Case type</span>
          <select value={kind} onChange={e => setKind(e.target.value)}>
            <option value="">All case types</option>
            {kinds.map(k => (
              <option key={k} value={k}>{caseTypeLabel(k)}</option>
            ))}
          </select>
        </label>
        <label className="field" style={{ width: 190 }}>
          <span className="label">Status</span>
          <select value={status} onChange={e => setStatus(e.target.value)}>
            <option value="">Any status</option>
            {statuses.map(st => (
              <option key={st} value={st}>{STATUS[st].label}</option>
            ))}
          </select>
        </label>
        {filtering && (
          <button className="ghost" onClick={() => { setQuery(''); setKind(''); setStatus('') }}>
            Clear
          </button>
        )}
      </div>

      {filtering && rows !== null && (
        <p className="muted" style={{ fontSize: 'var(--t-small)', marginTop: 0 }}>
          Showing {shown.length} of {base.length}
          {filter === 'mine' ? ' awaiting you' : ' cases'}.
        </p>
      )}

      {error && (
        <div className="card" style={{ borderColor: 'var(--red)', background: 'var(--redbg)',
                                       color: 'var(--red)' }}>{error}</div>
      )}

      {rows === null && (
        // Shaped like the table it stands in for, so the page does not jump when the real
        // rows arrive under the officer's eye.
        <div className="card" aria-busy="true" aria-label="Loading the register">
          <div className="table-wrap">
            <table><tbody>
              {[0, 1, 2, 3].map(i => (
                <tr key={i}>
                  {[46, 22, 12, 14, 18, 14].map((w, j) => (
                    <td key={j} style={{ padding: '14px var(--s3) 14px 0' }}>
                      <div className="skeleton" style={{
                        width: `${w}%`, animationDelay: `${(i * 6 + j) * 60}ms`,
                      }} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody></table>
          </div>
        </div>
      )}

      {rows !== null && shown.length === 0 && filtering && (
        <div className="empty">
          No case matches that. {base.length > 0 && (
            <>There {base.length === 1 ? 'is' : 'are'} {base.length} here without the filters
            — <button className="ghost" style={{ padding: 0 }}
                      onClick={() => { setQuery(''); setKind(''); setStatus('') }}>
              clear them
            </button>.</>
          )}
        </div>
      )}

      {rows !== null && shown.length === 0 && !filtering && (
        <div className="empty">
          {filter === 'mine'
            ? <>Nothing is waiting on the {role === 'ACCOUNTS_OFFICE'
                ? 'Accounts Office' : 'department'} right now.</>
            : role === 'ACCOUNTS_OFFICE'
              ? <>No cases yet. Under SOP §4.1 cases arrive from administrative departments
                  — switch role in the header to submit one yourself.</>
              : <>No cases yet. Submit one to begin.</>}
        </div>
      )}

      {shown.length > 0 && (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Kind</th>
                  <th className="num">Checklist</th>
                  <th className="num">Findings</th>
                  <th>Status</th>
                  <th>Last activity</th>
                  <th />
                </tr>
              </thead>
              <tbody className="stagger">
                {shown.map((r, i) => {
                  const st = STATUS[r.status]
                  return (
                    <tr key={r.run_id} style={{ '--i': i } as CSSProperties}>
                      <td>
                        <div style={{ fontWeight: 600 }}>
                          {r.claimant ?? r.file.replace(/^[0-9a-f]{12}-/, '') ?? r.run_id}
                        </div>
                        <div className="mono muted" style={{ fontSize: 11 }}>
                          {r.run_id.toUpperCase()}
                          {r.pages ? ` · ${r.pages} pages` : ''}
                        </div>
                      </td>
                      <td>{r.case_type ? caseTypeLabel(r.case_type) : <span className="muted">not determined</span>}</td>
                      <td className="num">
                        {r.checklist_required
                          ? <>{r.checklist_satisfied}/{r.checklist_required}</>
                          : <span className="muted">—</span>}
                      </td>
                      <td className="num">
                        {r.flags === 0
                          ? <span className="muted">none</span>
                          : <>{r.flags}{r.blocking_flags > 0 && (
                              <span className="pill high" style={{ marginLeft: 6 }}>
                                {r.blocking_flags} blocking
                              </span>)}</>}
                      </td>
                      <td>
                        <span className={`pill ${st.pill}`}>{st.label}</span>
                        {r.decided_by && (
                          <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>
                            by {r.decided_by}
                          </div>
                        )}
                      </td>
                      <td className="muted" style={{ whiteSpace: 'nowrap' }}>{ago(r.updated_at)}</td>
                      <td>
                        <div className="row" style={{ gap: 4, flexWrap: 'nowrap', justifyContent: 'flex-end' }}>
                          <button className="ghost" onClick={() => onOpen(r.run_id)}>
                            {role === 'ACCOUNTS_OFFICE' && r.status === 'AWAITING_REVIEW'
                              ? 'Review →' : 'Open →'}
                          </button>
                          {r.status !== 'RUNNING' && (
                            <button className="ghost remove-x" title="Remove from the register"
                                    aria-label={`Remove ${r.claimant ?? r.run_id} from the register`}
                                    disabled={removing === r.run_id}
                                    onClick={() => remove(r)}>×</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {role === 'ACCOUNTS_OFFICE' && (
        <p className="muted" style={{ fontSize: 12 }}>
          Under SOP §4.1 a case is submitted by the administrative department. The Accounts
          Office receives it here and, under §4.2, approves or rejects it within the timelines.
        </p>
      )}
    </div>
  )
}
