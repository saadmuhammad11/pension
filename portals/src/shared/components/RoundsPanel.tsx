/** Each submission round of a case, and for the AG what the latest one changed (30 Sep 2026).
 *
 *  A returned case comes back with the papers the AG asked for; its verification reads only
 *  those and reuses the rest (pipeline.carryover). The AG needs to see, at a glance: what was
 *  asked, what came, whether it resolved what was asked, and whether it raised anything new.
 *  A department sees only its side: what was asked of it, and whether that is now on file. */
import { useEffect, useState } from 'react'
import { fetchRounds, type CaseRound, type RoundCheck } from '../api/cases'

const RESOLUTION: Record<string, { word: string; cls: string }> = {
  RESOLVED: { word: 'Now on file', cls: 'low' }, WAIVED: { word: 'Waived', cls: 'low' },
  NO_LONGER_REQUIRED: { word: 'No longer required', cls: 'neutral' },
  STILL_MISSING: { word: 'Still missing', cls: 'high' }, STILL_DEFECTIVE: { word: 'Still defective', cls: 'high' },
  FOR_OFFICER: { word: 'For you to check', cls: 'medium' },
}
const DOC_STATUS: Record<string, string> = { NEW: 'new', REPLACEMENT: 'replacement', SUPERSEDED: 'withdrawn', EARLIER: 'earlier' }
const secs = (s?: number | null) => s == null ? '' : s < 90 ? `${Math.round(s)} s` : `${(s / 60).toFixed(1)} min`

export function RoundsPanel({ caseId, refreshKey, onlyLatest = false, agView }:
  { caseId: string; refreshKey: unknown; onlyLatest?: boolean; agView: boolean }) {
  const [rounds, setRounds] = useState<CaseRound[] | null>(null)
  useEffect(() => { fetchRounds(caseId).then(setRounds).catch(() => setRounds([])) }, [caseId, refreshKey])
  if (!rounds || !rounds.length) return null
  const shown = onlyLatest ? rounds.slice(-1) : [...rounds].reverse()
  if (onlyLatest && (shown[0].submission_no <= 1 || !(shown[0].checks ?? []).length)) return null
  return (
    <div className="stack" style={{ gap: 'var(--s3)' }}>
      {shown.map(r => <Round key={r.submission_no} r={r} agView={agView} latest={onlyLatest} />)}
    </div>
  )
}

function Round({ r, agView, latest }: { r: CaseRound; agView: boolean; latest: boolean }) {
  const check: RoundCheck | undefined = (r.checks ?? []).filter(c => c.finished_at).slice(-1)[0] ?? (r.checks ?? []).slice(-1)[0]
  const req = r.requests
  return (
    <div className="card">
      <div className="row" style={{ gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0 }}>{latest ? `What changed in submission ${r.submission_no}` : `Submission ${r.submission_no}`}</h3>
        {r.closed_action && !latest && <span className="muted" style={{ fontSize: 'var(--t-small)' }}>closed: {r.closed_action.replace(/_/g, ' ').toLowerCase()}</span>}
        {agView && check && (
          <span className="muted" style={{ fontSize: 'var(--t-small)', marginLeft: 'auto' }}>
            {check.mode === 'INCREMENTAL'
              ? `Read ${check.steps.pages_read ?? '?'} new page(s), reused ${check.steps.pages_reused ?? '?'} from submission ${check.base_submission_no ?? '?'}`
              : 'Full examination'}
            {check.duration_s != null ? ` · ${secs(check.duration_s)}` : ''}
          </span>
        )}
      </div>

      {req.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div className="label">Asked for</div>
          {req.map((q, i) => (
            <div key={i} style={{ fontSize: 'var(--t-small)', marginTop: 4 }}>
              <span className="muted">{q.action === 'AUTO_RETURN' ? 'Returned by the examination' : q.action === 'REQUEST_DOCS' ? 'Documents requested' : 'Returned'}{q.by ? ` by ${q.by}` : ''}, {q.at.replace('T', ' ').slice(0, 16)}</span>
              {q.remark && <div>“{q.remark}”</div>}
            </div>
          ))}
          <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 'var(--t-small)' }}>
            {(agView && check ? check.resolution : null)?.map((x, i) => (
              <li key={i}>
                <strong>{x.id ?? x.label}</strong> {x.id ? x.requirement : x.pages?.length ? `pages ${x.pages.join(', ')}` : ''}
                {x.note ? <span className="muted"> — {x.note}</span> : null}
                {' '}<span className={`pill ${RESOLUTION[x.resolution]?.cls ?? 'neutral'}`}>{RESOLUTION[x.resolution]?.word ?? x.resolution}</span>
                {x.located?.length ? <span className="muted"> p.{x.located.join(', ')}</span> : null}
              </li>
            )) ?? (r.requested_items?.length ? r.requested_items.map((x, i) => (
              <li key={i}><strong>{x.id ?? ''}</strong> {x.label} {x.on_file ? <span className="pill low">on file</span> : null}</li>
            )) : req.flatMap(q => q.items).map((x, i) => (
              <li key={i}><strong>{x.id ?? x.label}</strong> {x.id ? x.requirement : x.pages?.length ? `pages ${x.pages.join(', ')}` : ''}{x.note ? <span className="muted"> — {x.note}</span> : null}</li>
            )))}
          </ul>
        </div>
      )}

      {agView && check ? (
        <div style={{ marginTop: 10 }}>
          <div className="label">Documents</div>
          <div className="row" style={{ gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
            {check.documents.filter(d => !latest || d.status !== 'EARLIER').map(d => (
              <span key={d.id} className={`chip`} style={{ opacity: d.status === 'SUPERSEDED' ? .6 : 1 }}>
                {d.filename} <span className="muted">· {DOC_STATUS[d.status] ?? d.status}</span>
              </span>
            ))}
          </div>
          {check.changes && (check.changes.new || check.changes.cleared) && (
            <div style={{ marginTop: 10, fontSize: 'var(--t-small)' }}>
              <div className="label">Findings against submission {check.base_submission_no}</div>
              {(check.changes.new ?? []).map(f => (
                <div key={`n${f.id}`}><span className="pill medium">new</span> <strong>{f.id}</strong> {f.title}{f.from_new_documents ? <span className="muted"> · from the new papers</span> : null}</div>
              ))}
              {(check.changes.cleared ?? []).map(f => (
                <div key={`c${f.id}`}><span className="pill low">cleared</span> <span style={{ textDecoration: 'line-through' }}>{f.title}</span></div>
              ))}
              <div className="muted" style={{ marginTop: 4 }}>
                {(check.changes.unchanged ?? []).length} unchanged
                {(check.carried.dispositions ?? []).length ? ` · ${(check.carried.dispositions ?? []).length} clearance(s) carried from submission ${check.base_submission_no}` : ''}
              </div>
            </div>
          )}
        </div>
      ) : !agView && r.documents.length > 0 && !latest ? (
        <div style={{ marginTop: 10, fontSize: 'var(--t-small)' }}>
          <div className="label">Papers sent</div>
          {r.documents.map(d => <div key={d.id}>{d.filename}{d.replaces ? <span className="muted"> · in place of an earlier paper</span> : null}</div>)}
        </div>
      ) : null}
    </div>
  )
}
