/** A new case, in numbered steps: the case type, the papers, whose case it is, save. A pension
 *  case or a GP Fund claim (28 Sep 2026), which needs the kind of claim the GP Fund module will
 *  read it as.
 *
 *  The case type (29 Sep 2026) comes first and is mandatory for a pension case: it decides which
 *  documents the office asks for, so the list is shown as soon as the type is chosen, before
 *  anything is attached. The list of types is config/case_types.json, shared with the rules. */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { GPF_KINDS, PRODUCT_WORDS, createCase, departments, fetchCaseTypes, newIdempotencyKey, type CaseTypeInfo, type Department, type Product } from '../api/cases'
import { checkFiles, progressWords } from '../upload/limits'
import { useSession } from '../auth/AuthProvider'
import { CASE_TYPE_LIST } from '../caseTypes'

const kb = (n: number) => n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1048576).toFixed(1)} MB`

export function Upload({ product, onCreated, onCancel }: { product: Product; onCreated: (caseId: string) => void; onCancel: () => void }) {
  const { can, user } = useSession()
  const [files, setFiles] = useState<File[]>([])
  const [depts, setDepts] = useState<Department[]>([])
  const [department, setDepartment] = useState('')
  const [claimant, setClaimant] = useState('')
  const [caseType, setCaseType] = useState('')
  const [column, setColumn] = useState('')            // who is claiming, where the type has several columns
  const [typeInfo, setTypeInfo] = useState<CaseTypeInfo[]>([])
  const [typeError, setTypeError] = useState<string | null>(null)
  const [pay, setPay] = useState<Record<string, string>>({})
  const [commutation, setCommutation] = useState('')
  const [gpfKind, setGpfKind] = useState('final')
  const [gazetted, setGazetted] = useState('unknown')
  const gpf = product === 'GPF'
  const [more, setMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Files left out of the last pick, and why (a duplicate, too large, a type the office does not take) (F8).
  const [refused, setRefused] = useState<string[]>([])
  const [progress, setProgress] = useState<{ sent: number; total: number } | null>(null)
  // One key per attempt at filing (F8): a retry after a dropped connection carries the same key,
  // so the server files the case once; a change to the papers starts a new attempt.
  const attemptKey = useRef<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loadTry, setLoadTry] = useState(0)
  const pickDept = !!can?.pick_department

  useEffect(() => {
    // A failed load used to leave "Loading the document list…" and an empty department list
    // for good (F12); now it says so and offers Retry.
    setLoadError(null)
    const jobs: Promise<unknown>[] = []
    if (!gpf) jobs.push(fetchCaseTypes().then(setTypeInfo))
    if (pickDept) jobs.push(departments().then(setDepts))
    Promise.all(jobs).catch(e => setLoadError(e instanceof Error ? e.message : String(e)))
  }, [pickDept, gpf, loadTry])

  // Leaving the page mid-upload would abandon it; the browser asks first (F8).
  useEffect(() => {
    if (!busy) return
    const guard = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [busy])

  const typeDef = CASE_TYPE_LIST.find(t => t.id === caseType)
  const info = typeInfo.find(t => t.id === caseType)
  const columns = info?.variants ?? []
  const chosenColumn = columns.find(v => v.id === column)
  const required = chosenColumn ? chosenColumn.documents : (info?.documents ?? [])
  const typeMissing = !gpf && !caseType
  const columnMissing = !gpf && !!caseType && columns.length > 1 && !column

  const add = (list: FileList | null) => {
    if (!list) return
    if (typeMissing) { setTypeError('Select the case type before attaching documents.'); return }
    const { accepted, refused: left } = checkFiles(files, Array.from(list))
    setFiles(accepted); setRefused(left)
    attemptKey.current = null                              // the papers changed: a new attempt
  }
  const remove = (f: File) => { setFiles(files.filter(x => x !== f)); attemptKey.current = null }
  const pickType = (id: string) => { setCaseType(id); setColumn(''); setTypeError(null) }
  const year = new Date().getFullYear()
  const years = [year - 3, year - 2, year - 1]
  let n = 0
  const num = () => ++n

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (typeMissing) { setTypeError('Select the case type before submitting the case.'); return }
    if (columnMissing) { setTypeError('Say who is claiming before submitting the case.'); return }
    setBusy(true); setError(null); setProgress(null)
    attemptKey.current ??= newIdempotencyKey()
    try {
      const r = await createCase(files, {
        product, department_code: pickDept ? department : undefined,
        claimant_name: claimant,
        ...(gpf ? { gpf_kind: gpfKind, gazetted } : {
          case_type: caseType,
          variant: column || undefined,
          annual_pay: Object.fromEntries(Object.entries(pay).filter(([, v]) => v.trim())),
          commutation_percent: commutation || undefined,
        }),
      }, { idempotencyKey: attemptKey.current, onProgress: setProgress })
      attemptKey.current = null
      onCreated(r.case.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally { setBusy(false); setProgress(null) }
  }

  const blocked = busy || files.length === 0 || (pickDept && !department) || typeMissing || columnMissing
  const hint = typeMissing ? 'Select the case type.' : columnMissing ? 'Say who is claiming.' : files.length === 0 ? 'Attach at least one document.' : pickDept && !department ? 'Select the department.'
    : `${files.length} document${files.length === 1 ? '' : 's'} attached${user?.department_name ? ` · ${user.department_name}` : ''}.`

  return (
    <div className="screen container" style={{ paddingTop: 22, maxWidth: 860 }}>
      <button className="back" onClick={onCancel}>Back to the register</button>
      <h1 style={{ marginTop: 8 }}>{PRODUCT_WORDS[product].file}</h1>
      <p className="lead">
        {gpf ? 'Attach every page of the GP Fund claim: the application or sanction, the pay slip, the CNIC, the nomination or death papers as the kind of claim requires. Filing submits the claim to the Office of the Accountant General, where the GP Fund module examines it and the reviewer decides; a missing document is asked for by the reviewer.'
             : 'Choose the case type, then attach every document in the pension file. Filing submits the case to the Office of the Accountant General, where it is verified with AI against the checklist for that type and the reviewer decides; a missing document is asked for by the reviewer.'}
      </p>
      {loadError && (
        <div className="banner bad" role="alert"><span className="mark">!</span>
          <div className="sub">Could not load the form's lists ({loadError}). <button type="button" style={{ marginLeft: 8 }} onClick={() => setLoadTry(n => n + 1)}>Retry</button></div>
        </div>
      )}
      <form onSubmit={submit} className="stack" style={{ gap: 'var(--s4)' }} noValidate>
        {pickDept && (
          <div className="card">
            <h3 className="step-h"><span className="num">{num()}</span>Department</h3>
            <div className="field">
              <label className="label" htmlFor="dept">Department</label>
              <select id="dept" value={department} onChange={e => setDepartment(e.target.value)} required style={{ fontSize: 16 }}>
                <option value="">— choose the department —</option>
                {depts.map(d => <option key={d.code} value={d.code}>{d.name}</option>)}
              </select>
              <div className="hint">Administrator filing on behalf of the department's DDO: the case belongs to this department.</div>
            </div>
          </div>
        )}

        {!gpf && (
          <div className="card">
            <h3 className="step-h"><span className="num">{num()}</span>Case type</h3>
            <div className="field">
              <label className="label" htmlFor="case-type">Case type <span style={{ color: 'var(--red)' }} aria-hidden="true">*</span></label>
              <select id="case-type" value={caseType} onChange={e => pickType(e.target.value)} required aria-required="true"
                      aria-invalid={!!typeError} aria-describedby={typeError ? 'case-type-error' : 'case-type-hint'} style={{ fontSize: 16 }}>
                <option value="">— choose —</option>
                {CASE_TYPE_LIST.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
              </select>
              {typeError
                ? <div id="case-type-error" className="form-error" role="alert">{typeError}</div>
                : <div id="case-type-hint" className="hint">{typeDef ? typeDef.hint : 'Required. The kinds of case on the Office of the Accountant General\'s document sheet; the choice decides which documents are asked for and which rules apply.'}</div>}
            </div>
            {columns.length > 1 && (
              <div className="field">
                <label className="label" htmlFor="column">Who is claiming <span style={{ color: 'var(--red)' }} aria-hidden="true">*</span></label>
                <select id="column" value={column} onChange={e => { setColumn(e.target.value); setTypeError(null) }} required aria-required="true" style={{ fontSize: 16 }}>
                  <option value="">— choose —</option>
                  {columns.map(v => <option key={v.id} value={v.id}>{v.label}</option>)}
                </select>
                <div className="hint">This picks the checklist the Office of the Accountant General will apply. A widow's case and a son's case are checked against different lists.</div>
              </div>
            )}
            {caseType && (
              <div className="banner good" style={{ marginTop: 10, alignItems: 'flex-start' }}>
                <span className="mark" aria-hidden="true">i</span>
                <div className="sub" style={{ color: 'var(--ink)' }}>
                  <strong>Documents required for {typeDef?.label}{chosenColumn ? ` (${chosenColumn.label.toLowerCase()})` : ''}:</strong>
                  {required.length > 0 ? (
                    <ol style={{ margin: '6px 0 0', paddingLeft: 20 }}>
                      {required.map(d => <li key={d.id}>{d.requirement}</li>)}
                    </ol>
                  ) : (
                    <div style={{ marginTop: 4 }}>The office sheet has no column for this type; the sanction on the prescribed form with the pension papers is required.</div>
                  )}
                  {columns.length > 1 && !chosenColumn && <div className="help" style={{ marginTop: 6 }}>These are the documents every claimant needs. Say who is claiming to see the full list for that claimant.</div>}
                  {!info && typeDef && <div className="help" style={{ marginTop: 6 }}>Loading the document list…</div>}
                </div>
              </div>
            )}
          </div>
        )}

        <div className="card" style={typeMissing ? { opacity: .6 } : undefined} aria-disabled={typeMissing || undefined}>
          <h3 className="step-h"><span className="num">{num()}</span>Attach the documents</h3>
          <label className="drop" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); add(e.dataTransfer.files) }}
                 onClick={e => { if (typeMissing) { e.preventDefault(); setTypeError('Select the case type before attaching documents.') } }}>
            <input type="file" multiple style={{ display: 'none' }} disabled={typeMissing} onChange={e => { add(e.target.files); e.target.value = '' }}
                   accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.bmp,.gif,.webp,.doc,.docx,.odt,.rtf,.txt,.xls,.xlsx,.csv,.zip"
                   aria-label="Select the documents" />
            <div style={{ fontWeight: 800, fontSize: 17 }}>{typeMissing ? 'Select the case type first' : 'Select files, or drag them here'}</div>
            <button type="button" className="primary" style={{ marginTop: 10 }} disabled={typeMissing}
                    onClick={e => { (e.currentTarget.closest('label')?.querySelector('input[type=file]') as HTMLInputElement | null)?.click() }}>
              Choose files
            </button>
            <div className="help" style={{ marginTop: 4 }}>Scanned PDFs, images, Word or Excel files, or a zip archive. Files may be added in several batches.</div>
          </label>
          {files.length > 0 && (
            <>
              <div className="label" style={{ margin: '14px 0 6px' }}>{files.length} file{files.length === 1 ? '' : 's'} attached</div>
              <table>
                <tbody>
                  {files.map((f, i) => (
                    <tr key={f.name + f.size}>
                      <td className="mono muted" style={{ width: 36 }}>{i + 1}</td>
                      <td style={{ fontSize: 15 }}>{f.name}</td>
                      <td className="muted num" style={{ width: 90 }}>{kb(f.size)}</td>
                      <td style={{ width: 90 }}><button type="button" className="ghost" aria-label={`Remove ${f.name}`} onClick={() => remove(f)}>Remove</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {refused.length > 0 && (
            <div className="banner warn" role="status" style={{ marginTop: 10 }}>
              <span className="mark" aria-hidden="true">!</span>
              <div className="sub">
                <strong>Not attached:</strong>
                <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{refused.map(r => <li key={r}>{r}</li>)}</ul>
              </div>
            </div>
          )}
        </div>

        <div className="card">
          <h3 className="step-h"><span className="num">{num()}</span>{gpf ? 'Claim' : 'Claimant'}</h3>
          <div className="field">
            <label className="label" htmlFor="claimant">{gpf ? 'Subscriber\'s name' : 'Claimant\'s name'}</label>
            <input id="claimant" value={claimant} onChange={e => setClaimant(e.target.value)} placeholder="Optional; extracted from the documents if left blank" style={{ fontSize: 16 }} />
          </div>
          {gpf && (
            <div className="row" style={{ gap: 12, marginTop: 10, alignItems: 'flex-start' }}>
              <div className="field" style={{ flex: '1 1 260px' }}>
                <label className="label" htmlFor="gpf-kind">Kind of claim</label>
                <select id="gpf-kind" value={gpfKind} onChange={e => setGpfKind(e.target.value)} style={{ fontSize: 16 }}>
                  {GPF_KINDS.map(k => <option key={k.id} value={k.id}>{k.label}</option>)}
                </select>
                <div className="hint">Decides which of the office's checks apply.</div>
              </div>
              <div className="field" style={{ flex: '1 1 200px' }}>
                <label className="label" htmlFor="gazetted">Subscriber</label>
                <select id="gazetted" value={gazetted} onChange={e => setGazetted(e.target.value)} style={{ fontSize: 16 }}>
                  <option value="unknown">Not stated</option>
                  <option value="gazetted">Gazetted</option>
                  <option value="non-gazetted">Non-gazetted</option>
                </select>
              </div>
            </div>
          )}
          {!gpf && can?.intake_choices && (
            <>
              <button type="button" className="ghost" style={{ marginTop: 10 }} onClick={() => setMore(!more)}>
                {more ? 'Hide' : 'Show'} pension particulars (pay, commutation)
              </button>
              {more && (
                <div className="stack" style={{ marginTop: 8 }}>
                  <div className="field">
                    <label className="label">Basic pay on 1 July of the last three years (self pension only)</label>
                    <div className="row" style={{ gap: 8 }}>
                      {years.map(y => (
                        <input key={y} placeholder={`${y}`} aria-label={`Basic pay on 1 July ${y}`} value={pay[y] ?? ''} inputMode="numeric"
                               onChange={e => setPay({ ...pay, [y]: e.target.value })} />
                      ))}
                    </div>
                  </div>
                  <div className="field">
                    <label className="label" htmlFor="comm">Commutation opted (%, up to 25)</label>
                    <input id="comm" value={commutation} onChange={e => setCommutation(e.target.value)} inputMode="numeric" style={{ maxWidth: 140 }} />
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {error && <div className="banner bad" role="alert"><span className="mark">!</span><div className="sub">{error}</div></div>}

        {busy && (
          // How far the papers have got (F8): the bar fills with the bytes sent; on office Wi-Fi a
          // scanned file of 200 MB takes minutes, and a screen that said only "Filing…" read as stuck.
          <div className="card gpf-progress" role="status" aria-live="polite">
            <div style={{ fontWeight: 600 }}>Sending the documents…</div>
            <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100}
                 aria-valuenow={progress && progress.total ? Math.round((progress.sent / progress.total) * 100) : undefined}>
              <span style={{ width: progress && progress.total ? `${Math.round((progress.sent / progress.total) * 100)}%` : '0%' }} />
            </div>
            <div className="muted" style={{ fontSize: 'var(--t-small)' }}>
              {progress ? progressWords(progress.sent, progress.total) : 'Starting…'}{progress && progress.sent >= progress.total ? ' · the server is filing the case' : ''}
            </div>
            <div className="help">Keep this page open until the case is filed.</div>
          </div>
        )}

        <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <span className="num" style={{ width: 28, height: 28, borderRadius: '50%', background: 'var(--green)', color: '#fff', display: 'grid', placeItems: 'center', fontWeight: 800 }}>{num()}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 800, fontSize: 16 }}>File the {gpf ? 'claim' : 'case'} and submit it to the Office of the Accountant General</div>
            <div className="help">{hint}</div>
          </div>
          <button className="primary big" type="submit" disabled={blocked}
                  onClick={e => { if (typeMissing) { e.preventDefault(); setTypeError('Select the case type before submitting the case.') } }}>
            {busy ? 'Filing…' : 'File case and submit'}
          </button>
        </div>
      </form>
    </div>
  )
}
