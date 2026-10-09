/** Signing authorities and specimen signatures: the master store both products read (C1, 9 Oct 2026).
 *
 *  The administrator adds an authority (department, post, officer, scope, dates, the authorising
 *  letter), uploads one to five specimens and the letter's scan, and closes an entry with an end
 *  date when a post changes hands. Nothing is deleted; every change is audited. The specimens are
 *  shown to the AG's side where a signature is checked, never to a DDO.
 */
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { departments, type Department } from '../../api/cases'
import { addLetter, addSpecimen, closeAuthority, createAuthority, filterAuthorities, finalizeGpfRegister, inForceWords,
         listAuthorities, updateAuthority, type Authority, type AuthorityInput, type ProductScope } from '../../api/signatories'
import { specimenImageUrl } from '../../api'
import { imageRefused, useMediaTokenVersion } from '../../auth/useMediaToken'

const PRODUCT_WORDS: Record<ProductScope, string> = { PENSION: 'Pension', GPF: 'GP Fund', BOTH: 'Pension and GP Fund' }
const EMPTY: AuthorityInput = { department_name: '', department_code: null, department_aliases: [], post: '', post_aliases: [],
                                officer_name: '', scope: '', effective_from: '', effective_to: null, letter_no: '', letter_date: null,
                                product_scope: 'BOTH', may_sign_for: false, stamp_text: '' }

const splitList = (s: string) => s.split(';').map(v => v.trim()).filter(Boolean)

export function Signatories() {
  const [rows, setRows] = useState<Authority[] | null>(null)
  const [depts, setDepts] = useState<Department[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [deptQ, setDeptQ] = useState('')
  const [postQ, setPostQ] = useState('')
  const [showClosed, setShowClosed] = useState(false)
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState<AuthorityInput>(EMPTY)
  const [aliasText, setAliasText] = useState({ department: '', post: '' })
  const [editing, setEditing] = useState<Authority | null>(null)
  const [closing, setClosing] = useState<{ a: Authority; to: string; reason: string } | null>(null)
  const [attempt, setAttempt] = useState(0)
  useMediaTokenVersion()

  const load = () => listAuthorities().then(r => { setRows(r); setError(null) })
    .catch(e => setError(e instanceof Error ? e.message : String(e)))
  useEffect(() => { load(); departments().then(setDepts).catch(() => {}) }, [attempt])

  const shown = useMemo(() => filterAuthorities(rows ?? [], { department: deptQ, post: postQ, showClosed }), [rows, deptQ, postQ, showClosed])
  const provisional = useMemo(() => (rows ?? []).filter(a => a.provisional && !a.closed).length, [rows])

  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setError(null)
    try { await fn(); await load() } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }

  function submitNew(e: FormEvent) {
    e.preventDefault()
    run(async () => {
      await createAuthority({ ...form, department_aliases: splitList(aliasText.department), post_aliases: splitList(aliasText.post),
                              department_code: form.department_code || null, effective_to: form.effective_to || null, letter_date: form.letter_date || null })
      setForm(EMPTY); setAliasText({ department: '', post: '' }); setAdding(false)
    })
  }

  function submitEdit(e: FormEvent) {
    e.preventDefault()
    if (!editing) return
    const a = editing
    run(async () => {
      await updateAuthority(a.id, { department_name: a.department_name, department_code: a.department_code, post: a.post,
                                    officer_name: a.officer_name ?? '', scope: a.scope ?? '', effective_from: a.effective_from,
                                    effective_to: a.effective_to, letter_no: a.letter_no ?? '', letter_date: a.letter_date,
                                    product_scope: a.product_scope, may_sign_for: a.may_sign_for, stamp_text: a.stamp_text ?? '',
                                    department_aliases: a.department_aliases, post_aliases: a.post_aliases })
      setEditing(null)
    })
  }

  function submitClose(e: FormEvent) {
    e.preventDefault()
    if (!closing) return
    const c = closing
    run(async () => { await closeAuthority(c.a.id, c.to || null, c.reason); setClosing(null) })
  }

  const field = (label: string, input: JSX.Element) => (
    <label style={{ display: 'grid', gap: 4, fontSize: 'var(--t-small)' }}><span className="muted">{label}</span>{input}</label>
  )

  return (
    <div className="screen container" style={{ paddingTop: 22 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 'var(--s4)', flexWrap: 'wrap' }}>
        <div>
          <h1>Signing authorities</h1>
          <p className="lead">Who may sign a sanction or a GP Fund paper, and their specimen signatures. Entries are closed with an end date, never deleted; every change is audited. Specimens are shown to the Accountant General&apos;s desk only.</p>
        </div>
        <div className="row" style={{ gap: 8 }}>
          {provisional > 0 && (
            <button type="button" disabled={busy} onClick={() => { if (window.confirm(`Mark the GP Fund register final? ${provisional} provisional entries become the office's list; the module stops calling them provisional.`)) run(finalizeGpfRegister) }}>
              Mark GP Fund register final ({provisional} provisional)
            </button>
          )}
          <button type="button" className="header-cta" onClick={() => setAdding(a => !a)}>{adding ? 'Cancel' : 'Add authority'}</button>
        </div>
      </div>
      {error && <div className="banner bad" role="alert"><span className="mark">!</span><div className="sub">{error} <button type="button" style={{ marginLeft: 8 }} onClick={() => setAttempt(a => a + 1)}>Retry</button></div></div>}

      {adding && (
        <form className="card" onSubmit={submitNew} style={{ marginTop: 'var(--s4)', display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          {field('Department (as printed)', <input required value={form.department_name} onChange={e => setForm({ ...form, department_name: e.target.value })} />)}
          {field('Department on the list', (
            <select value={form.department_code ?? ''} onChange={e => setForm({ ...form, department_code: e.target.value || null })}>
              <option value="">— not on the list —</option>
              {depts.map(d => <option key={d.code} value={d.code}>{d.name}</option>)}
            </select>))}
          {field('Department aliases (separate with ;)', <input value={aliasText.department} onChange={e => setAliasText({ ...aliasText, department: e.target.value })} placeholder="S&GAD; SGAD" />)}
          {field('Post / designation', <input required value={form.post} onChange={e => setForm({ ...form, post: e.target.value })} />)}
          {field('Post aliases (separate with ;)', <input value={aliasText.post} onChange={e => setAliasText({ ...aliasText, post: e.target.value })} />)}
          {field('Officer name', <input value={form.officer_name ?? ''} onChange={e => setForm({ ...form, officer_name: e.target.value })} />)}
          {field('Scope (what they may sanction)', <input value={form.scope ?? ''} onChange={e => setForm({ ...form, scope: e.target.value })} placeholder="PSA for ex-PCS/PSS & PMS BS-17" />)}
          {field('Product', (
            <select value={form.product_scope} onChange={e => setForm({ ...form, product_scope: e.target.value as ProductScope })}>
              {(Object.keys(PRODUCT_WORDS) as ProductScope[]).map(p => <option key={p} value={p}>{PRODUCT_WORDS[p]}</option>)}
            </select>))}
          {field('In force from', <input required type="date" value={form.effective_from} onChange={e => setForm({ ...form, effective_from: e.target.value })} />)}
          {field('In force to (blank = open)', <input type="date" value={form.effective_to ?? ''} onChange={e => setForm({ ...form, effective_to: e.target.value || null })} />)}
          {field('Authorising letter no.', <input value={form.letter_no ?? ''} onChange={e => setForm({ ...form, letter_no: e.target.value })} />)}
          {field('Letter date', <input type="date" value={form.letter_date ?? ''} onChange={e => setForm({ ...form, letter_date: e.target.value || null })} />)}
          {field('Stamp text (as it reads)', <input value={form.stamp_text ?? ''} onChange={e => setForm({ ...form, stamp_text: e.target.value })} />)}
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 'var(--t-small)' }}>
            <input type="checkbox" checked={!!form.may_sign_for} onChange={e => setForm({ ...form, may_sign_for: e.target.checked })} /> May sign for the authority
          </label>
          <div style={{ gridColumn: '1 / -1' }}><button type="submit" className="header-cta" disabled={busy}>Add authority</button></div>
        </form>
      )}

      <div className="row" style={{ gap: 10, marginTop: 'var(--s4)', flexWrap: 'wrap' }}>
        <input placeholder="Filter by department…" aria-label="Filter by department" value={deptQ} onChange={e => setDeptQ(e.target.value)} style={{ maxWidth: 260 }} />
        <input placeholder="Filter by post…" aria-label="Filter by post" value={postQ} onChange={e => setPostQ(e.target.value)} style={{ maxWidth: 260 }} />
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 'var(--t-small)' }}>
          <input type="checkbox" checked={showClosed} onChange={e => setShowClosed(e.target.checked)} /> Show closed entries
        </label>
        <span className="muted" style={{ fontSize: 'var(--t-small)' }}>{shown.length} of {(rows ?? []).length}</span>
      </div>

      <div style={{ display: 'grid', gap: 'var(--s3)', marginTop: 'var(--s3)' }}>
        {rows === null && !error && <div className="skeleton" style={{ height: 90 }} />}
        {rows && shown.length === 0 && <div className="card"><div className="empty">No signing authority matches.</div></div>}
        {shown.map(a => (
          <div className="card" key={a.id} style={{ opacity: a.closed ? 0.7 : 1 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--s3)', flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontWeight: 700 }}>{a.post}{a.officer_name ? ` — ${a.officer_name}` : ''}</div>
                <div className="muted" style={{ fontSize: 'var(--t-small)' }}>
                  {a.department_name}{a.department_code ? ` (${a.department_code})` : ''} · {PRODUCT_WORDS[a.product_scope]} · {inForceWords(a)}
                  {a.provisional ? ' · provisional register' : ''}{a.may_sign_for ? ' · may sign for the authority' : ''}
                </div>
                {a.scope && <div style={{ fontSize: 'var(--t-small)', marginTop: 4 }}>{a.scope}</div>}
                <div className="muted" style={{ fontSize: 'var(--t-small)', marginTop: 4 }}>
                  {a.letter_no ? `Letter ${a.letter_no}${a.letter_date ? ` of ${a.letter_date}` : ''}` : 'No authorising letter recorded'}
                  {a.has_letter ? ' · scan on file' : ''}
                </div>
              </div>
              {!a.closed && (
                <div className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
                  <button type="button" disabled={busy} onClick={() => setEditing({ ...a })}>Edit</button>
                  <button type="button" disabled={busy} onClick={() => setClosing({ a, to: '', reason: '' })}>Close</button>
                </div>
              )}
            </div>
            <div className="row" style={{ gap: 10, marginTop: 'var(--s3)', flexWrap: 'wrap', alignItems: 'flex-start' }}>
              {a.specimens.map(s => (
                <figure key={s.id} style={{ margin: 0, width: 160 }}>
                  <img src={specimenImageUrl(a.id, s.name)} alt={`Specimen of ${a.officer_name || a.post}`} onError={imageRefused}
                       style={{ width: '100%', border: '1px solid var(--line)', borderRadius: 8, background: '#fff' }} />
                  <figcaption className="muted" style={{ fontSize: 'var(--t-small)' }}>{s.note ?? 'Specimen'}</figcaption>
                </figure>
              ))}
              {a.specimens.length === 0 && <span className="muted" style={{ fontSize: 'var(--t-small)' }}>No specimen on file for {a.department_name}, {a.post}.</span>}
              {!a.closed && a.specimens.length < 5 && (
                <label className="chip" style={{ cursor: 'pointer' }}>
                  Upload specimen ({a.specimens.length}/5)
                  <input type="file" accept="image/jpeg,image/png" style={{ display: 'none' }} disabled={busy}
                         onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) run(() => addSpecimen(a.id, f)) }} />
                </label>
              )}
              {!a.closed && (
                <label className="chip" style={{ cursor: 'pointer' }}>
                  {a.has_letter ? 'Replace letter scan' : 'Upload authorising letter'}
                  <input type="file" accept="application/pdf,image/jpeg,image/png" style={{ display: 'none' }} disabled={busy}
                         onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) run(() => addLetter(a.id, f)) }} />
                </label>
              )}
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <form className="card" onSubmit={submitEdit} role="dialog" aria-label="Edit signing authority"
              style={{ marginTop: 'var(--s4)', display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <div style={{ gridColumn: '1 / -1', fontWeight: 700 }}>Edit: {editing.post}, {editing.department_name}</div>
          {field('Department (as printed)', <input required value={editing.department_name} onChange={e => setEditing({ ...editing, department_name: e.target.value })} />)}
          {field('Post / designation', <input required value={editing.post} onChange={e => setEditing({ ...editing, post: e.target.value })} />)}
          {field('Officer name', <input value={editing.officer_name ?? ''} onChange={e => setEditing({ ...editing, officer_name: e.target.value })} />)}
          {field('Scope', <input value={editing.scope ?? ''} onChange={e => setEditing({ ...editing, scope: e.target.value })} />)}
          {field('In force from', <input required type="date" value={editing.effective_from} onChange={e => setEditing({ ...editing, effective_from: e.target.value })} />)}
          {field('In force to', <input type="date" value={editing.effective_to ?? ''} onChange={e => setEditing({ ...editing, effective_to: e.target.value || null })} />)}
          {field('Letter no.', <input value={editing.letter_no ?? ''} onChange={e => setEditing({ ...editing, letter_no: e.target.value })} />)}
          {field('Letter date', <input type="date" value={editing.letter_date ?? ''} onChange={e => setEditing({ ...editing, letter_date: e.target.value || null })} />)}
          {field('Stamp text', <input value={editing.stamp_text ?? ''} onChange={e => setEditing({ ...editing, stamp_text: e.target.value })} />)}
          <div style={{ gridColumn: '1 / -1' }} className="row">
            <button type="submit" className="header-cta" disabled={busy}>Save</button>
            <button type="button" onClick={() => setEditing(null)} style={{ marginLeft: 8 }}>Cancel</button>
          </div>
        </form>
      )}

      {closing && (
        <form className="card" onSubmit={submitClose} role="dialog" aria-label="Close signing authority" style={{ marginTop: 'var(--s4)', display: 'grid', gap: 10 }}>
          <div style={{ fontWeight: 700 }}>Close: {closing.a.post}, {closing.a.department_name}</div>
          <p className="muted" style={{ fontSize: 'var(--t-small)', margin: 0 }}>The entry stays on record with its end date; a signature dated within its period is still compared with it. Add the new officer as a new entry.</p>
          {field('In force to (blank = today)', <input type="date" value={closing.to} onChange={e => setClosing({ ...closing, to: e.target.value })} />)}
          {field('Reason (the letter that replaced it, the transfer, …)', <input required minLength={5} value={closing.reason} onChange={e => setClosing({ ...closing, reason: e.target.value })} />)}
          <div className="row">
            <button type="submit" className="header-cta" disabled={busy}>Close entry</button>
            <button type="button" onClick={() => setClosing(null)} style={{ marginLeft: 8 }}>Cancel</button>
          </div>
        </form>
      )}
    </div>
  )
}
