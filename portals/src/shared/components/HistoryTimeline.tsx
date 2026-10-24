/** The case history: every transition, who made it, and what they wrote. */
import { fmtDateTime } from '../fmt'
import type { CaseEvent } from '../api/cases'
import { statusLabelOf } from './StatusPill'

const ACTION_WORDS: Record<string, string> = {
  CREATE: 'Case filed', ADD_DOCS: 'Documents attached', RUN_CHECK: 'Examination started',
  CHECK_DONE: 'Examination complete: findings for the Office of the Accountant General', CHECK_FAILED: 'Examination incomplete',
  AUTO_RETURN: 'Returned by the examination: documents missing (automatic return, before 9 Oct 2026)', AUTO_APPROVE: 'Approved: nothing outstanding on the examination',
  GPF_RETURN: 'Returned after the GP Fund examination (automatic, before 9 Oct 2026)',
  FORWARD: "Submitted to Accountant General's Office",
  TAKE_UP: 'Taken up for review', APPROVE: 'Approved', REJECT: 'Rejected', RETURN: 'Returned to department',
  REQUEST_DOCS: 'Additional documents requested', OVERRIDE: 'Decision overridden by the Deputy Accountant General',
  SET_CASE_TYPE: 'Case type changed',
  REPLACE_DOC: 'Document replaced',
  FORWARD_TIER: 'Forwarded within the Pension Wing', RETURN_TIER: 'Returned within the Pension Wing',
}

const ROLE_WORDS: Record<string, string> = {
  DEPT_OFFICER: 'DDO', AG_REVIEWER: 'AG', AG_ADDL: 'Additional AG', AG_DAG: 'Deputy AG',
  AG_SENIOR_AUDITOR: 'Senior Auditor', AG_ASSISTANT_AO: 'Assistant Accounts Officer (AAO)',
  AG_AO: 'Accounts Officer (AO)',
  ADMIN: 'Administrator', SYSTEM: 'System',
}
const AG_ACTOR = ['AG_REVIEWER', 'AG_SENIOR_AUDITOR', 'AG_ASSISTANT_AO', 'AG_AO', 'AG_DAG']

/** What a row says: the tier moves name the tier and what the move meant (9 Oct 2026): the
 *  Senior Auditor verifies and forwards, the Assistant Accounts Officer approves and forwards,
 *  Officer gives the final approval. */
export function actionWords(e: { action: string; actor_role: string | null }): string {
  if (e.action === 'FORWARD_TIER') {
    if (e.actor_role === 'AG_ASSISTANT_AO') return 'Approved by the Assistant Accounts Officer (AAO) and forwarded to the Accounts Officer (AO)'
    if (e.actor_role === 'AG_SENIOR_AUDITOR') return 'Verified by the Senior Auditor and forwarded to the Assistant Accounts Officer (AAO)'
  }
  if (e.action === 'APPROVE' && e.actor_role === 'AG_AO') return 'Approved by the Accounts Officer (AO) — final'
  if (e.action === 'REJECT' && e.actor_role === 'AG_AO') return 'Rejected by the Accounts Officer (AO) — final'
  return ACTION_WORDS[e.action] ?? e.action
}

const tone = (a: string) =>
  ['APPROVE', 'AUTO_APPROVE'].includes(a) ? 'var(--ok)' : ['REJECT', 'RETURN', 'AUTO_RETURN', 'REQUEST_DOCS', 'CHECK_FAILED', 'OVERRIDE'].includes(a) ? 'var(--red)'
  : ['FORWARD', 'TAKE_UP', 'FORWARD_TIER'].includes(a) ? 'var(--amber)' : a === 'RETURN_TIER' ? 'var(--red)' : 'var(--green3)'

export function HistoryTimeline({ events, highlightAg = false }: { events: CaseEvent[]; highlightAg?: boolean }) {
  if (!events.length) return <div className="empty">No history yet.</div>
  const shown = [...events].reverse()
  return (
    <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {shown.map(e => {
        const ag = AG_ACTOR.includes(e.actor_role ?? '') || e.action === 'OVERRIDE'
        const docs = (e.payload as { documents?: string[] | number }).documents
        const missing = (e.payload as { missing_checklist?: { id: string; requirement: string; status?: string }[] }).missing_checklist
        return (
          <li key={e.id} style={{ display: 'grid', gridTemplateColumns: '18px 1fr', gap: 12, padding: '10px 0',
                                  borderBottom: '1px solid var(--line)' }}>
            <div style={{ width: 12, height: 12, borderRadius: '50%', marginTop: 5, background: tone(e.action),
                          boxShadow: highlightAg && ag ? '0 0 0 3px var(--amberbg)' : undefined }} />
            <div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
                <strong>{actionWords(e)}</strong>
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
