/** Where a case is: filed → with the office → the three desks inside it → decided.
 *
 *  The desks are steps of their own (22 Oct 2026). They were one step, "Verification", which
 *  did not move while a case travelled from the Senior Auditor to the Assistant Accounts
 *  Officer to the Accounts Officer -- so a department watching the bar saw nothing happen for
 *  days, and an officer could not tell from it whose desk the case was on.
 */
import { STATUS_META, progressStep, progressSteps, type CaseStatus, type HolderTier } from '../api/cases'

export function CaseProgress({ status, holderTier }: { status: CaseStatus; holderTier?: HolderTier | null }) {
  const m = STATUS_META[status]
  const steps = progressSteps(holderTier)
  const at = progressStep(status, holderTier)
  const bad = m.pill === 'high' || status === 'RETURNED' || status === 'DOCS_REQUESTED'
  return (
    <div className="progress" aria-label={`Progress: ${m.label}`}>
      {steps.map((label, i) => {
        const done = i < at || (i === at && m.side === 'closed')
        const active = i === at && !done
        return (
          <div key={label} className={`progress-step${done ? ' is-done' : ''}${active ? ' is-active' : ''}${active && bad ? ' is-bad' : ''}`}>
            <div className="progress-dot">{done ? '✓' : i + 1}</div>
            <div className="progress-label">
              {label}
              {active && <div className="progress-sub">{m.label}</div>}
            </div>
            {i < steps.length - 1 && <div className="progress-rail"><span style={{ width: done ? '100%' : '0%' }} /></div>}
          </div>
        )
      })}
    </div>
  )
}
