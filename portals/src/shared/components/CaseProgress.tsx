/** Where a case is, as four steps: papers filed → AI check → with the AG → decision. */
import { PROGRESS_STEPS, STATUS_META, type CaseStatus } from '../api/cases'

export function CaseProgress({ status }: { status: CaseStatus }) {
  const m = STATUS_META[status]
  const bad = m.pill === 'high' || status === 'RETURNED' || status === 'DOCS_REQUESTED'
  return (
    <div className="progress" aria-label={`Progress: ${m.label}`}>
      {PROGRESS_STEPS.map((label, i) => {
        const done = i < m.step || (i === m.step && m.side === 'closed')
        const active = i === m.step && !done
        return (
          <div key={label} className={`progress-step${done ? ' is-done' : ''}${active ? ' is-active' : ''}${active && bad ? ' is-bad' : ''}`}>
            <div className="progress-dot">{done ? '✓' : i + 1}</div>
            <div className="progress-label">
              {label}
              {active && <div className="progress-sub">{m.label}</div>}
            </div>
            {i < PROGRESS_STEPS.length - 1 && <div className="progress-rail"><span style={{ width: done ? '100%' : '0%' }} /></div>}
          </div>
        )
      })}
    </div>
  )
}
