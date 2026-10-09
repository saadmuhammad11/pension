/** The audit log: overrides and user changes, newest first, append-only on the server. */
import { useEffect, useState } from 'react'
import { auditLog, type AuditEntry } from '../../api/admin'
import { fmtDateTime } from '../../fmt'

const WORDS: Record<string, string> = {
  CASE_OVERRIDE: 'Case decision overridden', CASE_TYPE_CORRECTED: 'Case type corrected',
  USER_CREATE: 'User created', USER_DISABLE: 'User disabled',
  USER_ENABLE: 'User enabled', USER_RESET_PASSWORD: 'Password reset',
}

const brief = (v: unknown) => v == null ? '—' : typeof v === 'object' ? Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k}: ${String(x)}`).join(', ') : String(v)

export function AuditLog() {
  const [rows, setRows] = useState<AuditEntry[] | null>(null)
  const [actor, setActor] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)                    // Retry re-runs the fetch (F12)
  useEffect(() => {
    let live = true
    setRows(null); setError(null)
    const t = setTimeout(() => auditLog(actor ? { actor } : {})
      .then(r => { if (live) { setRows(r); setError(null) } })
      .catch(e => { if (live) setError(e instanceof Error ? e.message : String(e)) }), 250)
    return () => { live = false; clearTimeout(t) }
  }, [actor, attempt])
  return (
    <div className="screen container" style={{ paddingTop: 22 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 'var(--s4)', flexWrap: 'wrap' }}>
        <div><h1>Audit log</h1><p className="lead">A permanent record of overrides and changes to user accounts. Entries cannot be edited or removed.</p></div>
        <input placeholder="Filter by actor…" aria-label="Filter by actor" value={actor} onChange={e => setActor(e.target.value)} style={{ maxWidth: 260 }} />
      </div>
      {error && <div className="banner bad" role="alert"><span className="mark">!</span><div className="sub">Could not load the audit log. {error} <button type="button" style={{ marginLeft: 8 }} onClick={() => setAttempt(a => a + 1)}>Retry</button></div></div>}
      <div className="card table-wrap" style={{ marginTop: 'var(--s4)', padding: 0 }}>
        <table>
          <thead><tr><th>When</th><th>Who</th><th>What</th><th>Entity</th><th>Before → after</th><th>Reason</th></tr></thead>
          <tbody>
            {rows === null && !error && <tr><td colSpan={6} className="muted">Loading…</td></tr>}
            {rows && rows.length === 0 && <tr><td colSpan={6}><div className="empty">No entries.</div></td></tr>}
            {(rows ?? []).map(r => (
              <tr key={r.id}>
                <td className="mono" style={{ fontSize: 'var(--t-small)', whiteSpace: 'nowrap' }}>{fmtDateTime(r.at)}</td>
                <td style={{ fontSize: 'var(--t-small)' }}>{r.actor_name ?? r.actor_id ?? '—'}<div className="muted">{r.actor_role}</div></td>
                <td>{WORDS[r.action] ?? r.action}</td>
                <td className="mono muted" style={{ fontSize: 'var(--t-small)' }}>{r.entity_type} {r.entity_id.slice(0, 8)}</td>
                <td style={{ fontSize: 'var(--t-small)' }}>{brief(r.before)} → {brief(r.after)}</td>
                <td style={{ fontSize: 'var(--t-small)' }}>{r.reason || <span className="muted">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
