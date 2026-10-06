/** Screen 3 — Review Findings. BUILD §9.6. Six tabs, gold underline on active. */
import { useEffect, useState, type CSSProperties } from 'react'
import { Figure } from '../components/Figure'
import { ChecklistPanel } from '../components/ChecklistPanel'
import { PagePreview } from '../components/PagePreview'
import { fetchDispositions, postDisposition, signatureImageUrl, specimenImageUrl,
         type CalculationGate, type Disposition, type Role } from '../api'
import {
  caseNumber, caseTypeLabel, documentLabel, findingLabel, verdictLabel,
} from '../labels'
import type { Ambiguity, CaseReport, Flag, Severity, SpecimenSideBySide } from '../types'

const rs = (n: number) => `Rs. ${n.toLocaleString('en-PK')}`

/** Who the disposition is recorded against. Mirrors the header's signed-in officer; until
 *  there is authentication this is a claim, exactly as `officer` is on a case decision. */
const OFFICER_FOR: Record<string, string> = {
  ACCOUNTS_OFFICE: 'Syed Haider', ADMIN_DEPARTMENT: 'Dept. User',
}
const TABS = ['Summary', 'Extracted Data', 'Checklist', 'Flags', 'Calculation', 'Identity'] as const

const TONE: Record<Severity, { bg: string; fg: string; cls: string }> = {
  HIGH: { bg: 'var(--redbg)', fg: 'var(--red)', cls: 'high' },
  MEDIUM: { bg: 'var(--amberbg)', fg: 'var(--amber)', cls: 'medium' },
  LOW: { bg: 'var(--okbg)', fg: 'var(--ok)', cls: 'low' },
}

function Verdict({ report }: { report: CaseReport }) {
  // No recommendation means the engine could not type the case, which is a routing outcome
  // and not an absence of information. Rendering nothing here is what blanked the screen.
  if (!report.recommendation) {
    return (
      <div className="banner warn" style={{ marginTop: 'var(--s5)' }} role="status">
        <span className="mark" aria-hidden="true">?</span>
        <div>
          <div className="title">Needs an officer to classify this case</div>
          <div style={{ marginTop: 2 }}>
            {report.checklist_gap ?? 'The kind of case could not be determined from the bundle.'}
          </div>
          <div className="muted" style={{ fontSize: 'var(--t-small)', marginTop: 'var(--s2)' }}>
            The documents found are listed below. Choose the kind of case at intake to run the
            checklist against it.
          </div>
        </div>
      </div>
    )
  }
  const v = report.recommendation.verdict
  const kind = v === 'RETURN_FOR_CORRECTION' ? 'warn' : v === 'HOLD' ? 'bad' : 'good'
  const blocking = report.recommendation.blocking_flags
  return (
    <div className={`banner ${kind}`} style={{ marginTop: 'var(--s5)' }} role="status">
      <span className="mark" aria-hidden="true">{v === 'FORWARD' ? '✓' : '!'}</span>
      <div style={{ flex: 1 }}>
        <div className="row" style={{ gap: 'var(--s2)' }}>
          <span className="title">{verdictLabel(v)}</span>
          {blocking.length > 0 && (
            <span className="pill high">blocking {blocking.join(', ')}</span>
          )}
        </div>
        <div style={{ marginTop: 2 }}>{report.recommendation.rationale}</div>
        {/* §9.6 requires this sentence on the verdict banner. It is the line that keeps the
            screen a recommendation rather than a decision, so it is not styled away. */}
        <div className="muted" style={{ fontSize: 'var(--t-small)', marginTop: 'var(--s2)' }}>
          AI recommendation only — the decision rests with the Auditor / AG.
        </div>
      </div>
    </div>
  )
}

/** BLOCKING-06 and BLOCKING-03: both readings side by side, difference stated, never one
 *  figure. §9.6 tab 5 makes this a rendering requirement, not a nicety. */
function AmbiguityCard({ a }: { a: Ambiguity }) {
  return (
    <div style={{
      border: '1px solid var(--amber)', background: 'var(--amberbg)',
      borderRadius: 12, padding: 14, marginTop: 12,
    }}>
      <div style={{ fontWeight: 700, color: 'var(--amber)' }}>
        {a.rule_id} · {a.blocking_id} — unresolved
      </div>
      <div style={{ marginTop: 4 }}>{a.question}</div>
      <div style={{ display: 'flex', gap: 12, marginTop: 12, flexWrap: 'wrap' }}>
        {a.readings.map(r => (
          <div key={r.label} style={{
            flex: '1 1 240px', background: '#fff', border: '1px solid var(--line)',
            borderRadius: 10, padding: 12,
          }}>
            <div className="muted" style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase' }}>
              {r.label.replace(/_/g, ' ')}
            </div>
            <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--ink)' }}>{rs(r.amount)}</div>
            <div className="mono muted" style={{ fontSize: 11, marginTop: 4 }}>{r.computation_shown}</div>
            <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>{r.basis}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10, fontWeight: 700 }}>{a.difference}</div>
      <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Resolve with: {a.resolve_with}</div>
    </div>
  )
}

function FlagCard(
  { f, index = 0, runId, onPage, disposition, onDispose, mayDecide }:
  { f: Flag; index?: number; runId: string
    onPage: (page: number, doc: string) => void
    disposition?: Disposition
    onDispose: (flagId: string, action: Disposition['action'], ground: string) => Promise<void>
    mayDecide: boolean },
) {
  const tone = TONE[f.severity]
  return (
    // §9.6 asks for card tinting by severity. With nine flags on a case a full tint becomes
    // noise, so the tint stays soft and a 4px stripe carries the severity instead -- the eye
    // finds the HIGH ones down the left edge without reading a word.
    // The stripe is drawn rather than painted -- it runs down the edge as the card arrives,
    // which is what makes a column of nine findings read as a list being laid out instead of
    // a block appearing. `color` feeds the stripe through currentColor.
    <div className="finding" style={{
      border: `1px solid var(--line)`, background: tone.bg, color: tone.fg,
      borderRadius: 12, padding: 'var(--s4) var(--s5)', marginBottom: 'var(--s3)',
      paddingLeft: 'calc(var(--s5) + 3px)', '--i': index,
    } as CSSProperties}>
      <div className="row" style={{ gap: 'var(--s2)' }}>
        <span className={`pill ${tone.cls}`}>{f.severity}</span>
        <span className="muted mono">{f.id}</span>
        <span className="chip">{findingLabel(f.class)}</span>
        {f.blocks_ppo && <span className="pill high">BLOCKS PPO</span>}
        <span style={{ fontWeight: 700, fontSize: 'var(--t-lead)', color: 'var(--ink)' }}>
          {f.title}
        </span>
      </div>
      <div style={{ marginTop: 'var(--s2)', maxWidth: '82ch', color: 'var(--ink)' }}>
        {f.finding}
      </div>
      {(f.evidence.asserted.length > 0 || f.evidence.contradicted_by.length > 0) && (
        // The page a finding cites is the evidence for it, so it opens. A chip that names a
        // page an officer then has to hunt for in a 51-page PDF is a citation nobody checks.
        <div className="row" style={{ marginTop: 8, gap: 'var(--s1)' }}>
          {f.evidence.asserted.map(e => (
            <button key={`a${e.page}`} className="chip" onClick={() => onPage(e.page, e.doc)}
                    style={{ cursor: 'pointer', border: '1px solid var(--sage2)',
                             padding: '2px 8px', fontSize: 'var(--t-micro)' }}>
              ⧉ p.{e.page} {documentLabel(e.doc)}
            </button>
          ))}
          {f.evidence.contradicted_by.length > 0 && (
            <span className="muted" style={{ fontSize: 'var(--t-small)' }}>contradicted by</span>
          )}
          {f.evidence.contradicted_by.map(e => (
            <button key={`c${e.page}`} className="chip" onClick={() => onPage(e.page, e.doc)}
                    style={{ cursor: 'pointer', border: '1px solid var(--sage2)',
                             padding: '2px 8px', fontSize: 'var(--t-micro)' }}>
              ⧉ p.{e.page} {documentLabel(e.doc)}
            </button>
          ))}
        </div>
      )}
      {f.specimen && <SpecimenPanel s={f.specimen} runId={runId}
                                    onPage={p => onPage(p, f.evidence.asserted[0]?.doc ?? '')} />}
      <div style={{
        marginTop: 'var(--s3)', paddingTop: 'var(--s3)', borderTop: '1px solid rgba(31,41,55,.08)',
        color: 'var(--ok)', fontWeight: 600, maxWidth: '82ch',
      }}>→ Action: {f.required_action}</div>

      <FlagDisposition f={f} disposition={disposition} onDispose={onDispose} mayDecide={mayDecide} />
    </div>
  )
}

/** The sanction signature beside the department's specimen, for the officer's eye.
 *
 *  The comparison itself is the officer's: the vision model was tested for it and could not
 *  tell one officer's hand from another's (pipeline/signatory.py). What the portal can do is
 *  put the two next to each other, which is the step that used to mean finding the specimen
 *  letter in a file.
 */
function SpecimenPanel(
  { s, runId, onPage }: { s: SpecimenSideBySide; runId: string; onPage: (page: number) => void },
) {
  const box: CSSProperties = {
    flex: '1 1 280px', minWidth: 0, background: '#fff', border: '1px solid var(--line)',
    borderRadius: 10, padding: 'var(--s3)',
  }
  const img: CSSProperties = { display: 'block', width: '100%', height: 'auto', marginTop: 6 }
  return (
    <div className="row" style={{ marginTop: 'var(--s3)', gap: 'var(--s3)', alignItems: 'stretch',
                                  flexWrap: 'wrap', color: 'var(--ink)' }}>
      <div style={box}>
        <div style={{ fontWeight: 700 }}>On the sanction form{s.page ? ` (p.${s.page})` : ''}</div>
        {s.signature_image
          ? <img src={signatureImageUrl(runId, s.signature_image)} alt="Signature cut from the form" style={img} />
          : <div className="muted" style={{ fontSize: 'var(--t-small)', marginTop: 6 }}>
              The signature could not be cut out of the page; open the page to see it.</div>}
        {s.page && <button className="chip" style={{ marginTop: 8, cursor: 'pointer' }}
                           onClick={() => onPage(s.page as number)}>⧉ open p.{s.page}</button>}
      </div>
      <div style={box}>
        <div style={{ fontWeight: 700 }}>Specimen on file: {s.officer}</div>
        <div className="muted" style={{ fontSize: 'var(--t-small)' }}>
          {s.post}, {s.department} · {s.cite}</div>
        {s.images.map(name => (
          <img key={name} src={specimenImageUrl(s.id, name)} alt={`Specimen ${name}`} style={img} />
        ))}
      </div>
    </div>
  )
}

/** What the officer has decided about this one finding, and the controls to decide it.
 *
 *  The pension is gated on every finding being cleared, so this is where a case moves. Only
 *  a WAIVE clears: upholding is the officer agreeing the finding is right, and agreeing a
 *  case is defective is not a reason to compute its pension.
 */
function FlagDisposition(
  { f, disposition, onDispose, mayDecide }:
  { f: Flag; disposition?: Disposition
    onDispose: (flagId: string, action: Disposition['action'], ground: string) => Promise<void>
    mayDecide: boolean },
) {
  const [open, setOpen] = useState(false)
  const [action, setAction] = useState<Disposition['action'] | null>(null)
  const [ground, setGround] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const TONE_FOR: Record<string, string> = { WAIVE: 'low', UPHOLD: 'high', HOLD: 'medium' }
  const WORD: Record<string, string> = {
    WAIVE: 'Approved — does not prevent payment',
    UPHOLD: 'Rejected — the case cannot proceed',
    HOLD: 'On hold — exceptional-case lane',
  }

  if (disposition && !open) {
    return (
      <div style={{ marginTop: 'var(--s3)', paddingTop: 'var(--s3)',
                    borderTop: '1px dashed rgba(31,41,55,.12)' }}>
        <div className="row" style={{ gap: 'var(--s2)' }}>
          <span className={`pill ${TONE_FOR[disposition.action]}`}>{WORD[disposition.action]}</span>
          <span className="muted" style={{ fontSize: 'var(--t-small)' }}>
            {disposition.officer} · {disposition.at.replace('T', ' ')}
          </span>
          {mayDecide && (
            <button className="ghost" style={{ padding: 0, fontSize: 'var(--t-small)' }}
                    onClick={() => setOpen(true)}>Change</button>
          )}
        </div>
        {disposition.ground && (
          <div className="muted" style={{ fontSize: 'var(--t-small)', marginTop: 4,
                                          maxWidth: '82ch', color: 'var(--ink)' }}>
            “{disposition.ground}”
          </div>
        )}
      </div>
    )
  }

  if (!mayDecide) {
    return (
      <div className="muted" style={{ marginTop: 'var(--s3)', paddingTop: 'var(--s3)',
                                      borderTop: '1px dashed rgba(31,41,55,.12)',
                                      fontSize: 'var(--t-small)' }}>
        Findings are disposed of by the Accounts Office (SOP §4.2).
      </div>
    )
  }

  const needsGround = action === 'WAIVE'
  const blocked = !action || (needsGround && ground.trim().length < 15)

  return (
    <div style={{ marginTop: 'var(--s3)', paddingTop: 'var(--s3)',
                  borderTop: '1px dashed rgba(31,41,55,.12)' }}>
      <div className="row" style={{ gap: 'var(--s2)' }}>
        <button className={action === 'WAIVE' ? 'primary' : ''} onClick={() => setAction('WAIVE')}
                style={{ padding: '7px 14px', fontSize: 'var(--t-small)' }}>
          ✓ Approve — clears this finding
        </button>
        <button className={action === 'UPHOLD' ? 'primary' : ''} onClick={() => setAction('UPHOLD')}
                style={{ padding: '7px 14px', fontSize: 'var(--t-small)' }}>
          ✗ Reject — return to the department
        </button>
      </div>
      {needsGround && (
        <div style={{ marginTop: 'var(--s3)' }}>
          <div className="label" style={{ marginBottom: 4 }}>
            Ground for setting this finding aside (required, at least 15 characters)
          </div>
          <textarea rows={2} value={ground} onChange={e => setGround(e.target.value)}
                    placeholder="Recorded against your name in the audit trail…" />
        </div>
      )}
      {action && (
        <div className="row" style={{ marginTop: 'var(--s3)', gap: 'var(--s2)' }}>
          <button className="gold" disabled={blocked || busy}
                  onClick={async () => {
                    setBusy(true); setError(null)
                    try { await onDispose(f.id, action, ground); setOpen(false); setAction(null) }
                    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
                    finally { setBusy(false) }
                  }}>
            {busy ? 'Recording…' : 'Record'}
          </button>
          <button onClick={() => { setAction(null); setGround(''); setError(null) }}>Cancel</button>
        </div>
      )}
      {error && (
        <div style={{ marginTop: 'var(--s2)', color: 'var(--red)', fontSize: 'var(--t-small)',
                      maxWidth: '82ch' }}>{error}</div>
      )}
    </div>
  )
}

export function Review(
  { report: given, runId, role, onProceed }:
  { report: CaseReport; runId: string; role: Role; onProceed: () => void },
) {
  // The report as the officer has since settled its checklist; replaced by each checklist
  // action's answer, and by a new report from the parent.
  const [live, setLive] = useState(given)
  useEffect(() => setLive(given), [given])
  const report = live
  const [tab, setTab] = useState<typeof TABS[number]>('Summary')
  const [preview, setPreview] = useState<{ page: number; doc: string } | null>(null)
  const [disposed, setDisposed] = useState<Record<string, Disposition>>({})
  const [gate, setGate] = useState<CalculationGate | null>(null)
  const mayDecide = role === 'ACCOUNTS_OFFICE'

  useEffect(() => {
    let live = true
    fetchDispositions(runId)
      .then(d => { if (live) { setDisposed(d.current); setGate(d.gate) } })
      .catch(() => { /* a case with no findings has nothing to fetch */ })
    return () => { live = false }
  }, [runId])

  async function dispose(flagId: string, action: Disposition['action'], ground: string) {
    const r = await postDisposition(runId, { flag_id: flagId, action, ground, role,
                                             officer: OFFICER_FOR[role] })
    setDisposed(r.current); setGate(r.gate)
  }
  const det = report.determination
  const emol = report.emoluments

  return (
    <div className="screen container" style={{ paddingTop: 22 }}>
      <h1>Case {caseNumber(report.diary_no, report.case_ref)} — Findings</h1>
      <p className="lead">
        {caseTypeLabel(report.case_type.case_type)}
        {report.case_type.prescribed_form && ` · Form ${report.case_type.prescribed_form}`}
        {report.claimant_name && ` · claimant ${report.claimant_name}`}
        {report.forwarding_department && ` · ${report.forwarding_department}`}
      </p>

      <Verdict report={report} />

      <div className="tabs" role="tablist" style={{ marginTop: 'var(--s5)' }}>
        {TABS.map(t => {
          const count = t === 'Flags' ? report.flags.length
            : t === 'Checklist' ? report.checklist?.required ?? null : null
          // A blocking flag has to read from the tab strip, before the tab is opened.
          const alert = t === 'Flags' && report.flags.some(f => f.blocks_ppo)
          return (
            <button key={t} className="tab" role="tab" aria-selected={t === tab}
                    onClick={() => setTab(t)}>
              {t}
              {count !== null && (
                <span className={`count${alert ? ' alert' : ''}`}>{count}</span>
              )}
            </button>
          )
        })}
      </div>

      {tab === 'Summary' && (
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <div className="card" style={{ flex: '1 1 320px' }}>
            <h3 style={{ marginTop: 0 }}>Case</h3>
            <table><tbody>
              <Row k="Case type" v={report.case_type.case_type ?? '— routed to human'} />
              <Row k="Evidence" v={report.case_type.case_type_evidence} />
              <Row k="Confidence" v={String(report.case_type.case_type_confidence)} />
              <Row k="Documents identified" v={`${report.documents.length}`} />
              <Row k="Pages read" v={`${report.pages.length}`} />
            </tbody></table>
          </div>
          <div className="card" style={{ flex: '1 1 320px' }}>
            <h3 style={{ marginTop: 0 }}>Source</h3>
            <table><tbody>
              <Row k="File" v={report.source.file} />
              <Row k="Pages" v={`${report.source.source_pages}`} />
              <Row k="sha256" v={report.source.sha256.slice(0, 24) + '…'} mono />
              {Object.entries(report.provenance).map(([k, v]) => (
                <Row key={k} k={k.replace(/_/g, ' ')} v={String(v ?? '—')} />
              ))}
            </tbody></table>
          </div>
        </div>
      )}

      {tab === 'Extracted Data' && (() => {
        // This tab showed only stage 7's emoluments, which exist on a death-in-service case
        // and nowhere else -- so on six cases in seven it read "field extraction has not been
        // run" while every cross-document fact the pipeline had collected sat unshown. These
        // are the facts the findings are computed FROM, and each carries the page it was read
        // on, so an officer can open it.
        const x = report.extracted
        const rows = [
          ...(x?.assertions ?? []).map(a => ({
            what: a.field.replace(/_/g, ' '), value: a.value,
            who: [a.person, a.role].filter(Boolean).join(' · '),
            page: a.page, doc: a.document,
          })),
          ...(x?.document_dates ?? []).map(d => ({
            what: 'document date', value: d.value, who: '', page: d.page, doc: d.document,
          })),
          ...(x?.issuing_offices ?? []).map(o => ({
            what: 'issuing office', value: o.value, who: '', page: o.page, doc: o.document,
          })),
        ]
        const family = [
          ...(x?.annex_a_family ?? []).map(m => ({ ...m, src: 'Annex-A' })),
          ...(x?.frc_family ?? []).map(m => ({ ...m, src: 'NADRA FRC' })),
        ]
        return (
        <>
        {rows.length > 0 && (
          <div className="card">
            <div className="card-head">
              <h3>Facts read from the documents</h3>
              <span className="muted" style={{ fontSize: 'var(--t-small)' }}>
                {rows.length} values · each read twice and required to agree
              </span>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Field</th><th>Value</th><th>Person</th><th>Read from</th></tr></thead>
                <tbody className="stagger">
                  {rows.map((r, i) => (
                    <tr key={`${r.what}${r.value}${r.page}${i}`} style={{ '--i': i } as CSSProperties}>
                      <td style={{ textTransform: 'capitalize' }}>{r.what}</td>
                      <td className="mono">{r.value}</td>
                      <td className="muted">{r.who || '—'}</td>
                      <td>
                        <button className="chip" onClick={() => setPreview({ page: r.page, doc: r.doc })}
                                style={{ cursor: 'pointer', border: '1px solid var(--sage2)',
                                         padding: '2px 8px', fontSize: 'var(--t-micro)' }}>
                          ⧉ p.{r.page} {documentLabel(r.doc)}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {family.length > 0 && (
          <div className="card">
            <div className="card-head">
              <h3>Family, as each document records it</h3>
              <span className="muted" style={{ fontSize: 'var(--t-small)' }}>
                Held separately per source, so the two can disagree
              </span>
            </div>
            {x?.frc_applicant && (
              <p className="muted" style={{ fontSize: 'var(--t-small)', marginTop: 0 }}>
                The FRC was issued to <b>{x.frc_applicant.name}</b>, relation with head of
                family <b>{x.frc_applicant.relation_with_hof || '—'}</b>. Every relation on
                that certificate is stated toward this person.
              </p>
            )}
            <div className="table-wrap">
              <table>
                <thead><tr><th>Name</th><th>Relation</th><th>Marital status</th><th>Source</th></tr></thead>
                <tbody className="stagger">
                  {family.map((m, i) => (
                    <tr key={`${m.src}${m.name}${i}`} style={{ '--i': i } as CSSProperties}>
                      <td>{m.name}</td><td>{m.relation || '—'}</td>
                      <td className="muted">{m.marital_status || '—'}</td>
                      <td>
                        <button className="chip" onClick={() => setPreview({
                                  page: m.page, doc: m.src === 'Annex-A' ? 'ANNEX_A' : 'NADRA_FRC' })}
                                style={{ cursor: 'pointer', border: '1px solid var(--sage2)',
                                         padding: '2px 8px', fontSize: 'var(--t-micro)' }}>
                          ⧉ p.{m.page} {m.src}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {(x?.unreadable?.length ?? 0) > 0 && (
          <div className="card" style={{ borderLeft: '4px solid var(--amber)' }}>
            <h3 style={{ marginTop: 0 }}>Pages that could not be read</h3>
            <p className="hint">
              Their absence from the findings above is not evidence that they are clean.
            </p>
            {x!.unreadable.map(u => (
              <div key={u.page} className="row" style={{ gap: 'var(--s2)', marginBottom: 6 }}>
                <button className="chip" onClick={() => setPreview({ page: u.page, doc: u.document })}
                        style={{ cursor: 'pointer', border: '1px solid var(--sage2)',
                                 padding: '2px 8px', fontSize: 'var(--t-micro)' }}>
                  ⧉ p.{u.page} {documentLabel(u.document)}
                </button>
                <span className="muted" style={{ fontSize: 'var(--t-small)', maxWidth: '72ch' }}>
                  {u.reason}
                </span>
              </div>
            ))}
          </div>
        )}

        {rows.length === 0 && family.length === 0 && (
          <div className="empty">
            No fields have been extracted for this case yet. Stage 6 reads the identifier
            documents; it has not run, or produced nothing readable.
          </div>
        )}

        <div className="card">
          <h3 style={{ marginTop: 0 }}>Emoluments</h3>
          {!emol ? (
            <p className="muted">
              Computed only where the pension is built from a pay table — a death in service.
              This case takes its base from a figure the prescribed form states.
            </p>
          ) : (
            <>
              <table>
                <thead><tr><th>Component</th><th>Rs./month</th><th>Reckonable</th><th>Source</th></tr></thead>
                <tbody>
                  {emol.components.map(c => (
                    <tr key={c.printed_label}>
                      <td>{c.printed_label}</td>
                      <td>{c.amount.toLocaleString('en-PK')}</td>
                      <td>{c.reckonable ? '✅' : '❌'}</td>
                      <td>{c.page && <span className="chip">p.{c.page}</span>}</td>
                    </tr>
                  ))}
                  <tr className="total">
                    <td>Reckonable total</td>
                    <td>{emol.reckonable_total.toLocaleString('en-PK')}</td>
                    <td colSpan={2}>
                      {emol.reconciled
                        ? `✓ reconciles with the form's printed total (${emol.printed_total?.toLocaleString('en-PK')})`
                        : '⚠ does not reconcile with the form'}
                    </td>
                  </tr>
                  <tr>
                    <td className="muted">Excluded (non-reckonable)</td>
                    <td className="muted">{emol.excluded_total.toLocaleString('en-PK')}</td>
                    <td className="muted" colSpan={2}>not pensionable, however large</td>
                  </tr>
                </tbody>
              </table>
            </>
          )}
        </div>
        </>
        )
      })()}

      {tab === 'Checklist' && (
        <ChecklistPanel report={report} runId={runId} role={role} officer={OFFICER_FOR[role]}
                        mayDecide={mayDecide} onPage={(page, doc) => setPreview({ page, doc })}
                        onChange={(r, g) => { setLive(r); setGate(g) }} />
      )}

      {tab === 'Flags' && (
        <div className="stagger">{report.flags.length === 0
          ? <div className="empty">No cross-document inconsistencies found.</div>
          : report.flags.map((f, i) => (
              <FlagCard key={f.id} f={f} index={i} runId={runId}
                        onPage={(page, doc) => setPreview({ page, doc })}
                        disposition={disposed[f.id]} onDispose={dispose}
                        mayDecide={mayDecide} />
            ))}</div>
      )}

      {tab === 'Calculation' && gate && !gate.open && (
        // The office's rule: no pension while a finding is open. A determination shown
        // beside an unresolved contradiction is a figure somebody may act on, and the
        // contradiction is the reason it might be wrong.
        <div className="card" style={{ borderLeft: '4px solid var(--amber)',
                                       background: 'var(--amberbg)' }}>
          <h3 style={{ marginTop: 0 }}>The pension is not calculated yet</h3>
          <p style={{ maxWidth: '82ch', marginBottom: 'var(--s4)' }}>
            Every finding must be cleared and the checklist complete before a determination
            is produced. {gate.reason}.
          </p>
          <div className="row" style={{ gap: 'var(--s3)' }}>
            <span className="pill low">{gate.flags_cleared} of {gate.flags_total} findings cleared</span>
            {gate.checklist_missing > 0 && (
              <span className="pill high">{gate.checklist_missing} checklist item(s) missing</span>
            )}
            <button className="gold" onClick={() => setTab('Flags')}>Go to the findings →</button>
          </div>
          {gate.open_flags.length > 0 && (
            <div className="table-wrap" style={{ marginTop: 'var(--s4)' }}>
              <table>
                <thead><tr><th>Finding</th><th>Severity</th><th>Status</th></tr></thead>
                <tbody>
                  {gate.open_flags.map(f => (
                    <tr key={f.id}>
                      <td><span className="mono">{f.id}</span> {f.title}</td>
                      <td><span className={`pill ${f.severity === 'HIGH' ? 'high' : 'medium'}`}>
                        {f.severity}</span></td>
                      <td>{f.disposition
                        ? <span className="pill neutral">{f.disposition.toLowerCase()}</span>
                        : <span className="muted">not yet disposed of</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 'Calculation' && (!gate || gate.open) && (
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <div style={{ flex: '1 1 460px' }}>
            <div style={{ background: 'var(--green)', color: '#fff', borderRadius: 14, padding: 20 }}>
              <h3 style={{ margin: '0 0 12px' }}>Determination</h3>
              {!det ? (
                report.self_pension_error ? (
                  <div style={{
                    background: 'rgba(255,255,255,.10)', border: '1px solid var(--gold2)',
                    borderRadius: 10, padding: '12px 14px',
                  }}>
                    <div style={{ fontWeight: 700, color: 'var(--gold2)', marginBottom: 5 }}>
                      Refused — the pension cannot be computed on these papers
                    </div>
                    <div style={{ lineHeight: 1.55 }}>{report.self_pension_error}</div>
                  </div>
                ) : (
                  <p style={{ opacity: .8 }}>
                    Not computed. Supply the three annual pay figures at intake for a
                    retirement on or after 2 December 2024.
                  </p>
                )
              ) : det.steps.map(s => (
                <div key={s.rule_id} style={{
                  display: 'flex', justifyContent: 'space-between', gap: 16,
                  padding: '9px 0', borderBottom: '1px solid rgba(255,255,255,.13)',
                }}>
                  <div>
                    <div style={{ fontWeight: 600 }}>{s.description}</div>
                    <div className="mono" style={{ fontSize: 11, color: '#9DCFB2' }}>
                      {s.rule_id} · {s.computation_shown}
                    </div>
                  </div>
                  <div style={{ fontWeight: 700, whiteSpace: 'nowrap' }}>
                    {s.amount !== null ? rs(s.amount) : '—'}
                  </div>
                </div>
              ))}
              {det && (() => {
                // What the case actually pays, pulled out of the working. The steps above
                // are the audit; these two lines are the answer, and an officer reading a
                // column of rule ids should not have to work out which one is the figure.
                const amount = (id: string) =>
                  det.steps.find(s => s.rule_id === id && s.amount !== null)?.amount ?? null
                const monthly = amount('FAM-IS-03') ?? amount('CALC-02')
                  ?? amount('VOL-RED-01') ?? amount('CALC-01')
                const lump = amount('COMM-03')
                const label = amount('FAM-IS-03') ? 'Family pension, monthly'
                  : amount('CALC-02') ? 'Net pension, monthly (after commutation)'
                  : 'Pension, monthly'
                if (monthly === null) return null
                return (
                  <div style={{ marginTop: 14, borderTop: '1px solid rgba(255,255,255,.22)',
                                paddingTop: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between',
                                  alignItems: 'baseline', gap: 12 }}>
                      <span style={{ fontWeight: 700 }}>{label}</span>
                      <span style={{ fontSize: 26, fontWeight: 700, color: 'var(--gold2)' }}>
                        <Figure value={monthly} />
                      </span>
                    </div>
                    {lump !== null && (
                      <div style={{ display: 'flex', justifyContent: 'space-between',
                                    alignItems: 'baseline', gap: 12, marginTop: 6 }}>
                        <span style={{ fontWeight: 700 }}>Commuted value, once</span>
                        <span style={{ fontSize: 20, fontWeight: 700, color: 'var(--gold2)' }}>
                          <Figure value={lump} duration={1100} />
                        </span>
                      </div>
                    )}
                  </div>
                )
              })()}
            </div>
            {det?.ambiguities.map(a => <AmbiguityCard key={a.rule_id} a={a} />)}
          </div>
          <div className="card" style={{ flex: '1 1 300px' }}>
            <h3 style={{ marginTop: 0 }}>Engine notes and caveats</h3>
            {det?.provisional && (
              <div style={{
                background: 'var(--amberbg)', border: '1px solid var(--amber)', borderRadius: 10,
                padding: 10, marginBottom: 10, fontWeight: 700, color: 'var(--amber)',
              }}>
                PROVISIONAL — engages {det.unverified_rules_engaged.join(', ')}
              </div>
            )}
            <ul style={{ paddingLeft: 18, margin: 0 }}>
              {det?.caveats.map((c, i) => <li key={i} style={{ marginBottom: 7 }}>{c}</li>)}
            </ul>
          </div>
        </div>
      )}

      {preview && (
        <PagePreview runId={runId} page={preview.page} document={documentLabel(preview.doc)}
                     onClose={() => setPreview(null)} />
      )}

      {tab === 'Identity' && (
        <div className="card">
          <table>
            <thead><tr><th>Page</th><th>Document</th><th>Confidence</th><th>Identified by</th></tr></thead>
            <tbody>
              {report.pages.map(p => (
                <tr key={p.page}>
                  <td className="mono">p.{p.page}</td>
                  <td>{p.document_type}{p.needs_human && <span className="pill medium" style={{ marginLeft: 6 }}>CONFIRM</span>}</td>
                  <td>{p.confidence.toFixed(2)}</td>
                  <td className="muted" style={{ fontSize: 12 }}>{p.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ display: 'flex', gap: 10, marginTop: 18, alignItems: 'center',
                    flexWrap: 'wrap' }}>
        {/* "Proceed to Decision" named a screen, so it read as navigation and sat unread at
            the foot of six tabs. Naming the act instead -- and saying which way the engine
            leans -- makes the next step legible from the verdict banner down. */}
        <button className="gold" onClick={onProceed}>Approve or reject this case →</button>
        <span className="muted" style={{ fontSize: 'var(--t-small)' }}>
          {report.flags.some(f => f.blocks_ppo)
            ? `${report.flags.filter(f => f.blocks_ppo).length} finding(s) block a PPO — the engine recommends returning the case.`
            : 'Nothing blocks a PPO on these papers.'}
        </span>
      </div>
    </div>
  )
}

function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <tr>
      <td className="muted" style={{ width: 150 }}>{k}</td>
      <td className={mono ? 'mono' : undefined}>{v}</td>
    </tr>
  )
}
