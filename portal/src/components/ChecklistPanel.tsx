/** The checklist, and the officer's hand on it (api/checklist_actions.py).
 *
 *  The engine says which of the SOP's papers it found. Where it could not identify a page, or
 *  could not read it, it may report a paper "not found" that the department did file — and
 *  returning a case for a paper that is in the bundle is the error the office most wants to
 *  avoid. So an officer who can see the page can write what it is:
 *
 *    Write what a page is   a page the reader could not identify or read is this document, in
 *                           the officer's own words — and, if they say so, one of the
 *                           checklist's papers, which then counts as present
 *    Waive                  a paper not needed for this case, on a written ground -> waived
 *    Undo                   the engine's own reading applies again
 *
 *  A paper the reader reported NOT FOUND is not named into existence from its own row: it is
 *  either on one of the unrecognised pages (written up there) or it is waived. Every action is
 *  recorded against the officer; the engine's reading is kept beside it.
 */
import { useState } from 'react'
import { postChecklistAction, type CalculationGate, type Role } from '../api'
import { statusLabel } from '../labels'
import type { CaseReport, ChecklistItem } from '../types'

const MIN_GROUND = 15

const TONE: Record<string, string> = {
  PRESENT: 'low', MISSING: 'high', DEFECTIVE: 'medium', NOT_APPLICABLE: 'neutral', WAIVED: 'neutral',
}

export function ChecklistPanel(
  { report, runId, role, officer, mayDecide, onPage, onChange }:
  { report: CaseReport; runId: string; role: Role; officer: string; mayDecide: boolean
    onPage: (page: number, doc: string) => void
    onChange: (report: CaseReport, gate: CalculationGate) => void },
) {
  const [error, setError] = useState<string | null>(null)
  const checklist = report.checklist
  const nameable = report.nameable_pages ?? report.pages_unaccounted ?? []
  const named = report.named_documents ?? []
  const open = checklist?.items.filter(i => i.status === 'MISSING' || i.status === 'DEFECTIVE') ?? []

  async function act(body: Parameters<typeof postChecklistAction>[1]) {
    setError(null)
    try {
      const r = await postChecklistAction(runId, body)
      onChange(r.report, r.gate)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      throw e
    }
  }

  return (
    <div className="card">
      {nameable.length > 0 && (
        // Coverage first, result second. A shortcoming list is only as good as the pages
        // behind it, and a client who knows their case is complete will trust an honest
        // "we could not read these" far sooner than a confident list of things we say
        // are absent.
        <div className="banner bad" style={{ marginBottom: 'var(--s4)' }}>
          <span className="mark" aria-hidden="true">?</span>
          <div style={{ flex: 1 }}>
            <div className="title">
              {nameable.length} page{nameable.length > 1 ? 's' : ''} could not be identified or read
            </div>
            <div className="sub">
              Page{nameable.length > 1 ? 's' : ''}{' '}
              {nameable.map(p => (
                <button key={p} className="chip" style={{ cursor: 'pointer', marginRight: 4 }}
                        onClick={() => onPage(p, 'not identified')}>⧉ p.{p}</button>
              ))}
              {' '}{nameable.length > 1 ? 'were' : 'was'} not recognised as a document, or could not
              be read. Any requirement shown below as <strong>not found</strong> may be on
              {nameable.length > 1 ? ' one of them' : ' it'} — open the page and write what it is
              before returning the case to the department.
            </div>
            {mayDecide && (
              <NamePages nameable={nameable} open={open}
                         onName={(pages, itemId, name) => act({
                           action: 'NAME', pages, document_name: name, officer, role,
                           ...(itemId ? { item_id: itemId } : {}) })} />
            )}
          </div>
        </div>
      )}

      {!checklist ? (
        <div className="empty">
          <strong>No checklist was applied.</strong>
          <div style={{ marginTop: 'var(--s2)' }}>{report.checklist_gap}</div>
        </div>
      ) : (<>
        <div className={`banner ${checklist.result === 'COMPLETE' ? 'good' : 'warn'}`}
             style={{ marginBottom: 'var(--s4)' }}>
          <span className="mark" aria-hidden="true">{checklist.result === 'COMPLETE' ? '✓' : '!'}</span>
          <div>
            <div className="title">
              {checklist.result === 'COMPLETE' ? 'Checklist complete' : 'Checklist incomplete'}
              {' '}<span className="muted" style={{ fontWeight: 600 }}>
                {checklist.satisfied}/{checklist.required}
              </span>
            </div>
            <div className="sub">{checklist.result_line}</div>
          </div>
        </div>

        {error && (
          <div className="banner bad" style={{ marginBottom: 'var(--s3)' }}>
            <span className="mark" aria-hidden="true">!</span><div className="sub">{error}</div>
          </div>
        )}

        <table>
          <thead><tr><th style={{ width: 62 }}>Item</th><th>Requirement</th>
            <th style={{ width: 118 }}>Status</th><th style={{ width: 130 }}>Located</th>
            {mayDecide && <th style={{ width: 200 }}>Officer</th>}</tr></thead>
          <tbody>
            {checklist.items.map(i => (
              <ItemRow key={i.id} i={i} mayDecide={mayDecide} onPage={onPage}
                       onWaive={ground => act({ action: 'WAIVE', item_id: i.id, ground, officer, role })}
                       onUndo={() => act(i.officer_action?.name_id
                         ? { action: 'CLEAR', name_id: i.officer_action.name_id, officer, role }
                         : { action: 'CLEAR', item_id: i.id, officer, role })} />
            ))}
          </tbody>
        </table>

        {named.length > 0 && (
          <div style={{ marginTop: 'var(--s4)' }}>
            <div className="label" style={{ marginBottom: 6 }}>Pages written up by an officer</div>
            <table>
              <tbody>
                {named.map(n => (
                  <tr key={n.name_id}>
                    <td>{n.name}{n.item_id && <span className="muted" style={{ fontSize: 12 }}> · counts as {n.item_id}</span>}</td>
                    <td style={{ width: 160 }}>{n.pages.map(p => (
                      <button key={p} className="chip" style={{ cursor: 'pointer' }}
                              onClick={() => onPage(p, n.name)}>p.{p}</button>))}</td>
                    <td className="muted" style={{ width: 230, fontSize: 'var(--t-small)' }}>
                      {n.officer} · {n.at.replace('T', ' ')}
                      {mayDecide && <> · <button className="ghost" style={{ padding: 0, fontSize: 'var(--t-small)' }}
                        onClick={() => act({ action: 'CLEAR', name_id: n.name_id, officer, role }).catch(() => {})}>Undo</button></>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </>)}
    </div>
  )
}


function ItemRow(
  { i, mayDecide, onPage, onWaive, onUndo }:
  { i: ChecklistItem; mayDecide: boolean
    onPage: (page: number, doc: string) => void
    onWaive: (ground: string) => Promise<void>
    onUndo: () => Promise<void> },
) {
  const [waiving, setWaiving] = useState(false)
  const [ground, setGround] = useState('')
  const [busy, setBusy] = useState(false)
  const settled = i.officer_action
  const canWaive = i.status === 'MISSING' || i.status === 'DEFECTIVE'

  async function run(fn: () => Promise<void>) {
    setBusy(true)
    try { await fn(); setWaiving(false); setGround('') } catch { /* shown above */ }
    finally { setBusy(false) }
  }

  return (
    <tr>
      <td className="mono">{i.id}</td>
      <td>
        {i.requirement}
        {i.reason && <div className="muted" style={{ fontSize: 12 }}>{i.reason}</div>}
        {waiving && (
          <div style={{ marginTop: 8 }}>
            <div className="label" style={{ marginBottom: 4 }}>
              Why this paper is not needed, or its defect does not stop the case (at least {MIN_GROUND} characters)
            </div>
            <textarea rows={2} value={ground} onChange={e => setGround(e.target.value)} autoFocus
                      placeholder="Recorded against your name in the audit trail…" />
            <div className="row" style={{ gap: 'var(--s2)', marginTop: 6 }}>
              <button className="gold" disabled={busy || ground.trim().length < MIN_GROUND}
                      onClick={() => run(() => onWaive(ground.trim()))}>
                {busy ? 'Recording…' : 'Approve without this paper'}</button>
              <button onClick={() => setWaiving(false)}>Cancel</button>
            </div>
          </div>
        )}
      </td>
      <td>
        <span className={`pill ${TONE[i.status] ?? 'neutral'}`}>{statusLabel(i.status)}</span>
        {settled && i.engine_status && (
          <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>read as {statusLabel(i.engine_status).toLowerCase()}</div>
        )}
      </td>
      <td>{i.located?.map(p => (
        <button key={p} className="chip" style={{ cursor: 'pointer' }}
                onClick={() => onPage(p, i.requirement)}>p.{p}</button>))}</td>
      {mayDecide && (
        <td style={{ fontSize: 'var(--t-small)' }}>
          {settled ? (<>
            <div className="muted">{settled.action === 'WAIVE' ? 'Approved' : 'Written up'} by {settled.officer}</div>
            <div className="muted">{settled.at.replace('T', ' ')}</div>
            <button className="ghost" disabled={busy} style={{ padding: 0, fontSize: 'var(--t-small)' }}
                    onClick={() => run(onUndo)}>Undo</button>
          </>) : canWaive && !waiving ? (
            <button style={{ padding: '5px 10px', fontSize: 'var(--t-small)' }}
                    onClick={() => setWaiving(true)}>Approve</button>
          ) : null}
        </td>
      )}
    </tr>
  )
}


/** Write what an unrecognised or unreadable page is: its name, and optionally the checklist paper it is. */
function NamePages(
  { nameable, open, onName }:
  { nameable: number[]; open: ChecklistItem[]
    onName: (pages: number[], itemId: string | null, name: string) => Promise<void> },
) {
  const [on, setOn] = useState(false)
  const [picked, setPicked] = useState<number[]>([])
  const [name, setName] = useState('')
  // Optionally, which of the checklist's missing papers this is. '' = none of them.
  const [target, setTarget] = useState('')
  const [busy, setBusy] = useState(false)

  if (!on) {
    return <button style={{ marginTop: 8, padding: '6px 12px', fontSize: 'var(--t-small)' }}
                   onClick={() => setOn(true)}>Write what these pages are…</button>
  }
  const toggle = (p: number) => setPicked(x => x.includes(p) ? x.filter(y => y !== p) : [...x, p].sort((a, b) => a - b))
  const ready = picked.length > 0 && name.trim().length >= 3
  return (
    <div style={{ marginTop: 10, background: '#fff', border: '1px solid var(--line)', borderRadius: 10,
                  padding: 'var(--s3)', color: 'var(--ink)' }}>
      <div className="label" style={{ marginBottom: 4 }}>1. The page(s)</div>
      <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
        {nameable.map(p => (
          <button key={p} onClick={() => toggle(p)} className={picked.includes(p) ? 'primary' : ''}
                  style={{ padding: '4px 10px', fontSize: 'var(--t-small)' }}>p.{p}</button>
        ))}
      </div>
      <div className="label" style={{ margin: '10px 0 4px' }}>2. The document's name</div>
      <input value={name} onChange={e => setName(e.target.value)} style={{ maxWidth: 520 }}
             placeholder="As the office calls it — e.g. Succession certificate, Nikah nama" />
      {open.length > 0 && (<>
        <div className="label" style={{ margin: '10px 0 4px' }}>
          3. Is it one of the papers the checklist did not find? (optional)
        </div>
        <select value={target} onChange={e => setTarget(e.target.value)} style={{ maxWidth: 520 }}>
          <option value="">No — not a checklist paper</option>
          {open.map(i => <option key={i.id} value={i.id}>Yes — {i.id}, {i.requirement}</option>)}
        </select>
      </>)}
      <div className="row" style={{ gap: 'var(--s2)', marginTop: 10 }}>
        <button className="gold" disabled={!ready || busy}
                onClick={async () => {
                  setBusy(true)
                  try {
                    await onName(picked, target || null, name.trim())
                    setOn(false); setPicked([]); setName(''); setTarget('')
                  } catch { /* shown above */ } finally { setBusy(false) }
                }}>{busy ? 'Recording…' : 'Record'}</button>
        <button onClick={() => setOn(false)}>Cancel</button>
      </div>
    </div>
  )
}
