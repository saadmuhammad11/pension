/** One case: where it is, what to do now, its papers, the AI findings, every remark.
 *
 *  Built for an officer who is not a computer person: a progress bar says where the case is,
 *  one banner says what to do next with one big button, and the details sit in the tabs.
 *  The AI findings are the Accountant General's (28 Sep 2026): a department officer sees the
 *  papers, the history, and -- on a returned case -- the list of documents to attach. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchReport } from '../api'
import { ACTION_META, PRODUCT_WORDS, STATUS_META, act, addDocuments, replaceDocument, type RequestItem, getCase, gpfKindLabel, gpfState, nextStep, runCheck, setCaseType,
         type CaseAction, type CaseFull, type CaseStatus, type GpfState, type Product } from '../api/cases'
import { CaseTypePanel } from '../components/CaseTypePanel'
import { CASE_TYPE_SOURCE_WORDS, caseTypeSourceShort } from '../caseTypes'
import { useSession } from '../auth/AuthProvider'
import { ActionPanel } from '../components/ActionPanel'
import { CaseProgress } from '../components/CaseProgress'
import { DocumentList } from '../components/DocumentList'
import { HistoryTimeline } from '../components/HistoryTimeline'
import { StatusPill } from '../components/StatusPill'
import { useToast } from '../components/Toast'
import { caseTypeLabel } from '../labels'
import type { CaseReport } from '../types'
import { AnalysisLive } from './AnalysisLive'
import { CaseFindings } from './CaseFindings'
import { RoundsPanel } from '../components/RoundsPanel'
import { ScanViewer } from '../scan/ScanViewer'
import { withToken } from '../auth/session'
import { post } from '../api/client'

const TABS = ['Documents', 'AI findings', 'Remarks & history'] as const
type Tab = typeof TABS[number]

/** Actions the panel on the right lists with their own confirm step; the banner's big button
 *  is for the others, so the same action never shows twice on one screen. */
const PANEL_ACTIONS: CaseAction[] = ['FORWARD', 'APPROVE', 'REQUEST_DOCS', 'RETURN', 'REJECT', 'OVERRIDE']

export function CaseDetail({ caseId, onBack, initialTab, onProduct }:
  { caseId: string; onBack: (product: Product) => void; initialTab?: Tab
    /** Told the case's product once it is known, so the address and the header can follow it. */
    onProduct?: (product: Product) => void }) {
  const { can, user } = useSession()
  const toast = useToast()
  const [c, setC] = useState<CaseFull | null>(null)
  const [report, setReport] = useState<CaseReport | null>(null)
  // The findings are read at the AG; a department officer opens on the papers.
  const deptView = (user?.role ?? '') === 'DEPT_OFFICER'
  const [tab, setTab] = useState<Tab>(initialTab && !(deptView && initialTab === 'AI findings') ? initialTab : deptView ? 'Documents' : 'AI findings')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [pendingAction, setPendingAction] = useState<CaseAction | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const role = user?.role ?? ''

  // Every load carries a sequence number; an answer older than the newest request (or than the
  // last thing the officer did) is dropped, so a slow poll cannot overwrite a fresh action.
  const seq = useRef(0)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const load = useCallback(async () => {
    const mine = ++seq.current
    try {
      const full = await getCase(caseId)
      if (!mounted.current || mine !== seq.current) return
      setC(full)
      setError(null)
      const run = full.latest_run
      if (run && run.state === 'done' && !deptView && full.product !== 'GPF') {
        let rep: CaseReport | null = null
        try { rep = await fetchReport(run.run_id) } catch { rep = null }
        if (!mounted.current || mine !== seq.current) return
        setReport(rep)
      } else setReport(null)
    } catch (e) {
      if (mounted.current && mine === seq.current) setError(e instanceof Error ? e.message : String(e))
    }
  }, [caseId, deptView])

  useEffect(() => { load() }, [load])
  const told = useRef<string | null>(null)
  useEffect(() => {
    if (c && onProduct && told.current !== c.product) { told.current = c.product; onProduct(c.product) }
  }, [c, onProduct])

  // Poll while the case can change under the reader: fast during the AI check, slowly while the
  // other side holds it; not at all when the tab is hidden or the case is closed.
  const live = c?.status === 'AI_CHECKING' ? 4000
    : c && ['FORWARDED', 'UNDER_REVIEW', 'AI_FAILED', 'DRAFT', 'AI_CHECKED', 'RETURNED', 'DOCS_REQUESTED'].includes(c.status) ? 15000 : 0
  useEffect(() => {
    if (!live) return
    const tick = () => { if (document.visibilityState === 'visible') load() }
    const t = setInterval(tick, live)
    document.addEventListener('visibilitychange', tick)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', tick) }
  }, [live, load])

  async function doAct(action: CaseAction, remark: string, toStatus?: CaseStatus, items?: RequestItem[]) {
    setBusy(true)
    try {
      let answer: { case: CaseFull } | null = null
      if (action === 'OVERRIDE') answer = await act(caseId, 'OVERRIDE', { reason: remark, to_status: toStatus })
      else if (action !== 'ADD_DOCS' && action !== 'RUN_CHECK') answer = await act(caseId, action, { remark, ...(items ? { items } : {}) })
      seq.current += 1                                    // anything already in flight is stale now
      if (answer?.case && answer.case.id === caseId) setC(answer.case)
      await load()
      toast(ACTION_META[action].done)
      setPendingAction(null)
    } finally { setBusy(false) }
  }

  async function doCheck() {
    setBusy(true); setError(null)
    try { await runCheck(caseId); seq.current += 1; await load(); setTab('AI findings'); toast(ACTION_META.RUN_CHECK.done) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); toast('Could not start the AI check', 'bad') }
    finally { setBusy(false) }
  }

  async function doAdd(files: FileList | null) {
    if (!files || !files.length) return
    const picked = Array.from(files)                      // the FileList is emptied when the input is reset
    setBusy(true); setError(null)
    try { await addDocuments(caseId, picked); seq.current += 1; await load(); setTab('Documents'); toast(`${picked.length} document${picked.length === 1 ? '' : 's'} added. Now run the AI check.`) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); toast('Could not add the documents', 'bad') }
    finally { setBusy(false) }
  }

  async function doReplace(docId: string, file: File) {
    setBusy(true); setError(null)
    try { await replaceDocument(caseId, docId, file); seq.current += 1; await load(); toast('Document replaced. Submit the case when ready.') }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); toast('Could not replace the document', 'bad') }
    finally { setBusy(false) }
  }

  const [holdRun, setHoldRun] = useState<string | null>(null)
  useEffect(() => { if (c?.status === 'AI_CHECKING' && c.latest_run) setHoldRun(c.latest_run.run_id) }, [c?.status, c?.latest_run?.run_id])
  const analysisDone = useCallback(() => { setHoldRun(null); load() }, [load])

  const step = useMemo(() => c ? nextStep(c, role) : null, [c, role])

  if (!c || !step) {
    return (
      <div className="screen container" style={{ paddingTop: 22 }}>
        <button className="ghost" onClick={() => onBack('PENSION')}>Back to the register</button>
        {error ? <div className="banner bad" style={{ marginTop: 12 }}><span className="mark">!</span><div className="sub">{error}</div></div>
               : <div className="skeleton" style={{ height: 120, marginTop: 12 }} />}
      </div>
    )
  }

  const run = c.latest_run
  const m = STATUS_META[c.status]
  const hasIssues = run ? (run.verdict !== 'FORWARD' || (run.high_flags ?? 0) > 0 || (run.blocking_flags ?? []).length > 0) : true
  const deptSide = deptView || (role === 'ADMIN' && m.side === 'department')
  const canReview = !!can?.dispose && (m.side === 'ag' || !!can?.override)
  // The documents an automatic return (or the AG's own return) asked for, for this round.
  const sentBack = m.side === 'department' ? [...c.events].reverse().find(e => ['AUTO_RETURN', 'RETURN', 'REQUEST_DOCS'].includes(e.action)) : undefined
  const missingDocs = (sentBack?.payload as { missing_checklist?: { id: string; requirement: string; status?: string }[] } | undefined)?.missing_checklist ?? []
  const agRemarks = c.events.filter(e => (e.actor_role === 'AG_REVIEWER' || e.actor_role === 'ADMIN') && e.remark && e.action !== 'CREATE' && e.action !== 'FORWARD')
  const lastAg = agRemarks[agRemarks.length - 1]
  // The tab's count is the number of findings listed under it, the same as the Flags tab inside.
  const findings = report?.flags.length ?? 0
  const findingsHot = !!report?.flags.some(f => f.severity === 'HIGH')
  // The analysis stays on screen until it has shown its own finish (the bar at 100%, then on
  // to the findings), not cut off the moment the poll sees the case move on.
  const verifying = c.status === 'AI_CHECKING' || (!!run && holdRun === run.run_id && c.status !== 'AI_FAILED')
  const remarks = c.events.filter(e => e.remark && e.actor_role !== 'SYSTEM').length

  function primary() {
    if (!step?.action) return
    if (step.action === 'RUN_CHECK') doCheck()
    else if (step.action === 'ADD_DOCS') fileInput.current?.click()
    else setPendingAction(step.action)
  }

  const bannerTone = m.pill === 'high' || c.status === 'RETURNED' || c.status === 'DOCS_REQUESTED' ? ' is-bad' : m.side === 'ag' && deptSide ? ' is-wait' : ''
  const buttonInPanel = !!step.action && PANEL_ACTIONS.includes(step.action) && c.allowed_actions.includes(step.action)

  return (
    <div className="screen container" style={{ paddingTop: 18 }}>
      <input ref={fileInput} type="file" multiple style={{ display: 'none' }} aria-label="Attach documents to the case" onChange={e => { doAdd(e.target.files); e.target.value = '' }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <button className="ghost" onClick={() => onBack(c.product)}>Back to the register</button>
        <h1 style={{ margin: 0 }}>{c.product === 'GPF' ? 'GP Fund case' : 'Case'} <span className="mono">{c.case_no}</span></h1>
        <StatusPill status={c.status} />
      </div>
      <p className="lead" style={{ marginTop: 4 }}>
        <strong>{c.claimant_name ?? 'Claimant name not yet extracted'}</strong>
        {c.product === 'GPF' && c.intake?.gpf_kind ? ` · ${gpfKindLabel(String(c.intake.gpf_kind))}` : ''}
        {c.product !== 'GPF' && c.case_type && <> · <span title={CASE_TYPE_SOURCE_WORDS[c.case_type_source ?? ''] ?? ''}>{caseTypeLabel(c.case_type)}{c.case_type_source === 'DETECTED' ? ' (detected)' : ''}</span></>}
        {' · '}{c.department_name}
      </p>

      <CaseProgress status={c.status} />

      {/* What to do now. */}
      <div className={`next${bannerTone}`}>
        <div className="next-body">
          <p className="next-title">{step.title}</p>
          <p className="next-text">{step.text}</p>
          {lastAg && deptSide && (c.status === 'RETURNED' || c.status === 'DOCS_REQUESTED' || c.status === 'REJECTED') && (
            <p className="next-text" style={{ marginTop: 8, color: 'var(--ink)' }}>
              <strong>Remarks of the Accountant General:</strong> “{lastAg.remark}” <span className="muted">— {lastAg.actor_name}, {lastAg.at.replace('T', ' ').slice(0, 16)}</span>
            </p>
          )}
          {missingDocs.length > 0 && (
            <div style={{ marginTop: 8, color: 'var(--ink)' }}>
              <strong>Documents to attach{sentBack?.action === 'AUTO_RETURN' ? ' (found missing by the verification)' : ''}:</strong>
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {missingDocs.map(d => <li key={d.id}><strong>{d.id}</strong> {d.requirement}{d.status === 'DEFECTIVE' ? ' — the copy attached is defective' : ''}</li>)}
              </ul>
            </div>
          )}
        </div>
        {step.action && !buttonInPanel && (
          <button className={`big ${ACTION_META[step.action].tone === 'gold' ? 'gold' : 'primary'}`} onClick={primary} disabled={busy}>
            {step.action === 'RUN_CHECK' ? PRODUCT_WORDS[c.product].verify : ACTION_META[step.action].label}
          </button>
        )}
      </div>

      {error && <div className="banner bad" style={{ marginTop: 'var(--s3)' }}><span className="mark">!</span><div className="sub">{error}</div></div>}

      {/* For the AG: what the department wrote when it resubmitted. */}
      {c.officer_remark && !deptSide && m.side === 'ag' && (
        <div className="banner" style={{ marginTop: 'var(--s3)' }}>
          <span className="mark" aria-hidden="true" style={{ background: 'var(--green3)' }} />
          <div><div className="sub"><strong>Remarks of the submitting officer:</strong> “{c.officer_remark}”</div></div>
        </div>
      )}

      <div className="detail-grid">
        <div style={{ minWidth: 0 }}>
          <div className="tabs" role="tablist">
            <button className="tab" role="tab" aria-selected={tab === 'Documents'} onClick={() => setTab('Documents')}>
              Documents <span className="count">{c.documents.length}</span>
            </button>
            {!deptView && (
              <button className="tab" role="tab" aria-selected={tab === 'AI findings'} onClick={() => setTab('AI findings')}>
                {c.product === 'GPF' ? 'GP Fund examination' : 'AI findings'} {report && <span className={`count${findingsHot ? ' hot' : ''}`}>{findings}</span>}
              </button>
            )}
            <button className="tab" role="tab" aria-selected={tab === 'Remarks & history'} onClick={() => setTab('Remarks & history')}>
              Remarks and history <span className="count">{remarks}</span>
            </button>
          </div>

          {tab === 'Documents' && (
            <div className="card" style={{ marginTop: 'var(--s4)' }}>
              <DocumentList caseId={c.id} documents={c.documents} currentSubmission={c.submission_no} busy={busy}
                            onReplace={c.allowed_actions.includes('ADD_DOCS') ? (d, f) => doReplace(d.id, f) : undefined} />
              {c.allowed_actions.includes('ADD_DOCS') && (
                <div className="row" style={{ gap: 12, marginTop: 'var(--s4)', alignItems: 'center' }}>
                  <button onClick={() => fileInput.current?.click()} disabled={busy}>Add documents</button>
                  <span className="help">After attaching the documents, submit the case to the Accountant General.</span>
                </div>
              )}
            </div>
          )}

          {tab === 'AI findings' && !deptView && c.product === 'GPF' && (
            <GpfExamination c={c} busy={busy} onVerify={doCheck} onChanged={load} offerVerify={step.action !== 'RUN_CHECK'} />
          )}

          {tab === 'AI findings' && !deptView && c.product !== 'GPF' && (
            <div style={{ marginTop: 'var(--s4)' }}>
              {!verifying && c.submission_no > 1 && (
                <div style={{ marginBottom: 'var(--s4)' }}>
                  <RoundsPanel caseId={c.id} refreshKey={`${c.updated_at}${run?.state}`} onlyLatest agView />
                </div>
              )}
              {verifying && run && <AnalysisLive runId={run.run_id} onDone={analysisDone} />}
              {!verifying && report && run && (
                <CaseFindings report={report} runId={run.run_id} canDispose={canReview} onSettled={load} />
              )}
              {!verifying && !report && (
                <div className="card">
                  <div className="empty">
                    {run?.state === 'failed'
                      ? <><strong>The verification did not complete.</strong><div className="help" style={{ marginTop: 6 }}>{run.error}</div></>
                      : <strong>The case has not yet been verified with AI.</strong>}
                    {/* The banner above already carries the button when verifying is the next step; one button per screen. */}
                    {c.allowed_actions.includes('RUN_CHECK') && step.action !== 'RUN_CHECK' && (
                      <div style={{ marginTop: 'var(--s3)' }}><button className="primary big" onClick={doCheck} disabled={busy}>Verify case with AI</button></div>
                    )}
                    {c.allowed_actions.includes('RUN_CHECK') && step.action === 'RUN_CHECK' && (
                      <div className="help" style={{ marginTop: 6 }}>Use <em>{PRODUCT_WORDS[c.product].verify}</em> above.</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === 'Remarks & history' && (
            <div className="card" style={{ marginTop: 'var(--s4)' }}>
              <HistoryTimeline events={c.events} highlightAg={deptSide} />
            </div>
          )}
          {tab === 'Remarks & history' && c.submission_no > 1 && (
            <div style={{ marginTop: 'var(--s4)' }}>
              <div className="label" style={{ marginBottom: 6 }}>Submission rounds</div>
              <RoundsPanel caseId={c.id} refreshKey={c.updated_at} agView={!deptView} />
            </div>
          )}
        </div>

        <aside className="stack">
          <ActionPanel actions={c.allowed_actions} hasIssues={hasIssues} busy={busy} onAct={doAct}
                       checklist={(report?.checklist?.items ?? []).map(i => ({ id: i.id, requirement: i.requirement, status: i.status }))}
                       open={pendingAction} onOpenChange={setPendingAction} />
          {canReview && m.side === 'ag' && !c.allowed_actions.some(a => PANEL_ACTIONS.includes(a)) && (
            <div className="card">
              <div className="label" style={{ marginBottom: 6 }}>What you can do</div>
              <div className="help">Approve, reject, return and request-documents open once the AI examination of these papers has completed.</div>
            </div>
          )}
          {c.allowed_actions.includes('RUN_CHECK') && !verifying && step.action !== 'RUN_CHECK' && (
            <div className="card">
              <div className="label" style={{ marginBottom: 8 }}>Verification</div>
              <button onClick={doCheck} disabled={busy} style={{ width: '100%' }}>{c.product === 'GPF' ? 'Examine the claim again' : 'Verify the case again'}</button>
              <div className="help" style={{ marginTop: 8 }}>Reads the documents afresh; the outcome moves the case again.</div>
            </div>
          )}
          {c.product !== 'GPF' && (
            <CaseTypePanel c={c} busy={busy}
                           mayCorrect={!!can?.correct_case_type}
                           mayDeclare={deptView && ['DRAFT', 'AI_CHECKED', 'RETURNED', 'DOCS_REQUESTED'].includes(c.status)}
                           onSet={async body => { setBusy(true); try { await setCaseType(caseId, body); seq.current += 1; await load(); toast('Case type recorded.') } finally { setBusy(false) } }} />
          )}
          <div className="card">
            <div className="label" style={{ marginBottom: 6 }}>Case particulars</div>
            <table style={{ margin: 0 }}><tbody style={{ fontSize: 'var(--t-small)' }}>
              {c.product !== 'GPF' && (
                <tr><td className="muted" style={{ border: 0, padding: '3px 0' }}>Case type</td>
                    <td style={{ border: 0, padding: '3px 0' }}>{c.case_type ? caseTypeLabel(c.case_type) : 'not declared'}{c.case_type_source ? ` · ${caseTypeSourceShort(c.case_type_source)}` : ''}</td></tr>
              )}
              {c.product !== 'GPF' && !deptView && c.detected_case_type && c.detected_case_type !== c.case_type && (
                <tr><td className="muted" style={{ border: 0, padding: '3px 0' }}>AI read it as</td>
                    <td style={{ border: 0, padding: '3px 0', color: 'var(--amber)' }}>{caseTypeLabel(c.detected_case_type)}</td></tr>
              )}
              <tr><td className="muted" style={{ border: 0, padding: '3px 0' }}>Pension section</td><td style={{ border: 0, padding: '3px 0' }}>{c.pension_section ?? 'Legacy'}</td></tr>
              <tr><td className="muted" style={{ border: 0, padding: '3px 0' }}>Filed</td><td style={{ border: 0, padding: '3px 0' }}>{c.created_at.replace('T', ' ').slice(0, 16)}</td></tr>
              <tr><td className="muted" style={{ border: 0, padding: '3px 0' }}>Last change</td><td style={{ border: 0, padding: '3px 0' }}>{c.updated_at.replace('T', ' ').slice(0, 16)}</td></tr>
              <tr><td className="muted" style={{ border: 0, padding: '3px 0' }}>Submission</td><td style={{ border: 0, padding: '3px 0' }}>submission {c.submission_no}</td></tr>
              <tr><td className="muted" style={{ border: 0, padding: '3px 0' }}>Verifications</td><td style={{ border: 0, padding: '3px 0' }}>{c.runs.length}</td></tr>
            </tbody></table>
          </div>
        </aside>
      </div>
    </div>
  )
}

/** The GP Fund module's examination of a claim (28 Sep 2026): the reading job while it reads, then
 *  the module's own screens -- examination, cure, SAP extracts, disposal, issue pack -- framed
 *  here, signed in as the officer the portal signed in. What the officer does there moves the
 *  case: passed for payment, or nothing left open, approves it; a return sends it back to the
 *  department with the hard stops. */
/** The GP Fund module's own stage names (GP/backend/gpf/reading/pipeline.py), as the officer reads them. */
const GPF_STAGE: Record<string, string> = {
  queued: 'Waiting to start', ingest: 'Receiving the pages', classify: 'Identifying the document',
  extract: 'Reading the fields', 'page-done': 'Page read', illegible: 'Illegible page',
  assemble: 'Assembling the case facts', done: 'Read',
}

function GpfExamination({ c, busy, onVerify, onChanged, offerVerify = true }: { c: CaseFull; busy: boolean; onVerify: () => void; onChanged: () => void; offerVerify?: boolean }) {
  const [state, setState] = useState<GpfState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [frameHeight, setFrameHeight] = useState(1200)
  const [frameSigned, setFrameSigned] = useState(false)
  const reading = c.status === 'AI_CHECKING'
  const hasFrame = !!state?.embed_url
  // The framed module is behind the portal's sign-in (5 Oct 2026): a frame cannot carry the
  // session token, so the server sets a GP-Fund-only cookie first, renewed well inside its 2 hours.
  useEffect(() => {
    if (!hasFrame) return
    let live = true
    const sign = () => post('/api/v2/auth/gpf-session')
      .then(() => { if (live) setFrameSigned(true) })
      .catch(e => { if (live) setError(e instanceof Error ? e.message : String(e)) })
    sign()
    const renew = window.setInterval(sign, 90 * 60_000)
    return () => { live = false; window.clearInterval(renew) }
  }, [hasFrame])
  // The framed module reports its height, so the case screen scrolls as one page.
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== window.location.origin) return
      const h = (e.data as { gpfHeight?: number } | null)?.gpfHeight
      if (typeof h === 'number' && h > 200) setFrameHeight(Math.min(20000, Math.ceil(h) + 24))
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [])
  useEffect(() => {
    let live = true
    const tick = () => gpfState(c.id).then(s => { if (!live) return; setState(s); setError(null); if (s.status !== c.status) onChanged() })
      .catch(e => { if (live) setError(e instanceof Error ? e.message : String(e)) })
    tick()
    // While the module reads, the job's page count is the progress; afterwards, a slow poll
    // follows the officer's disposal in the frame back onto the case.
    const t = setInterval(tick, reading ? 1500 : 8000)
    return () => { live = false; clearInterval(t) }
  }, [c.id, c.status, reading])   // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !state) return <div className="banner bad" style={{ marginTop: 'var(--s4)' }}><span className="mark">!</span><div className="sub">{error}</div></div>
  if (!state) return <div className="skeleton" style={{ height: 120, marginTop: 'var(--s4)' }} />
  if (!state.module_up && !state.gpf_case_id) {
    return <div className="banner warn" style={{ marginTop: 'var(--s4)' }}><span className="mark">!</span><div className="sub">The GP Fund module is not running. Start it on the server (<code>./GP/run.sh</code>) and try again.</div></div>
  }
  if (reading || (state.job && !state.gpf_case_id)) {
    const j = state.job
    const pct = j && j.total ? Math.round(((j.done ?? 0) / j.total) * 100) : 0
    // The same scanning view as the pension analysis (shared/scan/ScanViewer), in GP Fund's gold,
    // on the page the module is reading, under the module's own stage names.
    const pg = j?.page ?? (j && j.total ? Math.min(j.total, (j.done ?? 0) + 1) : null)
    const stageWord = GPF_STAGE[j?.stage ?? ''] ?? 'Reading the claim'
    return (
      <div className="card gpf-progress" style={{ marginTop: 'var(--s4)' }}>
        <div style={{ fontWeight: 600, fontSize: 16 }}>{j?.state === 'error' ? 'The examination could not read the pages' : 'Reading the claim…'}</div>
        <div className="muted">{j?.detail ?? j?.message ?? 'The module classifies each page and extracts its fields; a page takes 5 to 15 seconds.'}</div>
        <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}><span style={{ width: `${pct}%` }} /></div>
        {j && j.total ? <div className="muted" style={{ fontSize: 'var(--t-small)' }}>{j.done ?? 0} of {j.total} pages{j.stage ? ` · ${stageWord}` : ''}</div> : null}
        <div className="gpf-scan" style={{ marginTop: 'var(--s4)' }}>
          <ScanViewer
            src={pg ? withToken(`/api/v2/cases/${encodeURIComponent(c.id)}/gpf/pages/${pg}`) : null}
            pageKey={pg}
            state={j?.state === 'error' ? 'failed' : j?.state === 'done' ? 'done' : 'live'}
            label={j?.artefact ? `${stageWord} · ${String(j.artefact).replace(/_/g, ' ').toLowerCase()}` : stageWord}
            caption={[pg ? `Page ${pg}${j?.total ? ` of ${j.total}` : ''}` : 'Preparing the pages', stageWord]}
            note={j && j.state === 'running' && (j.elapsed ?? 0) > 20 && (j.done ?? 0) === 0 ? 'The first page takes longest while the model warms up.' : null}
            waiting="Preparing the pages…" />
        </div>
      </div>
    )
  }
  if (!state.gpf_case_id || !state.embed_url) {
    return (
      <div className="card" style={{ marginTop: 'var(--s4)' }}>
        <div className="empty">
          <strong>The claim has not yet been examined.</strong>
          {c.allowed_actions.includes('RUN_CHECK') && offerVerify && (
            <div style={{ marginTop: 'var(--s3)' }}><button className="primary big" onClick={onVerify} disabled={busy}>Examine with AI</button></div>
          )}
          {c.allowed_actions.includes('RUN_CHECK') && !offerVerify && (
            <div className="help" style={{ marginTop: 6 }}>Use <em>Examine with AI</em> above.</div>
          )}
        </div>
      </div>
    )
  }
  const counts = state.case?.counts ?? {}
  return (
    <div style={{ marginTop: 'var(--s4)' }}>
      <div className="row" style={{ gap: 12, marginBottom: 10, alignItems: 'baseline' }}>
        <span className="muted" style={{ fontSize: 'var(--t-small)' }}>
          GP Fund module · case <span className="mono">{state.gpf_case_id}</span>
          {state.case?.caseDisp ? ` · ${state.case.caseDisp}` : ''}
          {' · '}{counts.hard ?? 0} hard stop{counts.hard === 1 ? '' : 's'} · {counts.conf ?? 0} to verify · {counts.sap ?? 0} SAP item{counts.sap === 1 ? '' : 's'} · {counts.adv ?? 0} observation{counts.adv === 1 ? '' : 's'}
        </span>
        {/* No "Open in the module" (removed 5 Oct 2026): the module's full page shows every GP Fund
            case and its own intake, outside the portal's register and workflow. The frame is the way in. */}
      </div>
      {frameSigned
        ? <iframe className="gpf-frame" src={state.embed_url} title="GP Fund examination" style={{ height: frameHeight }} />
        : <div className="card"><div className="skeleton" style={{ height: 120 }} /><div className="muted" style={{ marginTop: 8 }}>Opening the GP Fund module…</div></div>}
    </div>
  )
}
