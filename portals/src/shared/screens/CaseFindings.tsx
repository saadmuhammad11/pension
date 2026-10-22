/** The AI findings of one run: summary, extracted data, checklist, flags, identity.
 *
 *  Copied from the AI Pension Portal's Review screen. Who may act on a finding is decided by
 *  the signed-in user's capabilities (`can.dispose`), which the server enforces on its side. */
import { fmtAmount, fmtDateTime } from '../fmt'
import { useEffect, useState, type CSSProperties } from 'react'
import { ChecklistPanel } from '../components/ChecklistPanel'
import { PagePreview } from '../components/PagePreview'
import { type LapsedDisposition, fetchDispositions, postDisposition, signatureImageUrl, specimenImageUrl,
         type Disposition } from '../api'
import {
  caseTypeLabel, confidenceWord, documentLabel, findingLabel, maskIds, verdictLabel,
} from '../labels'
import type { CaseReport, Flag, Severity, SpecimenSideBySide } from '../types'
import { imageRefused, useMediaTokenVersion } from '../auth/useMediaToken'


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
  { f, index = 0, runId, onPage, disposition, onDispose, mayDecide, text, lastOpen }:
  { f: Flag; index?: number; runId: string
    /** Text for the screen: national ID numbers masked unless the officer asked to see them. */
    text: (s: string) => string
    onPage: (page: number, doc: string) => void
    disposition?: Disposition
    onDispose: (flagId: string, action: Disposition['action'], ground: string) => Promise<void>
    mayDecide: boolean
    lastOpen?: (action: Disposition['action']) => boolean },
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

      <FlagDisposition f={f} disposition={disposition} onDispose={onDispose} mayDecide={mayDecide} lastOpen={lastOpen} />
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
  useMediaTokenVersion()                                  // the cut-out's address carries the media token (F10)
  return (
    <div className="row" style={{ marginTop: 'var(--s3)', gap: 'var(--s3)', alignItems: 'stretch',
                                  flexWrap: 'wrap', color: 'var(--ink)' }}>
      <div style={box}>
        <div style={{ fontWeight: 700 }}>On the sanction form{s.page ? ` (p.${s.page})` : ''}</div>
        {s.signature_image
          ? <img src={signatureImageUrl(runId, s.signature_image)} alt="Signature cut from the form" style={img} onError={imageRefused} />
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
/** True when recording `action` on `flagId` would leave no finding open on the case: the officer
 *  is told so and asked for confirmation (F4). Only a WAIVE clears a finding. */
export function clearsLastOpenFinding(flags: { id: string }[], disposed: Record<string, { action: string }>,
                                      flagId: string, action: Disposition['action']): boolean {
  if (action !== 'WAIVE') return false
  const open = flags.filter(f => f.id !== flagId && disposed[f.id]?.action !== 'WAIVE')
  return open.length === 0
}

/** Characters of reason a decision carries. Both decisions are recorded against the officer's
 *  name, so both are given one; the server holds the same minimum (api.dispositions.MIN_GROUND). */
export const MIN_REASON = 10

/** What each decision does, in the words the officer sees (F4: the labels say what happens). */
export const DISPOSITION_WORDS: Record<string, string> = {
  WAIVE: 'Approved — does not stand against the case',
  UPHOLD: 'Rejected — the finding stands; the case cannot be approved while it does',
  HOLD: 'On hold — exceptional-case lane',
}

function FlagDisposition(
  { f, disposition, onDispose, mayDecide, lastOpen = () => false }:
  { f: Flag; disposition?: Disposition
    onDispose: (flagId: string, action: Disposition['action'], ground: string) => Promise<void>
    mayDecide: boolean
    /** Whether recording this action would clear the last open finding (F4). */
    lastOpen?: (action: Disposition['action']) => boolean },
) {
  const [open, setOpen] = useState(false)
  const [action, setAction] = useState<Disposition['action'] | null>(null)
  const [ground, setGround] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const TONE_FOR: Record<string, string> = { WAIVE: 'low', UPHOLD: 'high', HOLD: 'medium' }
  const WORD = DISPOSITION_WORDS

  if (disposition && !open) {
    return (
      <div style={{ marginTop: 'var(--s3)', paddingTop: 'var(--s3)',
                    borderTop: '1px dashed rgba(31,41,55,.12)' }}>
        <div className="row" style={{ gap: 'var(--s2)' }}>
          <span className={`pill ${TONE_FOR[disposition.action]}`}>{WORD[disposition.action]}</span>
          <span className="muted" style={{ fontSize: 'var(--t-small)' }}>
            {disposition.officer} · {fmtDateTime(disposition.at)}
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

  // Both decisions are recorded against the officer's name, so both are given a reason. Ten
  // characters, one box, nothing else asked (13 Oct 2026).
  const blocked = !action || ground.trim().length < MIN_REASON

  return (
    <div style={{ marginTop: 'var(--s3)', paddingTop: 'var(--s3)',
                  borderTop: '1px dashed rgba(31,41,55,.12)' }}>
      <div className="row" style={{ gap: 'var(--s2)' }}>
        <button className={action === 'WAIVE' ? 'primary' : ''} onClick={() => { setAction('WAIVE') }}
                style={{ padding: '7px 14px', fontSize: 'var(--t-small)' }}>
          Approve
        </button>
        <button className={action === 'UPHOLD' ? 'primary' : ''} onClick={() => { setAction('UPHOLD') }}
                style={{ padding: '7px 14px', fontSize: 'var(--t-small)' }}>
          Reject
        </button>
      </div>
      {action && (
        <div style={{ marginTop: 'var(--s3)' }}>
          <div className="label" style={{ marginBottom: 4 }}>
            {action === 'WAIVE'
              ? `Reason for approving this finding (required, at least ${MIN_REASON} characters)`
              : `Reason for rejecting this finding (required, at least ${MIN_REASON} characters)`}
          </div>
          <textarea rows={2} value={ground} onChange={e => setGround(e.target.value)}
                    placeholder="Recorded against your name in the audit trail…" />
        </div>
      )}
      {action && lastOpen(action) && (
        // The last open finding: once it is approved nothing stands against the case and it can
        // be approved as a whole, so the officer is told before it is recorded (F4). Told, not
        // asked to tick a second box as well (13 Oct 2026): the reason is the confirmation.
        // Nothing is approved by itself (M1); the decision is still the AG's, with a remark.
        <div className="banner warn" style={{ marginTop: 'var(--s3)' }} role="status">
          <span className="mark" aria-hidden="true">!</span>
          <div className="sub">
            <strong>This is the last open finding.</strong> Once it is approved, nothing stands against the case and it can be approved.
          </div>
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
  //: Every string this screen prints that may carry a national identity number goes through
  //: here. There was a "Show ID numbers" button that turned it off; it is gone (22 Oct 2026)
  //: and the mask is now unconditional. Only the middle group is hidden, so a number can still
  //: be matched against a paper -- which is what the mask was written for.
  const text = maskIds

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
      {/* A line stood here (22 Oct 2026): "Fresh - Self · Form B-I · claimant <name> · OFFICE OF
          THE PRINCIPAL Govt. Pilot Higher Secondary School, Wahdat Colony, Lahore". The type
          is the first row of the Summary below it and is in the line under the case number;
          the claimant is in that line too; the prescribed form is what AG-04 is about and is
          read on the Checklist. What it added was the forwarding office, in the papers' own
          shouting capitals, at the top of the findings.

          Beside it stood "Show ID numbers". The button is gone and the masking it switched is
          not: a national identity number on this screen reads 35201-•••••••-2, as it has
          since the mask was written, and there is no longer a control that turns it off. */}
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

      {/* One box (22 Oct 2026). "Case" and "Source" stood side by side and Source held two
          rows, one of which -- Pages -- was the page count a second time: "Pages read 28"
          on the left and "Pages 28" on the right, two labels for one number, because the
          pipeline reads every page of the bundle. They are one row now, and it says "27 of 28"
          on the day they differ, which is the only day the distinction was ever worth a line.
          The heading went with the split: the tab above already says Summary. */}
      {tab === 'Summary' && (
        <div className="card">
          <table><tbody>
            <Row k="Case type" v={declaredType(report) ? caseTypeLabel(declaredType(report)) : '— routed to human'} />
            <Row k="Confidence" v={confidenceWord(report.case_type.case_type_confidence)} title={`Model confidence ${report.case_type.case_type_confidence.toFixed(2)}`} />
            <Row k="Evidence" v={report.case_type.case_type_evidence} />
            <Row k="Documents identified" v={`${report.documents.length}`} />
            <Row k="Pages read" v={report.pages.length === report.source.source_pages
              ? `${report.pages.length}` : `${report.pages.length} of ${report.source.source_pages}`} />
            <Row k="File" v={report.source.file} />
          </tbody></table>
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
            {/* "24 values · each read twice and required to agree" stood beside this heading
                (22 Oct 2026). The count is the length of the table under it, and the rest is
                how the pipeline reads a page -- two passes that have to match -- which is a
                fact about the machine and not about this case. What an officer needs from
                this tab is the facts and the page each was read on, and both are in the
                table. */}
            <div className="card-head">
              <h3>Facts read from the documents</h3>
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
                      <td>{fmtAmount(c.amount)}</td>
                      <td>{c.page && <span className="chip">p.{c.page}</span>}</td>
                    </tr>
                  ))}
                  {emol.printed_total != null && (
                    <tr className="total">
                      <td>Total Pay the form prints</td>
                      <td>{fmtAmount(emol.printed_total)}</td>
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
                <li key={i}>{l.action} by {l.officer} on {fmtDateTime(l.at)} — “{l.flag_title}”: {l.why}.</li>
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
                        lastOpen={a => clearsLastOpenFinding(report.flags, disposed, f.id, a)}
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

/** The case type to print: the column the DDO picked at intake, in the office's own words.
 *
 *  report.case_type.case_type is the pipeline's path -- SUPERANNUATION_PENSION, read off the
 *  papers or derived from the declaration -- and it is what the rules run on, but it is not
 *  what anybody filed. A DDO who chose "Fresh - Self" saw the screen call the case
 *  "Superannuation pension" and had to be told the two were the same thing (22 Oct 2026).
 *  The column is report.case_variant, which is the checklist column the case was worked on.
 *  Where there is none -- a legacy case, or one filed before the columns existed -- the path
 *  is all there is, and it is better than nothing. */
const declaredType = (report: CaseReport) => report.case_variant ?? report.case_type.case_type

function Row({ k, v, mono, title }: { k: string; v: string; mono?: boolean; title?: string }) {
  return (
    <tr>
      <td className="muted" style={{ width: 150 }}>{k}</td>
      <td className={mono ? 'mono' : undefined} title={title}>{v}</td>
    </tr>
  )
}
