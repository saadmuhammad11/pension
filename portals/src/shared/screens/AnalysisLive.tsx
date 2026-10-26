/** Screen 2 — AI Analysis. BUILD §9.5.
 *
 * Streams the REAL pipeline over server-sent events: nothing here is replayed or invented. Three
 * things, kept plain on purpose: the bar, the page the vision model is working on (with the name
 * of the document it found there), and the technical log.
 *
 * The bar never jumps. It is driven by real progress -- page 7 of 15 is 7/15 of the reading
 * stage, document 3 of 8 of the cross-checking -- eases forward between two events, never past
 * the start of a stage that has not started, and never goes backwards. It moves a bounded step
 * a second, so a stage that ends early is caught up over seconds, not in one leap, and once the
 * run is done it climbs to the end before the findings open. The arithmetic is analysisBar.ts.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { pageImageUrl, runStatus, subscribe, type RunEvent } from '../api'
import { ScanViewer } from '../scan/ScanViewer'
import { mmss } from '../fmt'
import { documentLabel } from '../labels'
import { useMediaTokenVersion } from '../auth/useMediaToken'
import { FULL, STAGES, barTarget, nextShown, stageOf } from './analysisBar'

/** In words, what each stage is doing -- rotated while it runs. Each line is true of the stage. */
const NOW: Record<number, string[]> = {
  0: ['Separating the bundle into pages and checking each scan is legible',
      'Fingerprinting the file, so every finding can be traced back to this exact copy'],
  1: ['Reading each page and deciding which document it is',
      'Telling a CNIC from a family certificate, a pay slip from a sanction form',
      'Grouping pages that belong to one document'],
  2: ['Reading the prescribed form a second time with a separate OCR model',
      'Deciding what kind of pension case this is from the sanction form'],
  3: ['Reading pay, dates and service off the sanction form — every figure read twice',
      'Separating reckonable pay from allowances that do not count for pension'],
  4: ['Collecting each fact from every document that states it',
      'Comparing the CNIC, personnel number and names across the whole file',
      'Checking the family on Annex-A against the NADRA family certificate',
      'Looking for recoveries the sanction form does not declare'],
  5: ['Reading who signed the sanction, and the stamp beside it',
      'Checking the signing officer against the specimen the department sent'],
  6: ['Applying the office checklist and the rules to what was read',
      'Writing up the findings, the checklist and the recommendation'],
}

const PAGES_IN = /^(\d+) source pages/
const PAGE_DONE = /^p\.\s*(\d+)\s+([A-Z][A-Z0-9_]+)\s+([\d.]+)/
const DOCS_FOUND = /^(\d+) documents assembled/
/** "stage 6  NADRA_FRC p.6", "stage 4  reading Form D-II p.4 (double read)", "signature  FORM_B_I p.4" */
const WORK_ON = /(?:stage \d+\s+(?:reading\s+)?|signature\s+|form text\s+)([A-Za-z][\w -]*?)\s+p\.\s*(\d+)/

/** What each later stage is doing to the page it has open, for the label on the viewer. */
const VERB: Record<number, string> = { 2: 'Second reading', 3: 'Reading the details', 4: 'Cross-checking', 5: 'Checking the signature' }

/** How many log lines the screen keeps (F16). */

const shortName = (t: string) => documentLabel(t).split(' — ')[0]

export function AnalysisLive({ runId, onDone }: { runId: string; onDone: () => void }) {
  const [events, setEvents] = useState<RunEvent[]>([])
  const [finished, setFinished] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [shown, setShown] = useState(0)            // the percentage on screen
  // The run's own start, from the server -- never the moment this screen opened. A screen
  // reopened, refreshed or navigated back to mid-run resumes where the run really is.
  const startedAt = useRef(Date.now())
  const [, setStartKnown] = useState(false)
  const mountedAt = useRef(Date.now())
  useMediaTokenVersion()                                  // page addresses carry the media token (F10)

  useEffect(() => {
    runStatus(runId).then(st => {
      const t = Date.parse(st.started_at)
      if (t && t < startedAt.current) { startedAt.current = t; setStartKnown(true) }
      if (st.state === 'done' || st.state === 'failed') setFinished(st.state)
    }).catch(() => { /* the stream below still carries the run */ })
    const stop = subscribe(
      runId,
      e => setEvents(prev => {
        if (prev.some(p => p.seq === e.seq)) return prev              // a reconnect replays what we have
        // The event's own moment (ts, ISO). `at` is a time of day the browser cannot place,
        // and stamping the replayed backlog "now" is what sent a reopened analysis back to 0.
        const t = Date.parse(e.ts ?? '') || Date.now()
        if (t < startedAt.current) startedAt.current = t
        return [...prev, { ...e, _t: t } as RunEvent]
      }),
      state => setFinished(state),
    )
    return stop
  }, [runId, onDone])

  // The clock: once a second (F16; it was four times a second, and every tick re-rendered the
  // whole screen for ten to twenty minutes on an old office PC). It keeps ticking after the run
  // is done until the bar has reached the end: the bar moves a bounded step per tick, and when
  // the clock stopped with the run, the bar froze wherever it was -- in the seventies, after
  // the long cross-checking stage -- and the findings appeared out of nowhere 12 s later.
  const barFull = shown >= FULL
  useEffect(() => {
    if (finished && (barFull || finished !== 'done')) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [finished, barFull])

  // On to the findings only once the bar has visibly reached the end (or, at the latest, 12 s
  // after the run did): leaving at 90% reads as the screen giving up, not the work finishing.
  useEffect(() => {
    if (!finished) return
    const t = setTimeout(onDone, finished !== 'done' ? 1500 : barFull ? 900 : 12000)
    return () => clearTimeout(t)
  }, [finished, barFull, onDone])

  // -- what the stream has said, as facts -----------------------------------------------------
  const facts = useMemo(() => {
    let stage = 0, totalPages = 0, docs = 0, facts6 = 0, extracts = 0
    let stageAt = startedAt.current, lastEventAt = startedAt.current, stageStepAt = startedAt.current
    const placed: Record<number, { type: string; conf: number }> = {}
    let lastPage: number | null = null, lastPageAt = startedAt.current
    //: What a later stage is working on: "stage 6  NADRA_FRC p.6" -> page 6, NADRA_FRC.
    let work: { page: number; doc: string; stage: number } | null = null
    for (const e of events) {
      const t = (e as RunEvent & { _t?: number })._t ?? Date.now()
      lastEventAt = t
      const s = stageOf(e.stage)
      if (s > stage) { stage = s; stageAt = t; stageStepAt = t }
      if (['extract', 'assertions', 'signatures', 'verify'].includes(e.stage)) {
        const w = WORK_ON.exec(e.message)
        if (w) { work = { page: Number(w[2]), doc: w[1], stage: s }; stageStepAt = t }
      }
      const pages = PAGES_IN.exec(e.message); if (pages) totalPages = Number(pages[1])
      if (e.stage === 'identify') {
        const m = PAGE_DONE.exec(e.message)
        // Pages finish out of order (four are read at once); the view follows the furthest page
        // read, so it only ever moves forward.
        if (m) { placed[Number(m[1])] = { type: m[2], conf: Number(m[3]) }; lastPage = Math.max(lastPage ?? 0, Number(m[1])); lastPageAt = t }
      }
      const d = DOCS_FOUND.exec(e.message); if (d) docs = Number(d[1])
      if (e.stage === 'assertions' && /^stage 6/.test(e.message)) facts6++
      if (e.stage === 'extract' && /^stage 4/.test(e.message)) extracts++
    }
    return { stage, stageAt, stageStepAt, lastEventAt, totalPages, placed, lastPage, lastPageAt, docs, facts6, extracts, work }
  }, [events])

  // -- where the bar should be now ------------------------------------------------------------
  const target = useMemo(() => barTarget(facts, now, finished), [facts, now, finished])

  // Toward the target: never backwards, a bounded step a second -- when a stage ends sooner than
  // its share of the bar, the bar catches up over several seconds instead of leaping 20% at once.
  // The glide between two values is the CSS transition on the fill (F16), not a frame loop: one
  // state change a second, no requestAnimationFrame re-rendering the screen. On opening, a screen
  // opened mid-run takes the run's real position at once rather than climbing from zero. The
  // step is taken on every tick of the clock, not only when the target moves: once the run is
  // done the target is 100 and stays there, and the bar still has to get there.
  const hasEvents = events.length > 0
  useEffect(() => {
    setShown(v => {
      if (target - v > 0.01 && Date.now() - mountedAt.current < 2500 && hasEvents) return target
      return nextShown(v, target, finished)
    })
  }, [target, hasEvents, finished, now])

  const elapsed = (now - startedAt.current) / 1000
  const pct = Math.floor(shown)
  const lines = NOW[Math.min(facts.stage, 6)]
  const line = lines[Math.floor(elapsed / 6) % lines.length]
  // After the pages are read, the viewer follows whatever page the later stages have open.
  const working = facts.work && facts.work.stage >= 2 && facts.stage >= 2 ? facts.work : null
  // Page 1 until the model names a page: the scan is under way the moment the pages exist.
  const targetPage = working?.page ?? facts.lastPage ?? (facts.totalPages > 0 ? 1 : null)
  // The page on screen walks toward the one being worked on, one page at a time while the pages
  // are read, and never faster than one change every ~0.9 s: a steady scan, not a flicker.
  const [page, setPage] = useState<number | null>(null)
  useEffect(() => {
    if (targetPage === null || targetPage === page) return
    const walking = !working && page !== null && targetPage > page && targetPage - page <= 40
    const t = setTimeout(() => setPage(p => walking && p !== null ? p + 1 : targetPage), page === null ? 0 : 900)
    return () => clearTimeout(t)
  }, [targetPage, page, working])
  const quiet = (now - facts.lastEventAt) / 1000
  // The log on screen is the last 300 lines (F16); the facts above are drawn from all of them.
  const workDoc = !working ? '' : /^[A-Z0-9_]+$/.test(working.doc) ? shortName(working.doc) : working.doc
  const slowLine = !finished && quiet > 45 && working
    ? `Still on ${workDoc} (p.${working.page}) — a dense page can take a minute or two. Last update ${mmss(quiet)} ago.`
    : null

  return (
    <div className="screen container" style={{ paddingTop: 22 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ margin: '0 0 4px' }}>AI Analysis</h2>
        <span className="mono muted" style={{ fontSize: 12 }}>run {runId}</span>
        {!finished && <span className="pill medium an-live">LIVE</span>}
        {finished === 'done' && <span className="pill low">COMPLETE</span>}
        {finished === 'failed' && <span className="pill high">FAILED</span>}
        <span style={{ flex: 1 }} />
        <span className="mono muted" style={{ fontSize: 12 }}>
          {mmss(elapsed)} elapsed
        </span>
      </div>

      {/* The bar. role="progressbar" as Upload and CaseDetail already carry it: a reader that
          cannot see this screen was told nothing at all for the three minutes it runs. */}
      <div className="an-bar-wrap">
        <div className="an-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100}
             aria-valuenow={pct} aria-label="Analysis progress">
          <div className={`an-fill${finished ? '' : ' is-live'}`} style={{ width: `${shown}%`, transition: 'width 1s linear' }} />
        </div>
        <span className="an-pct">{pct}%</span>
      </div>
      {/* The live region is the WRAPPER, not the line: `key` remounts the line to restart its
          animation, and a live region that is replaced rather than changed is not announced. */}
      <div aria-live="polite" aria-atomic="true">
        <div className="an-now" key={slowLine ? 'slow' : line}>
          <span className="an-dot" aria-hidden="true" />
          {finished === 'done' ? 'Analysis complete — opening the findings…'
            : finished === 'failed' ? 'The analysis stopped. The technical log below says where.'
            : line}
        </div>
      </div>

      <div className="an-grid">
      {/* The page being read: the shared scanning view (shared/scan/ScanViewer). */}
      <div className="an-viewer-slot">
        <ScanViewer
          src={page === null ? null : pageImageUrl(runId, page)}
          pageKey={page}
          state={finished === 'done' ? 'done' : finished === 'failed' ? 'failed' : 'live'}
          label={page === null ? null
            : working && !finished ? `${VERB[working.stage] ?? 'Working on'} · ${workDoc}`
            : facts.placed[page] ? shortName(facts.placed[page].type) : null}
          caption={[page === null ? 'Preparing the bundle' : `Page ${page}${facts.totalPages ? ` of ${facts.totalPages}` : ''}`,
                    STAGES[Math.min(facts.stage, STAGES.length - 1)][0]]}
          note={slowLine}
          waiting={facts.totalPages ? `Preparing ${facts.totalPages} pages…` : 'Separating the pages…'} />
      </div>

      {/* The stages, and which one is running. */}
      <div className="an-stages">
        {STAGES.map(([name, sub], i) => {
          const done = finished === 'done' || i < facts.stage
          const running = i === facts.stage && !finished
          return (
            <div key={name} className={`an-stage${running ? ' is-running' : ''}${done ? ' is-done' : ''}`}>
              <div className={`an-mark${running ? ' working' : ''}`}>{done ? '✓' : ''}</div>
              <div>
                <div className="an-stage-name">{name}</div>
                {running && <div className="an-stage-sub">{sub}</div>}
              </div>
            </div>
          )
        })}
      </div>
      </div>

      {/* The technical log stood here: three hundred lines of stage, timestamp and message,
          under a screen that already says which stage is running, which page is being read
          and how far along it is. It was the engineer's view of a run on an officer's screen
          (26 Oct 2026). The events still drive everything above -- the bar, the stage list
          and the page -- they are no longer printed. */}
    </div>
  )
}
