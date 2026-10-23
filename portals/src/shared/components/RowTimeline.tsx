/** A department's view of where one case is, on its register row (29 Sep 2026): three steps --
 *  Sent, Processing at the Accountant General, Outcome -- with the outcome named as Returned,
 *  Approved or Rejected. A DDO reads the whole register at a glance without opening a case. */
import { fmtDateTime } from '../fmt'
import type { CaseStatus, CaseSummary } from '../api/cases'

type Step = { label: string; state: 'done' | 'active' | 'todo'; tone?: 'ok' | 'bad' | 'wait'; sub?: string }

const fmt = (iso: string | null | undefined) => fmtDateTime(iso)

export function timelineFor(r: CaseSummary): Step[] {
  const s: CaseStatus = r.status
  const last = r.last_event?.at ?? r.updated_at
  const sent = r.submission_no > 1 ? `Resubmitted ${fmt(last)}` : `Sent ${fmt(r.created_at)}`
  if (s === 'DRAFT' || s === 'AI_CHECKED')
    return [{ label: 'Not yet sent', state: 'active', tone: 'wait', sub: 'Submit to the Office of the Accountant General' },
            { label: 'Processing', state: 'todo' }, { label: 'Outcome', state: 'todo' }]
  if (s === 'FORWARDED' || s === 'AI_CHECKING' || s === 'AI_FAILED' || s === 'UNDER_REVIEW')
    return [{ label: 'Sent', state: 'done', sub: sent },
            { label: 'Processing', state: 'active', tone: 'wait', sub: 'At the Office of the Accountant General' },
            { label: 'Outcome', state: 'todo' }]
  if (s === 'RETURNED' || s === 'DOCS_REQUESTED')
    return [{ label: 'Sent', state: 'done', sub: sent }, { label: 'Processed', state: 'done' },
            { label: s === 'RETURNED' ? 'Returned' : 'Documents requested', state: 'active', tone: 'bad', sub: `${fmt(last)} · attach and resubmit` }]
  if (s === 'APPROVED')
    return [{ label: 'Sent', state: 'done', sub: sent }, { label: 'Processed', state: 'done' },
            { label: 'Approved', state: 'done', tone: 'ok', sub: fmt(last) }]
  return [{ label: 'Sent', state: 'done', sub: sent }, { label: 'Processed', state: 'done' },
          { label: 'Rejected', state: 'done', tone: 'bad', sub: fmt(last) }]
}

export function RowTimeline({ row }: { row: CaseSummary }) {
  const steps = timelineFor(row)
  const current = steps.find(s => s.state === 'active') ?? steps[steps.length - 1]
  // On a row only the step that matters carries its note; the others are the ticks.
  const noted = (st: Step) => st === current
  return (
    <div className="row-timeline" role="img" aria-label={`${current.label}${current.sub ? `: ${current.sub}` : ''}`}>
      {steps.map((st, i) => (
        <div key={i} className={`rt-step is-${st.state}${st.tone ? ` is-${st.tone}` : ''}`}>
          <span className="rt-dot" aria-hidden="true">{st.state === 'done' && st.tone !== 'bad' ? '✓' : st.tone === 'bad' ? '!' : ''}</span>
          <span className="rt-text">
            <span className="rt-label">{st.label}</span>
            {st.sub && noted(st) && <span className="rt-sub">{st.sub}</span>}
          </span>
          {i < steps.length - 1 && <span className="rt-rail" aria-hidden="true" />}
        </div>
      ))}
    </div>
  )
}
