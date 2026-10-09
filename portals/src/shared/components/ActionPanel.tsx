/** The actions this user may take on this case, each with its remark.
 *
 *  The list comes from the server (`allowed_actions`): the panel never guesses what a role may
 *  do. Remarks are required by the rules in ACTION_META and again by the server. The parent can
 *  open an action from its own big button (`open`). */
import { useEffect, useState } from 'react'
import { ACTION_META, STATUS_META, type CaseAction, type CaseStatus, type RequestItem } from '../api/cases'

const STATUSES: CaseStatus[] = ['DRAFT', 'AI_CHECKED', 'FORWARDED', 'UNDER_REVIEW', 'APPROVED', 'REJECTED', 'RETURNED', 'DOCS_REQUESTED']
const ORDER: CaseAction[] = ['FORWARD', 'APPROVE', 'REQUEST_DOCS', 'RETURN', 'REJECT', 'OVERRIDE']

export function ActionPanel(
  { actions, hasIssues, busy, onAct, open: openProp, onOpenChange, checklist = [], status }:
  { actions: CaseAction[]
    hasIssues: boolean
    /** The case's present status, so the override says what it changes from (F14). */
    status?: CaseStatus
    busy: boolean
    onAct: (action: CaseAction, remark: string, toStatus?: CaseStatus, items?: RequestItem[]) => Promise<void>
    open?: CaseAction | null
    onOpenChange?: (a: CaseAction | null) => void
    /** The case's checklist, for naming exactly what a return asks for (30 Sep 2026). */
    checklist?: { id: string; requirement: string; status: string }[] },
) {
  const [open, setOpenState] = useState<CaseAction | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [other, setOther] = useState('')
  const [otherPages, setOtherPages] = useState('')
  const asking = open === 'RETURN' || open === 'REQUEST_DOCS'
  useEffect(() => {
    if (asking) {
      setPicked(new Set(checklist.filter(i => i.status === 'MISSING' || i.status === 'DEFECTIVE').map(i => i.id)))
      setOther(''); setOtherPages('')
    }
  }, [open])  // eslint-disable-line react-hooks/exhaustive-deps
  const items = (): RequestItem[] => {
    const out: RequestItem[] = checklist.filter(i => picked.has(i.id)).map(i => ({ id: i.id }))
    const pages = otherPages.split(/[^0-9]+/).filter(Boolean).map(Number).filter(n => n > 0)
    if (other.trim().length >= 3 || pages.length) out.push({ label: other.trim(), pages })
    return out
  }
  const [remark, setRemark] = useState('')
  const [toStatus, setToStatus] = useState<CaseStatus>('RETURNED')
  const [error, setError] = useState<string | null>(null)
  const [touched, setTouched] = useState(false)     // the "N more characters" hint waits until the officer has typed
  const setOpen = (a: CaseAction | null) => { setOpenState(a); onOpenChange?.(a); if (a) { setRemark(''); setError(null); setTouched(false) } }
  useEffect(() => { if (openProp !== undefined && openProp !== open) { setOpenState(openProp); if (openProp) { setRemark(''); setError(null) } } }, [openProp])  // eslint-disable-line react-hooks/exhaustive-deps

  const decisions = ORDER.filter(a => actions.includes(a))
  if (!decisions.length) return null

  const meta = open ? ACTION_META[open] : null
  const required = !!meta && (meta.needsRemark === 'always' || (meta.needsRemark === 'issues' && hasIssues))
  const minLen = open === 'APPROVE' && hasIssues ? 15 : required ? 3 : 0
  const ready = remark.trim().length >= minLen

  async function go() {
    if (!open) return
    setError(null)
    try {
      await onAct(open, remark.trim(), open === 'OVERRIDE' ? toStatus : undefined, asking ? items() : undefined)
      setOpen(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const cls = (tone: string) => tone === 'primary' ? 'primary' : tone === 'gold' ? 'gold' : ''

  return (
    <div className="card">
      <div className="label" style={{ marginBottom: 8 }}>{open ? 'Confirm' : 'What you can do'}</div>
      {!open ? (
        <div className="stack" style={{ gap: 8 }}>
          {decisions.map(a => (
            <button key={a} className={cls(ACTION_META[a].tone)} disabled={busy}
                    style={{ width: '100%', justifyContent: 'flex-start', textAlign: 'left',
                             ...(ACTION_META[a].tone === 'danger' ? { color: 'var(--red)', borderColor: 'var(--red)' } : {}) }}
                    onClick={() => setOpen(a)}>
              {ACTION_META[a].label}
            </button>
          ))}
        </div>
      ) : (
        <div>
          <h3 style={{ margin: '0 0 6px' }}>{meta!.label}</h3>
          {meta!.prompt && <p className="help" style={{ margin: '0 0 8px' }}>{meta!.prompt}</p>}
          {open === 'OVERRIDE' && (
            <div className="field" style={{ marginBottom: 8 }}>
              <label className="label" htmlFor="override-to">Set the case to</label>
              <select id="override-to" value={toStatus} onChange={e => setToStatus(e.target.value as CaseStatus)}>
                {STATUSES.map(s => <option key={s} value={s}>{STATUS_META[s].label}</option>)}
              </select>
              <div className="help" style={{ marginTop: 4 }}>
                Setting from {status ? STATUS_META[status].label : 'the present status'} to {STATUS_META[toStatus].label}. This is audited.
              </div>
            </div>
          )}
          {asking && (
            <div className="field" style={{ marginBottom: 8 }}>
              <label className="label">What the department must send</label>
              {checklist.filter(i => !['NOT_APPLICABLE', 'NOT_REQUIRED', 'FOUND_NOT_REQUIRED'].includes(i.status)).length > 0 && (
                <div style={{ maxHeight: 220, overflowY: 'auto', border: '1px solid var(--line)', borderRadius: 8, padding: '6px 8px' }}>
                  {checklist.filter(i => !['NOT_APPLICABLE', 'NOT_REQUIRED', 'FOUND_NOT_REQUIRED'].includes(i.status)).map(i => (
                    <label key={i.id} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 'var(--t-small)', padding: '3px 0' }}>
                      <input type="checkbox" checked={picked.has(i.id)} style={{ marginTop: 3 }}
                             onChange={e => setPicked(s => { const n = new Set(s); if (e.target.checked) n.add(i.id); else n.delete(i.id); return n })} />
                      <span><strong>{i.id}</strong> {i.requirement}{i.status === 'MISSING' || i.status === 'DEFECTIVE' ? <span className="muted"> · {i.status.toLowerCase()}</span> : null}</span>
                    </label>
                  ))}
                </div>
              )}
              <div className="row" style={{ gap: 8, marginTop: 6 }}>
                <input value={other} onChange={e => setOther(e.target.value)} placeholder="Another document, in your words" aria-label="Another document, in your words" style={{ flex: 2 }} />
                <input value={otherPages} onChange={e => setOtherPages(e.target.value)} placeholder="Pages, e.g. 5, 6" aria-label="Pages concerned" style={{ flex: 1 }} />
              </div>
              <div className="help" style={{ marginTop: 4 }}>The next submission is checked against this list, and only the papers it adds are read again.</div>
            </div>
          )}
          <textarea rows={4} value={remark} onChange={e => { setRemark(e.target.value); setTouched(true) }} autoFocus aria-label="Your remark"
                    placeholder={required ? `Your remark (required${minLen > 3 ? `, at least ${minLen} characters` : ''})…` : 'Your remark (optional)…'} />
          {required && !ready && touched && <div className="help" style={{ marginTop: 4 }}>{minLen - remark.trim().length} more character{minLen - remark.trim().length === 1 ? '' : 's'} needed.</div>}
          {error && <div className="banner bad" style={{ marginTop: 8 }}><span className="mark">!</span><div className="sub">{error}</div></div>}
          <div className="row" style={{ gap: 8, marginTop: 10 }}>
            <button className={cls(meta!.tone) || 'primary'} disabled={busy || !ready} onClick={go}>
              {busy ? 'Saving…' : `Confirm: ${meta!.label.toLowerCase()}`}
            </button>
            <button onClick={() => setOpen(null)} disabled={busy}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}
