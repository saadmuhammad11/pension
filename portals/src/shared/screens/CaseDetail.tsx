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
import { CASE_TYPE_SOURCE_WORDS } from '../caseTypes'
import { useSession } from '../auth/AuthProvider'
import { ActionPanel } from '../components/ActionPanel'
import { isAgReader } from '../auth/session'
import { returnedItems } from '../api/returnedItems'
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
import { onGpfExpired, registerGpfFrame } from '../auth/frameActivity'
import { mmss, fmtDateTime } from '../fmt'
import { nextTabFor, tabId } from '../components/tabs'
import { useMediaTokenVersion } from '../auth/useMediaToken'
import type React from 'react'

const TABS = ['Documents', 'AI findings', 'Remarks & history'] as const
type Tab = typeof TABS[number]

/** Actions the panel on the right lists with their own confirm step; the banner's big button
 *  is for the others, so the same action never shows twice on one screen. */
const PANEL_ACTIONS: CaseAction[] = ['FORWARD', 'APPROVE', 'RETURN', 'REJECT', 'OVERRIDE']

export function CaseDetail({ caseId, onBack, initialTab, onProduct }:
  { caseId: string; onBack: (product: Product) => void; initialTab?: Tab
    /** Told the case's product once it is known, so the address and the header can follow it. */
    onProduct?: (product: Product) => void }) {
  // `can` is no longer read here: the only capability this screen asked for was
  // correct_case_type, and the case-type panel stopped offering the correction (22 Oct 2026).
  const { user } = useSession()
  const toast = useToast()
  const [c, setC] = useState<CaseFull | null>(null)
  const [report, setReport] = useState<CaseReport | null>(null)
  // A report that could not be fetched is not a case that was never verified (F5): kept apart.
  const [reportError, setReportError] = useState<string | null>(null)
  // The findings are read at the AG; a department officer opens on the papers.
  const deptView = (user?.role ?? '') === 'DEPT_OFFICER'
  const [tab, setTab] = useState<Tab>(initialTab && !(deptView && initialTab === 'AI findings') ? initialTab : deptView ? 'Documents' : 'AI findings')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [pendingAction, setPendingAction] = useState<CaseAction | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const role = user?.role ?? ''

  // Every load carries a sequence number; an answer older than the last thing the officer did
  // is dropped, so a slow reply cannot overwrite a fresh action. A poll is not started while one
  // is still out (F12): on a slow link a reply slower than the interval used to be thrown away
  // every time, and the live view froze.
  const seq = useRef(0)
  const inflight = useRef(false)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const load = useCallback(async () => {
    const mine = ++seq.current
    inflight.current = true
    try {
      const full = await getCase(caseId)
      if (!mounted.current || mine !== seq.current) return
      setC(full)
      setError(null)
      const run = full.latest_run
      if (run && run.state === 'done' && !deptView && full.product !== 'GPF') {
        try {
          const rep = await fetchReport(run.run_id)
          if (!mounted.current || mine !== seq.current) return
          setReport(rep); setReportError(null)
        } catch (e) {
          if (!mounted.current || mine !== seq.current) return
          setReport(null); setReportError(e instanceof Error ? e.message : String(e))
        }
      } else { setReport(null); setReportError(null) }
    } catch (e) {
      if (mounted.current && mine === seq.current) setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (mine === seq.current) inflight.current = false
    }
  }, [caseId, deptView])

  useEffect(() => { load() }, [load])
  // A first load that failed is tried again on its own every 10 s, and at once on Retry (F12).
  useEffect(() => {
    if (c || !error) return
    const t = setTimeout(load, 10_000)
    return () => clearTimeout(t)
  }, [c, error, load])
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
    const tick = () => { if (document.visibilityState === 'visible' && !inflight.current) load() }
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
      // Only a complete answer goes on screen before the reload: one without the moves blanked the page (9 Oct 2026).
      if (answer?.case && answer.case.id === caseId && Array.isArray(answer.case.allowed_actions)) setC(answer.case)
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

  // Replacing a paper is confirmed first (F14): the old one stays on file but is no longer read.
  const [pendingReplace, setPendingReplace] = useState<{ doc: { id: string; filename: string }; file: File } | null>(null)
  async function doReplace(docId: string, file: File) {
    setBusy(true); setError(null)
    try { await replaceDocument(caseId, docId, file); seq.current += 1; await load(); toast('Document replaced. Submit the case when ready.') }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); toast('Could not replace the document', 'bad') }
    finally { setBusy(false) }
  }

  const [holdRun, setHoldRun] = useState<string | null>(null)
  const latestRunId = c?.latest_run?.run_id ?? null
  // Only a pension run is held: holdRun exists to keep AnalysisLive on screen until its bar
  // has visibly finished, and AnalysisLive is drawn for a pension case alone. A GP Fund run
  // was held too and nothing could let go of it -- the component that calls analysisDone is
  // never rendered for GPF, and its run id 404s on the pension run endpoints by design
  // (api/v2._run_for: "a GP Fund examination has no pension artefacts"). So after examining a
  // claim the actions never came back, and a reload -- which starts holdRun at null -- was the
  // only way to see them again (23 Oct 2026).
  useEffect(() => {
    if (c?.status === 'AI_CHECKING' && latestRunId && c.product !== 'GPF') setHoldRun(latestRunId)
  }, [c?.status, c?.product, latestRunId])
  const analysisDone = useCallback(() => { setHoldRun(null); load() }, [load])

  const step = useMemo(() => c ? nextStep(c, role) : null, [c, role])

  if (!c || !step) {
    return (
      <div className="screen container" style={{ paddingTop: 22 }}>
        <button className="back" onClick={() => onBack('PENSION')}>Back to the register</button>
        {error ? (
          <div className="banner bad" role="alert" style={{ marginTop: 12 }}><span className="mark">!</span>
            <div className="sub">Could not load the case. {error} <button type="button" style={{ marginLeft: 8 }} onClick={() => load()}>Retry</button>
              <span className="muted" style={{ marginLeft: 8, fontSize: 'var(--t-small)' }}>Trying again on its own every 10 seconds.</span></div>
          </div>
        ) : <div className="skeleton" style={{ height: 120, marginTop: 12 }} />}
      </div>
    )
  }

  const run = c.latest_run
  const m = STATUS_META[c.status]
  const hasIssues = run ? (run.verdict !== 'FORWARD' || (run.high_flags ?? 0) > 0 || (run.blocking_flags ?? []).length > 0) : true
  const deptSide = deptView                       // the administrator acts on no side (G6)
  // The server answers this, not the role: findings are acted on while the case is under review,
  // on its current examination, by the tier that holds it (the AG desk and the Deputy AG at any
  // tier). Deciding it from the role capability alone offered Waive and Uphold to every AG
  // account and 409'd all but the holder (audit 13 Oct 2026, M-12).
  const canReview = !!c.may_dispose
  // The documents the AG's return asked for, for this round (AUTO_RETURN / GPF_RETURN: rows from before 9 Oct 2026,
  // when the system still returned cases by itself).
  const sentBack = m.side === 'department' ? [...c.events].reverse().find(e => ['AUTO_RETURN', 'GPF_RETURN', 'RETURN', 'REQUEST_DOCS'].includes(e.action)) : undefined
  const missingDocs = returnedItems(sentBack?.payload)
  const agRemarks = c.events.filter(e => (isAgReader(e.actor_role ?? '') || e.actor_role === 'ADMIN') && e.remark && e.action !== 'CREATE' && e.action !== 'FORWARD')
  const lastAg = agRemarks[agRemarks.length - 1]
  // Who has signed the case off so far, tier by tier (9 Oct 2026): the DDO's history carries no tier moves.
  const approvals = c.events.filter(e => (e.action === 'FORWARD_TIER' && (e.actor_role === 'AG_SENIOR_AUDITOR' || e.actor_role === 'AG_ASSISTANT_AO'))
    || ((e.action === 'APPROVE' || e.action === 'REJECT') && e.actor_role === 'AG_AO'))
    .map(e => `${e.action === 'FORWARD_TIER' ? (e.actor_role === 'AG_SENIOR_AUDITOR' ? 'Verified' : 'Approved') : e.action === 'APPROVE' ? 'Approved (final)' : 'Rejected (final)'} by ${e.actor_name ?? e.actor_role}, ${fmtDateTime(e.at)}`)
  // The tab's count is the number of findings listed under it, the same as the Flags tab inside.
  const findings = report?.flags.length ?? 0
  const findingsHot = !!report?.flags.some(f => f.severity === 'HIGH')
  // The analysis stays on screen until it has shown its own finish (the bar at 100%, then on
  // to the findings), not cut off the moment the poll sees the case move on.
  const verifying = c.status === 'AI_CHECKING'
    || (c.product !== 'GPF' && !!run && holdRun === run.run_id && c.status !== 'AI_FAILED')
  const remarks = c.events.filter(e => e.remark && e.actor_role !== 'SYSTEM').length

  // Left/Right on the tab strip move between the tabs (F15); a department has no AI tab.
  const tabKeys = (e: React.KeyboardEvent) => {
    const order = TABS.filter(t => !(deptView && t === 'AI findings'))
    const n = nextTabFor(order, tab, e.key)
    if (n) { e.preventDefault(); setTab(n); (document.getElementById(tabId('case-tab', n)) as HTMLElement | null)?.focus() }
  }

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
        <button className="back" onClick={() => onBack(c.product)}>Back to the register</button>
        <h1 style={{ margin: 0 }}>{c.product === 'GPF' ? 'GP Fund case' : 'Case'} <span className="mono">{c.case_no}</span></h1>
        <StatusPill status={c.status} />
      </div>
      <p className="lead" style={{ marginTop: 4 }}>
        <strong>{c.claimant_name ?? (c.product === 'GPF' ? 'Subscriber name not yet read' : 'Claimant name not yet extracted')}</strong>
        {c.product === 'GPF' && c.intake?.gpf_kind ? ` · ${gpfKindLabel(String(c.intake.gpf_kind))}` : ''}
        {c.product !== 'GPF' && c.case_type && <> · <span title={CASE_TYPE_SOURCE_WORDS[c.case_type_source ?? ''] ?? ''}>{caseTypeLabel(c.case_type)}{c.case_type_source === 'DETECTED' ? ' (detected)' : ''}</span></>}
        {' · '}{c.department_name}
        {c.holder_label && <> · <span className="muted" title="Who holds the case now">{c.holder_label}</span></>}
      </p>

      {approvals.length > 0 && <p className="muted" style={{ marginTop: 4, fontSize: 'var(--t-small)' }} aria-label="Approvals so far">{approvals.join(' · ')}</p>}

      <CaseProgress status={c.status} holderTier={c.holder_tier} />

      {/* What to do now -- unless the step says the actions rail already shows it (api/cases.ts). */}
      {!step.quiet && (
      <div className={`next${bannerTone}`}>
        <div className="next-body">
          <p className="next-title">{step.title}</p>
          <p className="next-text">{step.text}</p>
          {lastAg && deptSide && (c.status === 'RETURNED' || c.status === 'DOCS_REQUESTED' || c.status === 'REJECTED') && (
            <p className="next-text" style={{ marginTop: 8, color: 'var(--ink)' }}>
              <strong>Remarks of the Office of the Accountant General:</strong> “{lastAg.remark}” <span className="muted">— {lastAg.actor_name}, {fmtDateTime(lastAg.at)}</span>
            </p>
          )}
          {missingDocs.length > 0 && (
            <div style={{ marginTop: 8, color: 'var(--ink)' }}>
              <strong>Documents to attach{sentBack?.action === 'AUTO_RETURN' ? ' (found missing by the verification)' : ''}:</strong>
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {missingDocs.map((d, i) => (
                  <li key={`${d.id ?? d.label ?? ''}${i}`}>
                    {d.id ? <><strong>{d.id}</strong> {d.requirement}</> : <>{d.label}{d.pages?.length ? ` — page ${d.pages.join(', ')}` : ''}</>}
                    {d.status === 'DEFECTIVE' ? ' — the copy attached is defective' : ''}
                    {d.note ? <> — {d.note}</> : null}
                  </li>
                ))}
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
      )}

      {error && <div className="banner bad" role="alert" style={{ marginTop: 'var(--s3)' }}><span className="mark">!</span><div className="sub">{error}</div></div>}
      {pendingReplace && (
        <div className="banner warn" role="alertdialog" aria-label="Confirm the replacement" style={{ marginTop: 'var(--s3)' }}>
          <span className="mark" aria-hidden="true">!</span>
          <div className="sub">
            Replace <strong>{pendingReplace.doc.filename}</strong> with <strong>{pendingReplace.file.name}</strong>? The earlier paper stays on file, marked replaced, and is no longer read.
            <div className="row" style={{ gap: 8, marginTop: 8 }}>
              <button className="primary" disabled={busy} onClick={() => { const r = pendingReplace; setPendingReplace(null); doReplace(r.doc.id, r.file) }}>Replace the document</button>
              <button disabled={busy} onClick={() => setPendingReplace(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* For the AG: what the department wrote when it resubmitted. */}
      {c.officer_remark && !deptSide && m.side === 'ag' && (
        <div className="banner" style={{ marginTop: 'var(--s3)' }}>
          <span className="mark" aria-hidden="true" style={{ background: 'var(--green3)' }} />
          <div><div className="sub"><strong>Remarks of the submitting officer:</strong> “{c.officer_remark}”</div></div>
        </div>
      )}

      <div className="detail-grid">
        <div style={{ minWidth: 0 }}>
          <div className="tabs" role="tablist" onKeyDown={tabKeys}>
            <button className="tab" role="tab" id={tabId('case-tab', 'Documents')} aria-controls={tabId('case-panel', 'Documents')} tabIndex={tab === 'Documents' ? 0 : -1}
                    aria-selected={tab === 'Documents'} onClick={() => setTab('Documents')}>
              Documents <span className="count">{c.documents.length}</span>
            </button>
            {!deptView && (
              <button className="tab" role="tab" id={tabId('case-tab', 'AI findings')} aria-controls={tabId('case-panel', 'AI findings')} tabIndex={tab === 'AI findings' ? 0 : -1}
                      aria-selected={tab === 'AI findings'} onClick={() => setTab('AI findings')}>
                {c.product === 'GPF' ? 'GP Fund examination' : 'AI findings'} {report && <span className={`count${findingsHot ? ' hot' : ''}`}>{findings}</span>}
              </button>
            )}
            <button className="tab" role="tab" id={tabId('case-tab', 'Remarks & history')} aria-controls={tabId('case-panel', 'Remarks & history')} tabIndex={tab === 'Remarks & history' ? 0 : -1}
                    aria-selected={tab === 'Remarks & history'} onClick={() => setTab('Remarks & history')}>
              Remarks and history <span className="count">{remarks}</span>
            </button>
          </div>

          {tab === 'Documents' && (
            <div className="card" role="tabpanel" id={tabId('case-panel', 'Documents')} aria-labelledby={tabId('case-tab', 'Documents')} style={{ marginTop: 'var(--s4)' }}>
              <DocumentList caseId={c.id} documents={c.documents} currentSubmission={c.submission_no} busy={busy}
                            onReplace={c.allowed_actions.includes('ADD_DOCS') ? (d, f) => setPendingReplace({ doc: d, file: f }) : undefined} />
              {c.allowed_actions.includes('ADD_DOCS') && (
                <div className="row" style={{ gap: 12, marginTop: 'var(--s4)', alignItems: 'center' }}>
                  <button onClick={() => fileInput.current?.click()} disabled={busy}>Add documents</button>
                  <span className="help">After attaching the documents, submit the case to the Office of the Accountant General.</span>
                </div>
              )}
            </div>
          )}

          {tab === 'AI findings' && !deptView && c.product === 'GPF' && (
            <div role="tabpanel" id={tabId('case-panel', 'AI findings')} aria-labelledby={tabId('case-tab', 'AI findings')}>
              <GpfExamination c={c} busy={busy} onVerify={doCheck} onChanged={load} offerVerify={step.action !== 'RUN_CHECK'} />
            </div>
          )}

          {tab === 'AI findings' && !deptView && c.product !== 'GPF' && (
            <div role="tabpanel" id={tabId('case-panel', 'AI findings')} aria-labelledby={tabId('case-tab', 'AI findings')} style={{ marginTop: 'var(--s4)' }}>
              {!verifying && c.submission_no > 1 && (
                <div style={{ marginBottom: 'var(--s4)' }}>
                  <RoundsPanel caseId={c.id} refreshKey={`${c.updated_at}${run?.state}`} onlyLatest agView />
                </div>
              )}
              {verifying && run && <AnalysisLive runId={run.run_id} onDone={analysisDone} />}
              {!verifying && report && run && (
                <CaseFindings report={report} runId={run.run_id} canDispose={canReview} onSettled={load} />
              )}
              {!verifying && !report && reportError && (
                <div className="card">
                  <div className="empty" role="alert">
                    <strong>Could not load the findings.</strong>
                    <div className="help" style={{ marginTop: 6 }}>{reportError}</div>
                    <div style={{ marginTop: 'var(--s3)' }}><button className="primary" onClick={() => load()} disabled={busy}>Retry</button></div>
                    <div className="help" style={{ marginTop: 6 }}>The case was verified; only the reading of its findings failed just now. No re-verification is needed.</div>
                  </div>
                </div>
              )}
              {!verifying && !report && !reportError && (
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
            <div className="card" role="tabpanel" id={tabId('case-panel', 'Remarks & history')} aria-labelledby={tabId('case-tab', 'Remarks & history')} style={{ marginTop: 'var(--s4)' }}>
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
          {/* Nothing to decide while the examination is still on screen (23 Oct 2026).
              The run finishes a few seconds before the analysis does: the server moves the
              case to UNDER_REVIEW the moment the pipeline ends, the case reloads with
              approve/return/reject in allowed_actions, and the rail drew them beside a bar
              still climbing and a LIVE pill. An officer was offered a decision on findings
              the screen had not finished showing them. `verifying` is what holds the analysis
              up (it stays true until the bar reaches the end), so it holds the actions back
              with it, and they appear together with the findings. */}
          {!verifying && <>
          <ActionPanel actions={c.allowed_actions} hasIssues={hasIssues} busy={busy} onAct={doAct} status={c.status} holderTier={c.holder_tier}
                       checklist={(report?.checklist?.items ?? []).map(i => ({ id: i.id, requirement: i.requirement, status: i.status }))}
                       open={pendingAction} onOpenChange={setPendingAction} />
          {canReview && m.side === 'ag' && !c.allowed_actions.some(a => PANEL_ACTIONS.includes(a)) && (
            <div className="card">
              <div className="label" style={{ marginBottom: 6 }}>What you can do</div>
              <div className="help">Approve, reject, return and request-documents open once the AI examination of these papers has completed.</div>
            </div>
          )}
          </>}
          {c.allowed_actions.includes('RUN_CHECK') && !verifying && step.action !== 'RUN_CHECK' && (
            <div className="card">
              <div className="label" style={{ marginBottom: 8 }}>Verification</div>
              <button onClick={doCheck} disabled={busy} style={{ width: '100%' }}>{c.product === 'GPF' ? 'Examine the claim again' : 'Verify the case again'}</button>
              <div className="help" style={{ marginTop: 8 }}>Reads the documents afresh; the outcome moves the case again.</div>
            </div>
          )}
          {/* Only where it can be acted on (22 Oct 2026): the department, while the case is on
              its side. An officer saw a card that read "Case type / Fresh - Self / Declared by
              the DDO" and could do nothing with it, and the same words are in the line under
              the case number and again in the Summary. The panel is a control, so it is drawn
              for the person holding the control and for nobody else. */}
          {c.product !== 'GPF' && deptView && ['DRAFT', 'AI_CHECKED', 'RETURNED', 'DOCS_REQUESTED'].includes(c.status) && (
            <CaseTypePanel c={c} busy={busy}
                           onSet={async body => { setBusy(true); try { await setCaseType(caseId, body); seq.current += 1; await load(); toast('Case type recorded.') } finally { setBusy(false) } }} />
          )}
          {/* The "Case particulars" card stood here and is gone (22 Oct 2026). Every line of it
              was already on the screen: the case type on the panel above it and in the line
              under the case number, the pension section beside the department on the register
              row that opened the case, and when it was filed, when it last moved, which
              submission this is and how many times it has been verified -- all of it in
              Remarks and history, which is the tab that holds the case's dates and is the
              record. A second, shorter copy in the corner is a second thing to keep true. */}
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
  const [signError, setSignError] = useState<string | null>(null)
  const [signTry, setSignTry] = useState(0)
  const [frameKey, setFrameKey] = useState(0)
  const frame = useRef<HTMLIFrameElement>(null)
  const reading = c.status === 'AI_CHECKING'
  const hasFrame = !!state?.embed_url
  useMediaTokenVersion()                                  // the page being read carries the media token (F10)
  // The framed module is behind the portal's sign-in (5 Oct 2026): a frame cannot carry the
  // session token, so the server sets a GP-Fund-only cookie first, renewed well inside its 2 hours.
  // A failed sign-in says so and offers Retry (F12) instead of "Opening…" for ever.
  useEffect(() => {
    if (!hasFrame) return
    let live = true
    const sign = () => post('/api/v2/auth/gpf-session')
      .then(() => { if (live) { setFrameSigned(true); setSignError(null) } })
      .catch(e => { if (live) { setFrameSigned(false); setSignError(e instanceof Error ? e.message : String(e)) } })
    sign()
    const renew = window.setInterval(sign, 90 * 60_000)
    return () => { live = false; window.clearInterval(renew) }
  }, [hasFrame, signTry])
  // The frame says its own sign-in lapsed (auth/frameActivity.ts): sign it again and reload it.
  useEffect(() => onGpfExpired(() => { setFrameSigned(false); setSignTry(n => n + 1); setFrameKey(k => k + 1) }), [])
  // The frame's window is registered while it is on screen, so its activity counts (F9).
  useEffect(() => {
    if (!frameSigned) return
    return registerGpfFrame(frame.current?.contentWindow)
  }, [frameSigned, frameKey])
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
    // One request at a time, the next scheduled only when the last has answered (F12): a fixed
    // 1.5 s interval on a slow link piled requests up and showed answers out of order.
    let live = true, timer: ReturnType<typeof setTimeout> | null = null, n = 0
    const tick = () => {
      const mine = ++n
      gpfState(c.id)
        .then(s => { if (!live || mine !== n) return; setState(s); setError(null); if (s.status !== c.status) onChanged() })
        .catch(e => { if (live && mine === n) setError(e instanceof Error ? e.message : String(e)) })
        // While the module reads, the job's page count is the progress; afterwards, a slow poll
        // follows the officer's disposal in the frame back onto the case.
        .finally(() => { if (live) timer = setTimeout(tick, reading ? 1500 : 8000) })
    }
    tick()
    return () => { live = false; if (timer) clearTimeout(timer) }
  }, [c.id, c.status, reading])   // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !state) return <div className="banner bad" role="alert" style={{ marginTop: 'var(--s4)' }}><span className="mark">!</span><div className="sub">Could not reach the GP Fund examination. {error} <span className="muted">Trying again…</span></div></div>
  if (!state) return <div className="skeleton" style={{ height: 120, marginTop: 'var(--s4)' }} />
  if (!state.module_up && !state.gpf_case_id) {
    return <div className="banner warn" style={{ marginTop: 'var(--s4)' }}><span className="mark">!</span><div className="sub">The GP Fund module is not running. Start it on the server (<code>./GP/run.sh</code>) and try again.</div></div>
  }
  if (reading || (state.job && !state.gpf_case_id)) {
    const j = state.job
    // Two numbers, because pages are read four at a time (GPF_READ_CONCURRENCY): `done` is
    // what is finished and `inFlight` what is with the model now. A bar drawn from `done`
    // alone sits at nothing while four pages work and then jumps by four, which reads as
    // stuck — so the solid part is what is finished and the pale part is what is under way.
    const pct = j && j.total ? Math.round(((j.done ?? 0) / j.total) * 100) : 0
    const underway = j && j.total
      ? Math.min(100, Math.round((((j.done ?? 0) + (j.inFlight ?? 0)) / j.total) * 100))
      : 0
    // The same scanning view as the pension analysis (shared/scan/ScanViewer), in GP Fund's gold,
    // on the page the module is reading, under the module's own stage names.
    const pg = j?.page ?? (j && j.total ? Math.min(j.total, (j.done ?? 0) + 1) : null)
    const stageWord = GPF_STAGE[j?.stage ?? ''] ?? 'Reading the claim'
    return (
      <div className="card gpf-progress" style={{ marginTop: 'var(--s4)' }}>
        <div style={{ fontWeight: 600, fontSize: 16 }}>{j?.state === 'error' ? 'The examination could not read the pages' : 'Reading the claim…'}</div>
        <div className="muted">{j?.detail ?? j?.message ?? 'The module classifies each page and extracts its fields; a page takes 5 to 15 seconds.'}</div>
        <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
          <span className="ahead" style={{ width: `${underway}%` }} />
          <span style={{ width: `${pct}%` }} />
        </div>
        {j && j.total ? (
          <div className="muted gpf-progress-line" style={{ fontSize: 'var(--t-small)' }}>
            <span>
              {j.done ?? 0} of {j.total} pages
              {(j.inFlight ?? 0) > 0 ? ` · ${j.inFlight} being read` : ''}
              {j.stage ? ` · ${stageWord}` : ''}
            </span>
            {/* Served by the module rather than timed in the browser, so a clock skew between
                machines cannot show a negative timer (reading/jobs.py Job.view). */}
            {j.elapsed != null ? <span className="mono muted">{mmss(j.elapsed)} elapsed</span> : null}
          </div>
        ) : null}
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
  return (
    <div style={{ marginTop: 'var(--s4)' }}>
      <div className="row" style={{ gap: 12, marginBottom: 10, alignItems: 'baseline' }}>
        {/* The counts stood here too -- "0 hard stops · 3 to verify · 0 SAP items · 2
            observations" -- directly above a frame whose own first row is those same figures,
            larger and with the satisfied checks as well (23 Oct 2026). Two tallies of one
            examination a centimetre apart, and the one here went on counting SAP items after
            the module's stopped. What is left is the only thing this line can say that the
            frame cannot: which of the module's cases is open in it. */}
        <span className="muted" style={{ fontSize: 'var(--t-small)' }}>
          GP Fund module · case <span className="mono">{state.gpf_case_id}</span>
        </span>
        {/* No "Open in the module" (removed 5 Oct 2026): the module's full page shows every GP Fund
            case and its own intake, outside the portal's register and workflow. The frame is the way in. */}
      </div>
      {frameSigned
        ? <iframe key={frameKey} ref={frame} className="gpf-frame" src={state.embed_url} title="GP Fund examination" style={{ height: frameHeight }} />
        : signError
          ? <div className="banner bad" role="alert"><span className="mark">!</span>
              <div className="sub">Could not open the GP Fund module. {signError} <button type="button" style={{ marginLeft: 8 }} onClick={() => setSignTry(n => n + 1)}>Retry</button></div></div>
          : <div className="card"><div className="skeleton" style={{ height: 120 }} /><div className="muted" style={{ marginTop: 8 }}>Opening the GP Fund module…</div></div>}
    </div>
  )
}
