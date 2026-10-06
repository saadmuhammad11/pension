/** The case type on a case, and who may change it (29 Sep 2026).
 *
 *  A DDO changes the department's own declaration while the case is on its side, no remark needed.
 *  The Accountant General and the administrator correct it at any point, with a remark that is
 *  entered in the audit log; the AI's own reading stays on the case beside it, and the
 *  correction takes effect at the next verification. */
import { useState } from 'react'
import type { CaseFull } from '../api/cases'
import { CASE_TYPE_LIST, CASE_TYPE_SOURCE_WORDS } from '../caseTypes'
import { caseTypeLabel } from '../labels'

export function CaseTypePanel({ c, busy, mayCorrect, mayDeclare, onSet }:
  { c: CaseFull; busy: boolean; mayCorrect: boolean; mayDeclare: boolean
    onSet: (body: { case_type: string; variant?: string; remark?: string }) => Promise<void> }) {
  const [open, setOpen] = useState(false)
  const [type, setType] = useState(c.case_type ?? '')
  const [column, setColumn] = useState(c.variant ?? '')
  const [remark, setRemark] = useState('')
  const [error, setError] = useState<string | null>(null)
  const may = mayCorrect || mayDeclare
  const needsRemark = mayCorrect && !mayDeclare
  const columns: string[] = []                           // the office type is its own checklist column
  const ready = !!type && (!needsRemark || remark.trim().length >= 5) && (type !== c.case_type || (column || '') !== (c.variant || ''))

  async function go() {
    setError(null)
    try {
      await onSet({ case_type: type, variant: columns.includes(column) ? column : undefined, remark: remark.trim() || undefined })
      setOpen(false); setRemark('')
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }

  return (
    <div className="card">
      <div className="label" style={{ marginBottom: 6 }}>Case type</div>
      <div style={{ fontWeight: 600 }}>{c.case_type ? caseTypeLabel(c.case_type) : 'Not declared'}</div>
      <div className="help">{CASE_TYPE_SOURCE_WORDS[c.case_type_source ?? ''] ?? 'No type on the case.'}</div>
      {!deptSees(c) && c.detected_case_type && c.detected_case_type !== c.case_type && (
        <div className="banner warn" style={{ marginTop: 8 }}><span className="mark" aria-hidden="true">!</span>
          <div className="sub">The AI read the papers as <strong>{caseTypeLabel(c.detected_case_type)}</strong>. Confirm the type with the DDO, or correct it here and verify the case again.</div></div>
      )}
      {may && !open && (
        <button type="button" style={{ marginTop: 10, width: '100%' }} disabled={busy} onClick={() => { setType(c.case_type ?? ''); setColumn(c.variant ?? ''); setOpen(true) }}>
          {mayCorrect && !mayDeclare ? 'Correct the case type' : 'Change the case type'}
        </button>
      )}
      {open && (
        <div className="stack" style={{ marginTop: 10, gap: 8 }}>
          <div className="field">
            <label className="label" htmlFor="ct-type">Case type</label>
            <select id="ct-type" value={type} onChange={e => { setType(e.target.value); setColumn('') }}>
              <option value="">— choose —</option>
              {CASE_TYPE_LIST.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </div>
          {columns.length > 1 && (
            <div className="field">
              <label className="label" htmlFor="ct-col">Who is claiming</label>
              <select id="ct-col" value={column} onChange={e => setColumn(e.target.value)}>
                <option value="">— not stated —</option>
                {columns.map(v => <option key={v} value={v}>{v.replace(/_/g, ' ').toLowerCase()}</option>)}
              </select>
            </div>
          )}
          {needsRemark && (
            <textarea rows={3} value={remark} onChange={e => setRemark(e.target.value)} placeholder="Why the type is being corrected (required; entered in the audit log)…" />
          )}
          {error && <div className="banner bad"><span className="mark">!</span><div className="sub">{error}</div></div>}
          <div className="row" style={{ gap: 8 }}>
            <button className="primary" disabled={busy || !ready} onClick={go}>{busy ? 'Saving…' : 'Confirm'}</button>
            <button onClick={() => setOpen(false)} disabled={busy}>Cancel</button>
          </div>
          {mayCorrect && <div className="help">The correction takes effect at the next verification: press “Verify the case again” afterwards.</div>}
        </div>
      )}
    </div>
  )
}

/** The AI's reading is the Accountant General's: the server sends none to a department. */
const deptSees = (c: CaseFull) => c.detected_case_type == null
