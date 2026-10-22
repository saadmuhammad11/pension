/** Where a case is: filed → with the office → the three desks inside it → decided.
 *
 *  The desks are steps of their own (22 Oct 2026). They were one step, "Verification", which
 *  did not move while a case travelled from the Senior Auditor to the Assistant Accounts
 *  Officer to the Accounts Officer -- so a department watching the bar saw nothing happen for
 *  days, and an officer could not tell from it whose desk the case was on.
 *
 *  The last step says what was decided (22 Oct 2026). It did not: a decided case drew four
 *  green ticks and the word "Decision", and an approval and a rejection were the same picture.
 *  The outcome is the one thing a department opens this bar to read. A closed step now carries
 *  the outcome under it the way the step in progress carries its status, and a bad outcome --
 *  rejected, returned, documents wanted back -- is red with a cross, not a green tick.
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
        const here = i === at
        const done = i < at || (here && m.side === 'closed')
        const active = here && !done
        // The red belongs to the step the case is standing on, whether that step is still
        // running or is where the case came to rest.
        const wrong = here && bad
        return (
          <div key={label} className={`progress-step${done ? ' is-done' : ''}${active ? ' is-active' : ''}${wrong ? ' is-bad' : ''}`}>
            <div className="progress-dot">{done ? (wrong ? '✕' : '✓') : i + 1}</div>
            <div className="progress-label">
              {label}
              {here && <div className="progress-sub">{m.label}</div>}
            </div>
            {i < steps.length - 1 && <div className="progress-rail"><span style={{ width: done ? '100%' : '0%' }} /></div>}
          </div>
        )
      })}
    </div>
  )
}
