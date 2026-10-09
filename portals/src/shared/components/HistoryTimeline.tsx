/** The case history: every transition, who made it, and what they wrote. */
import { fmtDateTime } from '../fmt'
import type { CaseEvent } from '../api/cases'
import { statusLabelOf } from './StatusPill'

const ACTION_WORDS: Record<string, string> = {
  CREATE: 'Case filed', ADD_DOCS: 'Documents attached', RUN_CHECK: 'Verification started',
  CHECK_DONE: 'Verification complete: findings for the Accountant General', CHECK_FAILED: 'Verification incomplete',
  AUTO_RETURN: 'Returned by the verification: documents missing (automatic return, before 9 Oct 2026)', AUTO_APPROVE: 'Approved: nothing outstanding on the verification',
  GPF_RETURN: 'Returned after the GP Fund examination (automatic, before 9 Oct 2026)',
  FORWARD: 'Submitted to Accountant General',
  TAKE_UP: 'Taken up for review', APPROVE: 'Approved', REJECT: 'Rejected', RETURN: 'Returned to department',
  REQUEST_DOCS: 'Additional documents requested', OVERRIDE: 'Decision overridden by the Deputy Accountant General',
  SET_CASE_TYPE: 'Case type changed',
  REPLACE_DOC: 'Document replaced',
}

const ROLE_WORDS: Record<string, string> = {
  DEPT_OFFICER: 'DDO', AG_REVIEWER: 'Pension Wing, AG Punjab', AG_DAG: 'Deputy AG (Pension)',
  ADMIN: 'Administrator', SYSTEM: 'System',
}

const tone = (a: string) =>
  ['APPROVE', 'AUTO_APPROVE'].includes(a) ? 'var(--ok)' : ['REJECT', 'RETURN', 'AUTO_RETURN', 'REQUEST_DOCS', 'CHECK_FAILED', 'OVERRIDE'].includes(a) ? 'var(--red)'
  : ['FORWARD', 'TAKE_UP'].includes(a) ? 'var(--amber)' : 'var(--green3)'

export function HistoryTimeline({ events, highlightAg = false }: { events: CaseEvent[]; highlightAg?: boolean }) {
  if (!events.length) return <div className="empty">No history yet.</div>
  const shown = [...events].reverse()
  return (
    <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {shown.map(e => {
        const ag = e.actor_role === 'AG_REVIEWER' || e.action === 'OVERRIDE'
        const docs = (e.payload as { documents?: string[] | number }).documents
        const missing = (e.payload as { missing_checklist?: { id: string; requirement: string; status?: string }[] }).missing_checklist
        return (
          <li key={e.id} style={{ display: 'grid', gridTemplateColumns: '18px 1fr', gap: 12, padding: '10px 0',
                                  borderBottom: '1px solid var(--line)' }}>
            <div style={{ width: 12, height: 12, borderRadius: '50%', marginTop: 5, background: tone(e.action),
                          boxShadow: highlightAg && ag ? '0 0 0 3px var(--amberbg)' : undefined }} />
            <div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
                <strong>{ACTION_WORDS[e.action] ?? e.action}</strong>
                <span className="muted" style={{ fontSize: 'var(--t-small)' }}>
                  {e.actor_name ?? 'System'}{e.actor_role && e.actor_role !== 'SYSTEM' ? ` · ${ROLE_WORDS[e.actor_role] ?? e.actor_role}` : ''}
                  {' · '}{fmtDateTime(e.at)}
                </span>
                {e.from_status && e.from_status !== e.to_status && (
                  <span className="muted" style={{ fontSize: 'var(--t-small)' }}>
                    {statusLabelOf(e.from_status)} → {statusLabelOf(e.to_status)}
                  </span>
                )}
              </div>
              {e.remark && (
                <div style={{ marginTop: 4, padding: '8px 12px', borderRadius: 8, fontSize: 'var(--t-body)',
                              background: ag ? 'var(--amberbg)' : 'var(--sage)', borderLeft: `3px solid ${tone(e.action)}` }}>
                  {e.remark}
                </div>
              )}
              {Array.isArray(docs) && docs.length > 0 && (
                <div className="muted" style={{ fontSize: 'var(--t-small)', marginTop: 4 }}>{docs.join(', ')}</div>
              )}
              {Array.isArray(missing) && missing.length > 0 && (
                <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 'var(--t-small)' }}>
                  {missing.map(m => <li key={m.id}><strong>{m.id}</strong> {m.requirement}{m.status === 'DEFECTIVE' ? ' (defective)' : ''}</li>)}
                </ul>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
