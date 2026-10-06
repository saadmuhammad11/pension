/** Screen 1 — Case Intake. BUILD §9.4. */
import { useEffect, useRef, useState } from 'react'
import { fetchVariants, startRun, type Role, type VariantFamily } from '../api'

/** §9.4: constrained inputs per the SOP's no-free-text requirement. */
export function Intake(
  { onStarted, role }: { onStarted: (runId: string) => void; role: Role },
) {
  // The checklist column the officer selects. Every case needs one: it decides which
  // documents are required, and it cannot be read off the scanned pages.
  const [families, setFamilies] = useState<VariantFamily[]>([])
  const [variant, setVariant] = useState('')
  useEffect(() => { fetchVariants().then(setFamilies).catch(() => setFamilies([])) }, [])
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  // Three years of basic pay. Required for any case whose entitlement arose after
  // 2 December 2024; harmless on an older case, which uses the last-drawn base.
  const thisYear = new Date().getFullYear()
  const payYears = [thisYear - 3, thisYear - 2, thisYear - 1]
  const [pay, setPay] = useState<Record<string, string>>({})
  // Commutation is the pensioner's option, recorded on the commutation option form in the
  // bundle. Blank means no election, not a nil election.
  const [commutation, setCommutation] = useState('')
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Uploads the PDF and starts a real pipeline run. Nothing is simulated: the run id
  // that comes back addresses work happening on this machine's GPU.
  async function start() {
    if (!file) return
    setBusy(true); setError(null)
    const supplied = Object.fromEntries(
      Object.entries(pay).filter(([, v]) => v.trim() !== ''),
    )
    try {
      onStarted((await startRun(file, variant || undefined, supplied, commutation, role)).run_id)
    }
    catch (e) { setError(String(e)); setBusy(false) }
  }

  return (
    <div className="screen container" style={{ paddingTop: 22 }}>
      <h1>New Pension Case — Intake</h1>
      <p className="lead">
        Upload the scanned case file received from the Administrative Department (Dashboard /
        SAP). The AI will read every page, verify the checklist, and prepare the case for your
        review.
      </p>

      <div className="card">
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          style={{ display: 'none' }}
          onChange={e => setFile(e.target.files?.[0] ?? null)}
        />
        <div
          onClick={() => inputRef.current?.click()}
          onDragOver={e => e.preventDefault()}
          onDrop={e => {
            e.preventDefault()
            const f = e.dataTransfer.files?.[0]
            if (f && f.type === 'application/pdf') setFile(f)
          }}
          onDragEnter={() => setOver(true)}
          onDragLeave={() => setOver(false)}
          style={{
            border: `2.5px dashed ${over ? 'var(--green3)' : 'var(--line)'}`,
            borderRadius: 14, padding: '26px 22px', textAlign: 'center', cursor: 'pointer',
            background: over || file ? 'var(--sage)' : 'transparent',
            transition: 'background .15s ease, border-color .15s ease',
          }}
        >
          <svg width="34" height="34" viewBox="0 0 24 24" fill="none" aria-hidden="true"
               style={{ margin: '0 auto 6px', display: 'block' }}>
            <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" stroke="var(--green2)" strokeWidth="1.7"
                  strokeLinecap="round" strokeLinejoin="round" />
            <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" stroke="var(--green3)"
                  strokeWidth="1.7" strokeLinecap="round" />
          </svg>
          <div style={{ fontWeight: 600, fontSize: 'var(--t-lead)' }}>
            Drop the scanned case file here, or click to browse
          </div>
          <div className="muted" style={{ fontSize: 'var(--t-small)', marginTop: 4 }}>
            PDF · up to 46+ pages · CamScanner-grade scans accepted ·{' '}
            <span className="urdu" style={{ display: 'inline-block' }}>فائل یہاں اپ لوڈ کریں</span>
          </div>
        </div>

        {file && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 12, marginTop: 14,
            background: 'var(--sage)', border: '1px solid var(--sage2)',
            borderRadius: 10, padding: 12,
          }}>
            <div style={{
              background: 'var(--green)', color: '#fff', borderRadius: 8,
              padding: '8px 10px', fontWeight: 700, fontSize: 12,
            }}>PDF</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600 }}>{file.name}</div>
              <div className="muted mono" style={{ fontSize: 11 }}>
                {(file.size / 1048576).toFixed(1)} MB · hashed on upload
              </div>
            </div>
            <span className="pill low">received</span>
          </div>
        )}

        <div style={{ marginTop: 'var(--s5)', maxWidth: 520 }}>
          <label className="field">
            <span className="label">Kind of case</span>
            <select value={variant} onChange={e => setVariant(e.target.value)}>
              <option value="">Detect from the prescribed form (recommended)</option>
              {families.map(f => (
                <optgroup key={f.id} label={`${f.label} — override`}>
                  {f.variants.map(v => (
                    <option key={v.id} value={v.id}>
                      {v.label} — {v.documents} documents
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            <span className="hint">
              The sanction form decides this — B-I a fresh self pension, B-IV an invalid one,
              D-I a death in service, D-II a death after retirement, narrowed by the claimant
              the form names. Override only if the detected column is wrong.
            </span>
          </label>
        </div>

        <div style={{ marginTop: 'var(--s5)' }}>
          <div className="label" style={{ fontSize: 'var(--t-small)', fontWeight: 700,
                                          color: 'var(--muted)', marginBottom: 6 }}>
            Basic pay including personal pay, as at 1 July
          </div>
          <div className="row" style={{ gap: 'var(--s3)' }}>
            {payYears.map(y => (
              <label key={y} className="field" style={{ width: 150 }}>
                <span className="label" style={{ fontWeight: 600 }}>1 July {y}</span>
                <input
                  inputMode="numeric"
                  value={pay[String(y)] ?? ''}
                  onChange={e => setPay({ ...pay, [String(y)]: e.target.value })}
                  placeholder="Rs."
                />
              </label>
            ))}
          </div>
          <div className="hint" style={{ marginTop: 6, maxWidth: '70ch' }}>
            Read from the service book or the pay slips. Required for a retirement or death
            on or after 2 December 2024, when the amended rule 4.4(4) made the pension base
            a three-year average rather than the last pay drawn. Leave blank for an earlier
            case, and for a family pension, which the engine computes from the bundle.
          </div>
        </div>

        <div style={{ marginTop: 'var(--s5)', maxWidth: 520 }}>
          <label className="field">
            <span className="label">Commutation elected by the pensioner</span>
            <select value={commutation} onChange={e => setCommutation(e.target.value)}>
              <option value="">No commutation option on the file</option>
              <option value="25">25% — the maximum permitted</option>
              <option value="20">20%</option>
              <option value="15">15%</option>
              <option value="10">10%</option>
              <option value="5">5%</option>
            </select>
            <span className="hint">
              Read from the commutation option form. Up to 25% of gross pension may be
              commuted into a lump sum (rule 8.1 as amended on 2 December 2024); the rest
              stays payable monthly. Leave as-is where the pensioner has not elected — that
              is not the same as electing nothing, and the engine shows the ceiling either way.
            </span>
          </label>
        </div>

        <div style={{ display: 'flex', gap: 10, marginTop: 18 }}>
          <button className="primary" disabled={!file || busy} onClick={start}>
            {busy ? 'Starting…' : '▶ Start AI Analysis'}
          </button>
        </div>
      </div>

      {error && (
        <div className="card" style={{ borderColor: 'var(--red)', background: 'var(--redbg)', color: 'var(--red)' }}>
          {error}
        </div>
      )}

      <p className="muted" style={{ fontSize: 12 }}>
        Case files are processed on the Accountant General's own servers. No document leaves
        the office.
      </p>
    </div>
  )
}

