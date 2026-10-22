/** The case type on a case, and the one person who sets it (29 Sep 2026; 22 Oct 2026).
 *
 *  The department declares it, and may change its own declaration while the case is on its
 *  side. That is all this panel does now.
 *
 *  Until 22 Oct 2026 the Accountant General could also correct it here, with a remark entered
 *  in the audit log, the correction taking effect at the next verification. The office's
 *  decision is that the type is the department's to state: where the papers disagree with the
 *  declaration the officer says so to the DDO, or returns the case, rather than overwriting
 *  what the department filed. The AI's reading stays on the case beside the declaration and is
 *  what raises the question -- see the banner below. The server still accepts a correction
 *  (capabilities.correct_case_type, api/v2.py), so this is a screen that stopped offering it,
 *  not a door that was shut. */
import { useState } from 'react'
import type { CaseFull } from '../api/cases'
import { CASE_TYPE_LIST, CASE_TYPE_SOURCE_WORDS } from '../caseTypes'
import { caseTypeLabel } from '../labels'

export function CaseTypePanel({ c, busy, mayDeclare, onSet }:
  { c: CaseFull; busy: boolean; mayDeclare: boolean
    onSet: (body: { case_type: string; variant?: string }) => Promise<void> }) {
  const [open, setOpen] = useState(false)
  const [type, setType] = useState(c.case_type ?? '')
  const [column, setColumn] = useState(c.variant ?? '')
  const [error, setError] = useState<string | null>(null)
  const columns: string[] = []                           // the office type is its own checklist column
  const ready = !!type && (type !== c.case_type || (column || '') !== (c.variant || ''))

  async function go() {
    setError(null)
    try {
      await onSet({ case_type: type, variant: columns.includes(column) ? column : undefined })
      setOpen(false)
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }

  return (
    <div className="card">
      <div className="label" style={{ marginBottom: 6 }}>Case type</div>
      <div style={{ fontWeight: 600 }}>{c.case_type ? caseTypeLabel(c.case_type) : 'Not declared'}</div>
      <div className="help">{CASE_TYPE_SOURCE_WORDS[c.case_type_source ?? ''] ?? 'No type on the case.'}</div>
      {!deptSees(c) && c.detected_case_type && c.detected_case_type !== c.case_type && (
        <div className="banner warn" style={{ marginTop: 8 }}><span className="mark" aria-hidden="true">!</span>
          <div className="sub">The AI read the papers as <strong>{caseTypeLabel(c.detected_case_type)}</strong>.
            The type on the case is the department's declaration: confirm it with the DDO, who can change it
            once the case is back with them.</div></div>
      )}
      {mayDeclare && !open && (
        <button type="button" style={{ marginTop: 10, width: '100%' }} disabled={busy} onClick={() => { setType(c.case_type ?? ''); setColumn(c.variant ?? ''); setOpen(true) }}>
          Change the case type
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
          {error && <div className="banner bad"><span className="mark">!</span><div className="sub">{error}</div></div>}
          <div className="row" style={{ gap: 8 }}>
            <button className="primary" disabled={busy || !ready} onClick={go}>{busy ? 'Saving…' : 'Confirm'}</button>
            <button onClick={() => setOpen(false)} disabled={busy}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}

/** The AI's reading is the Accountant General's: the server sends none to a department. */
const deptSees = (c: CaseFull) => c.detected_case_type == null
