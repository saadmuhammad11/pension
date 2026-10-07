/** The AI findings of one run: summary, extracted data, checklist, flags, identity.
 *
 *  Copied from the AI Pension Portal's Review screen. Who may act on a finding is decided by
 *  the signed-in user's capabilities (`can.dispose`), which the server enforces on its side. */
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { ChecklistPanel } from '../components/ChecklistPanel'
import { PagePreview } from '../components/PagePreview'
import { type LapsedDisposition, fetchDispositions, postDisposition, signatureImageUrl, specimenImageUrl,
         type Disposition } from '../api'
import {
  caseTypeLabel, confidenceWord, documentLabel, findingLabel, hasId, maskIds, titleCase, verdictLabel,
} from '../labels'
import type { CaseReport, Flag, Severity, SpecimenSideBySide } from '../types'


const TABS = ['Summary', 'Extracted Data', 'Checklist', 'Flags', 'Identity'] as const

const TONE: Record<Severity, { bg: string; fg: string; cls: string }> = {
  HIGH: { bg: 'var(--redbg)', fg: 'var(--red)', cls: 'high' },
  MEDIUM: { bg: 'var(--amberbg)', fg: 'var(--amber)', cls: 'medium' },
  LOW: { bg: 'var(--okbg)', fg: 'var(--ok)', cls: 'low' },
}

function Verdict({ report, text }: { report: CaseReport; text: (s: string) => string }) {
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
      <span className="mark" aria-hidden="true">{v === 'FORWARD' ? 'OK' : '!'}</span>
      <div style={{ flex: 1 }}>
        <div className="row" style={{ gap: 'var(--s2)' }}>
          <span className="title">{verdictLabel(v)}</span>
          {blocking.length > 0 && (
            <span className="pill high">blocking {blocking.join(', ')}</span>
          )}
        </div>
        <div style={{ marginTop: 2 }}>{text(report.recommendation.rationale)}</div>
        {/* §9.6 requires this sentence on the verdict banner. It is the line that keeps the
            screen a recommendation rather than a decision, so it is not styled away. */}
        <div className="muted" style={{ fontSize: 'var(--t-small)', marginTop: 'var(--s2)' }}>
          AI recommendation only; the decision rests with the Office of the Accountant General.
        </div>
      </div>
    </div>
  )
}

function FlagCard(
  { f, index = 0, runId, onPage, disposition, onDispose, mayDecide, text }:
  { f: Flag; index?: number; runId: string
    /** Text for the screen: national ID numbers masked unless the officer asked to see them. */
    text: (s: string) => string
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
          {text(f.summary || f.title)}
        </span>
      </div>
      {/* The finding in one line above; the full reasoning and action for whoever needs them. */}
      <details style={{ marginTop: 'var(--s2)', maxWidth: '82ch', color: 'var(--ink)' }}>
        <summary className="muted" style={{ cursor: 'pointer', fontSize: 'var(--t-small)' }}>Details</summary>
        <div style={{ marginTop: 6 }}>{text(f.finding)}</div>
        <div style={{ marginTop: 6, color: 'var(--ok)', fontWeight: 600 }}>→ Action: {f.required_action}</div>
      </details>
      {(f.evidence.asserted.length > 0 || f.evidence.contradicted_by.length > 0) ? (
        // The page a finding cites is the evidence for it, so it opens. A chip that names a
        // page an officer then has to hunt for in a 51-page PDF is a citation nobody checks.
        <div className="row" style={{ marginTop: 8, gap: 'var(--s1)' }}>
          <span className="muted" style={{ fontSize: 'var(--t-small)' }}>Open</span>
          {f.evidence.asserted.filter((e, i, all) => all.findIndex(x => x.page === e.page && x.doc === e.doc) === i).map(e => (
            <button key={`a${e.page}-${e.doc}`} className="chip" onClick={() => onPage(e.page, e.doc)}
                    style={{ cursor: 'pointer', border: '1px solid var(--sage2)',
                             padding: '2px 8px', fontSize: 'var(--t-micro)' }}>
              p.{e.page} {documentLabel(e.doc)}
            </button>
          ))}
          {f.evidence.contradicted_by.length > 0 && (
            <span className="muted" style={{ fontSize: 'var(--t-small)' }}>contradicted by</span>
          )}
          {f.evidence.contradicted_by.filter((e, i, all) => all.findIndex(x => x.page === e.page && x.doc === e.doc) === i).map(e => (
            <button key={`c${e.page}-${e.doc}`} className="chip" onClick={() => onPage(e.page, e.doc)}
                    style={{ cursor: 'pointer', border: '1px solid var(--sage2)',
                             padding: '2px 8px', fontSize: 'var(--t-micro)' }}>
              p.{e.page} {documentLabel(e.doc)}
            </button>
          ))}
        </div>
      ) : (
        // A finding with no page to open says so, rather than leaving a gap the officer
        // reads as "nothing to check". It happens when the paper concerned was never
        // located in the bundle.
        <div className="muted" style={{ marginTop: 8, fontSize: 'var(--t-small)' }}>
          No page located for this finding: the paper it concerns was not found in the bundle.
        </div>
      )}
      {f.specimen && <SpecimenPanel s={f.specimen} runId={runId}
                                    onPage={p => onPage(p, f.evidence.asserted[0]?.doc ?? '')} />}

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
                           onClick={() => onPage(s.page as number)}>Open p.{s.page}</button>}
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
          Approve — clears this finding
        </button>
        <button className={action === 'UPHOLD' ? 'primary' : ''} onClick={() => setAction('UPHOLD')}
                style={{ padding: '7px 14px', fontSize: 'var(--t-small)' }}>
          Reject — return to the department
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

export function CaseFindings(
  { report: given, runId, canDispose, onProceed, proceedLabel, onSettled }:
  { report: CaseReport; runId: string; canDispose: boolean; onProceed?: () => void; proceedLabel?: string
    /** Called when clearing a finding (or a checklist item) left nothing outstanding: the parent
     *  reloads the case so the decision buttons reflect it. Nothing is approved by itself (M1). */
    onSettled?: () => void },
) {
  // The report as the officer has since settled its checklist; replaced by each checklist
  // action's answer, and by a new report from the parent.
  const [live, setLive] = useState(given)
  useEffect(() => setLive(given), [given])
  const report = live
  const [tab, setTab] = useState<typeof TABS[number]>('Summary')
  const [preview, setPreview] = useState<{ page: number; doc: string } | null>(null)
  // At most five findings on screen (office rule, 30 Sep 2026), most serious first; the rest
  // one press away -- every one still counts toward the gate.
  const [showAll, setShowAll] = useState(false)
  const [disposed, setDisposed] = useState<Record<string, Disposition>>({})
  // Earlier decisions whose finding changed on a re-check (H8): shown so the officer decides afresh.
  const [lapsed, setLapsed] = useState<LapsedDisposition[]>([])
  const mayDecide = canDispose
  // National ID numbers read 35201-•••••••-2 until the officer asks for them (28 Sep 2026).
  const [showIds, setShowIds] = useState(false)
  const anyIds = useMemo(() => hasId(JSON.stringify(report)), [report])
  const text = (s: string) => showIds ? s : maskIds(s)

  useEffect(() => {
    let live = true
    fetchDispositions(runId)
      .then(d => { if (live) { setDisposed(d.current); setLapsed(d.lapsed ?? d.gate?.lapsed ?? []) } })
      .catch(() => { /* a case with no findings has nothing to fetch */ })
    return () => { live = false }
  }, [runId])

  async function dispose(flagId: string, action: Disposition['action'], ground: string) {
    const r = await postDisposition(runId, { flag_id: flagId, action, ground })
    setDisposed(r.current)
    setLapsed(r.gate?.lapsed ?? [])
    if ((r as { case?: unknown }).case) onSettled?.()
  }
  const emol = report.emoluments

  return (
    <div className="findings">
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <p className="lead" style={{ marginTop: 0 }}>
          {caseTypeLabel(report.case_type.case_type)}
          {report.case_type.prescribed_form && ` · Form ${report.case_type.prescribed_form}`}
          {report.claimant_name && ` · claimant ${report.claimant_name}`}
          {report.forwarding_department && ` · ${titleCase(report.forwarding_department)}`}
        </p>
        {anyIds && (
          <button type="button" className="ghost" style={{ padding: '4px 10px', minHeight: 0, fontSize: 'var(--t-small)' }}
                  onClick={() => setShowIds(!showIds)} aria-pressed={showIds} title="National ID numbers are masked on screen for privacy">
            {showIds ? 'Hide ID numbers' : 'Show ID numbers'}
          </button>
        )}
      </div>

      <Verdict report={report} text={text} />

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
              <Row k="Case type" v={report.case_type.case_type ? caseTypeLabel(report.case_type.case_type) : '— routed to human'} />
              <Row k="Evidence" v={report.case_type.case_type_evidence} />
              <Row k="Confidence" v={confidenceWord(report.case_type.case_type_confidence)} title={`Model confidence ${report.case_type.case_type_confidence.toFixed(2)}`} />
              <Row k="Documents identified" v={`${report.documents.length}`} />
              <Row k="Pages read" v={`${report.pages.length}`} />
            </tbody></table>
          </div>
          <div className="card" style={{ flex: '1 1 320px' }}>
            <h3 style={{ marginTop: 0 }}>Source</h3>
            <table><tbody>
              <Row k="File" v={report.source.file} />
              <Row k="Pages" v={`${report.source.source_pages}`} />
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
                      <td className="mono">{text(r.value)}</td>
                      <td className="muted">{r.who || '—'}</td>
                      <td>
                        <button className="chip" onClick={() => setPreview({ page: r.page, doc: r.doc })}
                                style={{ cursor: 'pointer', border: '1px solid var(--sage2)',
                                         padding: '2px 8px', fontSize: 'var(--t-micro)' }}>
                          p.{r.page} {documentLabel(r.doc)}
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
                          p.{m.page} {m.src}
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
                  p.{u.page} {documentLabel(u.document)}
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
          <h3 style={{ marginTop: 0 }}>Pay lines as printed</h3>
          {/* What the pay documents print, line by line, with the page each was read on. No
              total is computed and no line is classed as pensionable: this release checks
              documents and computes nothing (business decision of 7 Oct 2026). */}
          {!emol || emol.components.length === 0 ? (
            <p className="muted">
              No pay table was read on this case. Pay lines appear here where the bundle carries
              a pay document the reader got through.
            </p>
          ) : (
            <>
              <table>
                <thead><tr><th>Line as printed</th><th>Rs./month, as printed</th><th>Source</th></tr></thead>
                <tbody>
                  {emol.components.map(c => (
                    <tr key={`${c.printed_label}-${c.page ?? ''}`}>
                      <td>{c.printed_label}</td>
                      <td>{c.amount.toLocaleString('en-PK')}</td>
                      <td>{c.page && <span className="chip">p.{c.page}</span>}</td>
                    </tr>
                  ))}
                  {emol.printed_total != null && (
                    <tr className="total">
                      <td>Total Pay the form prints</td>
                      <td>{emol.printed_total.toLocaleString('en-PK')}</td>
                      <td className="muted">as printed; whether the lines add up to it is a finding, not a figure</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </>
          )}
        </div>
        </>
        )
      })()}

      {tab === 'Checklist' && (
        <ChecklistPanel report={report} runId={runId}
                        mayDecide={mayDecide} onPage={(page, doc) => setPreview({ page, doc })}
                        onChange={(r, gate) => { setLive(r); if (gate.open) onSettled?.() }} />
      )}

      {tab === 'Flags' && lapsed.length > 0 && (
        <div className="banner warn" role="status" style={{ marginBottom: 'var(--s3)' }}>
          <span className="mark" aria-hidden="true">!</span>
          <div>
            <div className="title">{lapsed.length === 1 ? 'An earlier decision has lapsed' : `${lapsed.length} earlier decisions have lapsed`}</div>
            <div style={{ marginTop: 2 }}>
              A decision is tied to the exact finding it was made on. These findings changed or went on the
              re-check, so the decisions no longer apply and the findings await a fresh one.
            </div>
            <ul style={{ margin: 'var(--s2) 0 0', paddingLeft: '1.2em', fontSize: 'var(--t-small)' }}>
              {lapsed.map((l, i) => (
                <li key={i}>{l.action} by {l.officer} on {l.at.replace('T', ' ')} — “{l.flag_title}”: {l.why}.</li>
              ))}
            </ul>
          </div>
        </div>
      )}
      {tab === 'Flags' && (
        <div className="stagger">{report.flags.length === 0
          ? <div className="empty">No issues found.</div>
          : report.flags.slice(0, showAll ? undefined : 5).map((f, i) => (
              <FlagCard key={f.id} f={f} index={i} runId={runId} text={text}
                        onPage={(page, doc) => setPreview({ page, doc })}
                        disposition={disposed[f.id]} onDispose={dispose}
                        mayDecide={mayDecide} />
            ))}
          {report.flags.length > 5 && (
            <button className="ghost" onClick={() => setShowAll(v => !v)} style={{ marginTop: 'var(--s2)' }}>
              {showAll ? 'Show the first five only' : `Show ${report.flags.length - 5} more finding${report.flags.length - 5 === 1 ? '' : 's'}`}
            </button>
          )}</div>
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
                  <td>{documentLabel(p.document_type)}{p.needs_human && <span className="pill medium" style={{ marginLeft: 6 }}>Confirm</span>}</td>
                  <td title={`Model confidence ${p.confidence.toFixed(2)}`}>{confidenceWord(p.confidence)}</td>
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
        {onProceed && <button className="gold" onClick={onProceed}>{proceedLabel ?? 'Decide this case →'}</button>}
        {/* One verdict on the screen: the reassurance appears only where the engine's own verdict is to forward. */}
        {(report.flags.some(f => f.blocks_ppo) || report.recommendation?.verdict === 'FORWARD') && (
          <span className="muted" style={{ fontSize: 'var(--t-small)' }}>
            {report.flags.some(f => f.blocks_ppo)
              ? `${report.flags.filter(f => f.blocks_ppo).length} finding(s) block a PPO — the engine recommends returning the case.`
              : 'Nothing blocks a PPO on these papers.'}
          </span>
        )}
      </div>
    </div>
  )
}

function Row({ k, v, mono, title }: { k: string; v: string; mono?: boolean; title?: string }) {
  return (
    <tr>
      <td className="muted" style={{ width: 150 }}>{k}</td>
      <td className={mono ? 'mono' : undefined} title={title}>{v}</td>
    </tr>
  )
}
