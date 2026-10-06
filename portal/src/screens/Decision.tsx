/** Screen 4 — Decision & Dispatch. BUILD §9.7. */
import { useEffect, useState } from 'react'
import { fetchDecisions, postDecision, type DecisionEntry, type Role } from '../api'
import { caseTypeLabel } from '../labels'
import type { CaseReport } from '../types'

const ACTION_FOR: Record<string, string> = {
  return: 'RETURN_FOR_CORRECTION',
  override: 'FORWARD',
  hold: 'HOLD',
}

const statusOf = (r: CaseReport) =>
  !r.checklist ? 'not applied' : r.checklist.result === 'COMPLETE' ? 'complete' : 'incomplete'

export function Decision(
  { report, runId, role, onReset, onNew }:
  { report: CaseReport; runId: string; role: Role; onReset: () => void
    onNew?: () => void },
) {
  const [choice, setChoice] = useState<string | null>(null)
  const [justification, setJustification] = useState('')
  const [officer, setOfficer] = useState('')
  const [saving, setSaving] = useState(false)
  const [refused, setRefused] = useState<string | null>(null)
  const [history, setHistory] = useState<DecisionEntry[]>([])
  useEffect(() => { fetchDecisions(runId).then(setHistory).catch(() => setHistory([])) }, [runId])

  async function dispatch() {
    if (!choice) return
    setSaving(true); setRefused(null)
    try {
      await postDecision(runId, {
        action: ACTION_FOR[choice],
        officer,
        role,
        justification,
      })
      setHistory(await fetchDecisions(runId))
      setChoice(null); setJustification('')
    } catch (e) {
      setRefused(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }
  const blocking = (report.recommendation?.blocking_flags ?? []).join(', ')
  // Does anything actually stand against forwarding? The same test the server applies, so
  // the screen and the endpoint agree about what an override is. A clean case offers plain
  // approval; only a blocked one demands a written reason. Calling every approval an
  // "override" taught officers to ignore the word on the cases where it mattered.
  const blockedFlags = report.flags.filter(f => f.blocks_ppo).length
  const missing = report.checklist?.missing ?? 0
  const incomplete = (report.checklist?.result ?? '') === 'INCOMPLETE'
  // The engine's verdict too, as api/decisions.py _blocked reads it: a case recommended for
  // HOLD, or one that reached no determination, is not forwardable either. Without this the
  // screen offered plain approval with no reason box, and the server then refused it for want
  // of the reason it had never asked for.
  const verdict = report.recommendation?.verdict
  const blocked = blockedFlags > 0 || missing > 0 || incomplete
    || (verdict ? verdict !== 'FORWARD' : !report.recommendation)
  const dept = report.notifications.find(n => n.recipient_class === 'DEPARTMENT')
  const claimant = report.notifications.find(n => n.recipient_class === 'CLAIMANT')

  // §9.7: an override cannot advance without a recorded justification. On a clean case
  // there is nothing to override, so approval needs no essay.
  const overrideBlocked =
    choice === 'override' && blocked && justification.trim().length < 15
  const mayDecide = role === 'ACCOUNTS_OFFICE'

  const audit = [
    `INTAKE      ${report.source.file} · ${report.source.source_pages} pages`,
    `SCAN        sha256 ${report.source.sha256.slice(0, 40)}…`,
    `EXTRACT     ${report.provenance.vl_model ?? 'vision model'} · weights ${report.provenance.weights_version ?? 'pinned'}`,
    `CASE KIND   ${caseTypeLabel(report.case_type.case_type)} · confidence ${report.case_type.case_type_confidence}`,
    `CHECKLIST   ${statusOf(report)} ${report.checklist?.satisfied ?? '-'}/${report.checklist?.required ?? '-'}`,
    `FLAGS       ${report.flags.length} raised · ${report.flags.filter(f => f.blocks_ppo).length} blocking (${blocking || 'none'})`,
    report.determination
      ? `RULES       pack ${report.determination.rule_pack_id} · ${report.determination.provisional ? 'PROVISIONAL' : 'final'}`
      : `RULES       not computed`,
  ]

  return (
    <div className="screen container" style={{ paddingTop: 22 }}>
      <h2 style={{ margin: '0 0 4px' }}>Decision &amp; Dispatch</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        The AI recommends; the officer decides. Every action below is logged to the
        append-only audit trail.
      </p>

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div style={{ flex: '1 1 520px' }}>
          <div className="card">
            <div className="card-head">
              <h3 style={{ margin: 0 }}>Approve or reject</h3>
              <span className={`pill ${blocked ? 'high' : 'low'}`}>
                {blocked ? 'Engine recommends return' : 'Engine recommends approval'}
              </span>
            </div>

            {!mayDecide ? (
              <div className="banner warn" style={{ marginBottom: 0 }}>
                <div className="mark">i</div>
                <div>
                  <div className="title">This case is decided by the Accounts Office</div>
                  <div className="sub">
                    Under SOP §4.2 a pension case is approved or rejected by the Accounts
                    Office. The Administrative Department submits the case, answers for
                    shortcomings found in it, and resubmits once they are removed (§4.1).
                    Switch role in the header to act as the Accounts Office.
                  </div>
                </div>
              </div>
            ) : (
            <>
            <button
              className={choice === 'override' ? 'primary' : ''}
              style={{ width: '100%', textAlign: 'left', marginBottom: 8 }}
              onClick={() => setChoice('override')}
            >
              {blocked
                ? '✓ Approve anyway — override the findings and forward (reason required)'
                : '✓ Approve and forward to the AG determination queue'}
            </button>
            <button
              className={choice === 'return' ? 'primary' : ''}
              style={{ width: '100%', textAlign: 'left', marginBottom: 8 }}
              onClick={() => setChoice('return')}
            >
              ✗ Reject — return to the department for correction
              {blocking && ` (${blocking})`}{blocked && ' — recommended'}
            </button>
            <button
              className={choice === 'hold' ? 'primary' : ''}
              style={{ width: '100%', textAlign: 'left' }}
              onClick={() => setChoice('hold')}
            >
              ⏸ Place on hold (exceptional-case lane, SOP §6.2)
            </button>

            {choice && (
              // Every decision carries the officer's remarks. Required where the decision goes
              // against the engine.
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 4 }}>
                  {choice === 'override' && blocked
                    ? 'Why the findings do not prevent approval (required, at least 15 characters)'
                    : choice === 'override' ? 'Remarks on the approval (optional)'
                    : choice === 'return' ? 'What the department must do (optional; the shortcomings list goes with it)'
                    : 'Why the case is on hold (optional)'}
                </div>
                <textarea
                  value={justification}
                  onChange={e => setJustification(e.target.value)}
                  rows={3}
                  style={{
                    width: '100%', padding: 10, borderRadius: 10,
                    border: `1px solid ${overrideBlocked ? 'var(--red)' : 'var(--line)'}`,
                    fontFamily: 'inherit', fontSize: 14,
                  }}
                  placeholder={choice === 'override' && blocked
                    ? `The engine recommends ${verdict ? verdict.replace(/_/g, ' ').toLowerCase() : 'no determination'}; say why this case may go forward…`
                    : 'Recorded with the decision…'}
                />
                {overrideBlocked && (
                  <div style={{ fontSize: 12, color: 'var(--red)', marginTop: 4 }}>
                    {15 - justification.trim().length} more character(s) needed before this approval can be recorded.
                  </div>
                )}
              </div>
            )}
            </>
            )}
          </div>

          {dept && (
            <div className="card">
              <h3 style={{ marginTop: 0 }}>To the department</h3>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                {dept.notification_class.replace(/_/g, ' ')} · {dept.channel}
              </div>
              <pre className="mono" style={{
                whiteSpace: 'pre-wrap', background: 'var(--sage)', borderRadius: 10,
                padding: 12, margin: 0, maxHeight: 260, overflow: 'auto', fontSize: 11.5,
              }}>{dept.body_en}</pre>
            </div>
          )}

          {claimant && (
            <div className="card">
              <h3 style={{ marginTop: 0 }}>To the claimant</h3>
              <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                {claimant.notification_class.replace(/_/g, ' ')} · {claimant.channel} ·{' '}
                {claimant.requires_recipient_action
                  ? 'action required from the claimant'
                  : 'no action required from the claimant'}
              </div>
              <div style={{
                background: 'var(--sage)', borderRadius: 10, padding: 12, marginBottom: 8,
              }}>{claimant.body_en}</div>
              {claimant.body_ur && (
                <div className="urdu" style={{
                  background: 'var(--sage)', borderRadius: 10, padding: 12, fontSize: 16,
                  lineHeight: 2,
                }}>{claimant.body_ur}</div>
              )}
            </div>
          )}
        </div>

        <div className="card" style={{ flex: '1 1 340px' }}>
          <h3 style={{ marginTop: 0 }}>Append-only audit trail</h3>
          <div className="mono" style={{
            background: 'var(--sage)', borderRadius: 10, padding: 12, fontSize: 11.5,
            lineHeight: 1.9,
          }}>
            {audit.map((l, i) => <div key={i}>{l}</div>)}
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            On resubmission the case re-enters intake, auto-revalidates, and is diffed against
            this submission so a reviewer sees what changed rather than re-reading every page.
          </p>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 10, marginTop: 14, alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span className="muted" style={{ fontSize: 12, fontWeight: 700 }}>
            Deciding officer{mayDecide ? '' : ' (Accounts Office only)'}
          </span>
          <input
            value={officer}
            onChange={e => setOfficer(e.target.value)}
            placeholder="Name and designation"
            style={{ padding: '7px 9px', minWidth: 250 }}
          />
        </label>
        <button
          className="gold"
          disabled={!mayDecide || !choice || !officer.trim() || overrideBlocked || saving}
          onClick={dispatch}
        >
          {saving ? 'Recording…' : 'Record decision'}
        </button>
        <button onClick={onReset}>← Back to the register</button>
        {/* This case is dispatched; the next one is usually already on the desk. */}
        {onNew && <button className="primary" onClick={onNew}>＋ Submit a new case</button>}
      </div>

      {refused && (
        <div className="card" style={{ marginTop: 12, borderLeft: '3px solid var(--high, #A32A1E)' }}>
          <strong>Decision not recorded.</strong>
          <div style={{ marginTop: 4, fontSize: 13 }}>{refused}</div>
        </div>
      )}

      {history.length > 0 && (
        <div className="card" style={{ marginTop: 14 }}>
          <h3 style={{ marginTop: 0 }}>Decision history</h3>
          <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
            Append-only. A later decision is added, never substituted for an earlier one.
          </p>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <tbody>
              {history.map((d, i) => (
                <tr key={i} style={{ borderTop: '1px solid var(--rule, #ddd)' }}>
                  <td style={{ padding: '6px 10px 6px 0', whiteSpace: 'nowrap' }}>{d.at}</td>
                  <td style={{ padding: '6px 10px 6px 0', fontWeight: 600 }}>{d.action}</td>
                  <td style={{ padding: '6px 10px 6px 0' }}>{d.officer}</td>
                  <td style={{ padding: '6px 0' }}>
                    {d.overrides_recommendation && (
                      <span style={{ fontWeight: 700 }}>OVERRIDE — </span>
                    )}
                    {d.justification || <span className="muted">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
