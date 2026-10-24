/** The register: the cases this user may see, sorted by what needs doing.
 *
 *  Four tiles at the top answer the first question of the day -- what is waiting on me, what
 *  is with the other side, what is finished, how many in all -- and each is a filter on the
 *  table below. Under the search box a filter bar narrows further (design of 28 Sep 2026):
 *  status chips, the department, the kind of pension. Rows carry a badge for the status, a
 *  badge for the AI result, the kind of case, how long it has waited where it is, and one
 *  action button with a verb on it. On a phone the rows are paged, twelve at a time.
 *
 *  With a `view`, the screen is split in two (28 Sep 2026): the dashboard (title, tiles,
 *  figures) and the cases (search, filters, rows), switched from the header; a tile opens the
 *  cases with that filter set. Without one, everything is on one page.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import type React from 'react'
import { nextTabFor } from '../components/tabs'
import { PRODUCT_SLUG, STATUS_META, gpfKindLabel, nextStep, type CaseStatus, type CaseSummary, type Product } from '../api/cases'
import { caseTypeLabel } from '../labels'
import { CASE_TYPE_SOURCE_WORDS } from '../caseTypes'
import { RowTimeline } from '../components/RowTimeline'
import { navigate } from '../router/hash'

const ago = (iso: string) => {
  const t = Date.parse(iso)
  if (!t) return '—'
  const mins = Math.round((Date.now() - t) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

type Bucket = 'mine' | 'theirs' | 'done' | 'all'

/** The verb on the row's button: what pressing it lets the officer do. */
const VERBS: Record<string, string> = {
  TAKE_UP: 'Take up', FORWARD: 'Submit', ADD_DOCS: 'Attach', RUN_CHECK: 'Verify',
}

/** The kind of case on a row: the declared (or detected) pension case type, or the GP Fund claim's kind. */
const kindOf = (r: CaseSummary) => r.product === 'GPF' ? (gpfKindLabel(String(r.intake?.gpf_kind ?? '')) || null) : (r.case_type ? caseTypeLabel(r.case_type) : null)
const kindKey = (r: CaseSummary) => r.product === 'GPF' ? String(r.intake?.gpf_kind ?? '') : (r.case_type ?? '')

/** Short status words for the row badge; the full wording is the badge's tooltip. */
const SHORT: Record<CaseStatus, string> = {
  DRAFT: 'Not yet submitted', AI_CHECKING: 'Verifying', AI_FAILED: 'Verification incomplete', AI_CHECKED: 'Not yet submitted',
  FORWARDED: 'Submitted', UNDER_REVIEW: 'Under review', APPROVED: 'Approved', REJECTED: 'Rejected',
  RETURNED: 'Returned', DOCS_REQUESTED: 'Documents requested',
}

/** The status chips: one colour, one meaning, the same as the badges. */
type Group = '' | 'awaiting' | 'pending' | 'returned' | 'approved' | 'rejected'
//: `ag: null` means the chip is a department's own and is not drawn on this side. A case not
//: yet submitted is the department's to finish and the AG has nothing to do with it; offering
//: the Office a filter for it was offering a filter on somebody else's work (24 Oct 2026).
//: Such a case is still counted and still listed under All -- only the chip has gone.
const GROUPS: { key: Group; dept: string; ag: string | null; statuses: CaseStatus[] }[] = [
  { key: 'awaiting', dept: 'With the AG', ag: 'Awaiting decision', statuses: ['FORWARDED', 'AI_CHECKING', 'AI_FAILED', 'UNDER_REVIEW'] },
  { key: 'pending', dept: 'Not yet submitted', ag: null, statuses: ['DRAFT', 'AI_CHECKED'] },
  { key: 'returned', dept: 'Returned', ag: 'Returned', statuses: ['RETURNED', 'DOCS_REQUESTED'] },
  { key: 'approved', dept: 'Approved', ag: 'Approved', statuses: ['APPROVED'] },
  { key: 'rejected', dept: 'Rejected', ag: 'Rejected', statuses: ['REJECTED'] },
]

/** Days an open case has waited where it is now: since its last movement, or since filing. */
function daysWaiting(r: CaseSummary): number | null {
  if (STATUS_META[r.status].side === 'closed') return null
  const since = Date.parse(r.last_event?.at ?? r.created_at)
  if (!since) return null
  return Math.max(0, Math.floor((Date.now() - since) / 86400000))
}
const slaTone = (days: number) => days > 7 ? 'over' : days > 3 ? 'warn' : 'ok'

/** Phones page the register twelve at a time; a desktop fifty (F16: a register of hundreds of
 *  rows re-rendered on every 3-second refresh was what made an old office PC crawl). */
function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const on = () => setNarrow(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return narrow
}
export const PAGE_NARROW = 12
//: Twenty a page on a full screen (24 Oct 2026, office decision). Fifty filled the screen
//: several times over and the pager below it was never reached.
export const PAGE_WIDE = 20
const BUCKETS: Bucket[] = ['mine', 'theirs', 'done', 'all']

export function CaseRegister(
  { product, rows, title, lead, waitingOn, onOpen, onNew, newLabel, showDepartment, error, stale, loading, role, charts, view,
    statusCounts, total }:
  { product: Product
    rows: CaseSummary[]
    /** Counts by status from the server (api/inventory.py): the tiles never count a partial list. */
    statusCounts?: Partial<Record<CaseStatus, number>>
    total?: number
    view?: 'dashboard' | 'cases'
    title: string
    lead: string
    /** Statuses that mean "waiting on this user". */
    waitingOn: CaseStatus[]
    onOpen: (id: string) => void
    onNew?: () => void
    newLabel?: string
    showDepartment?: boolean
    error?: string | null
    /** The rows are on screen but the last refresh failed: a quiet notice, retried on its own (F12). */
    stale?: boolean
    loading?: boolean
    role: string
    charts?: ReactNode },
) {
  // Every register opens on every case (30 Sep 2026 for a department, 24 Oct 2026 for the
  // Office): opening on a tile hid a case the moment it was filed, and on the AG's side it
  // opened an empty table whenever nothing happened to await a decision. A tile narrows the
  // register when the officer presses one, and says so while it does.
  const [bucket, setBucket] = useState<Bucket>('all')
  const [q, setQ] = useState('')
  const [group, setGroup] = useState<Group>('')
  const [kind, setKind] = useState('')
  const [dept, setDept] = useState('')
  const [section, setSection] = useState('')
  const [page, setPage] = useState(1)
  const narrow = useNarrow()
  const isDept = role === 'DEPT_OFFICER'
  const buckets = useMemo(() => {
    const mine = rows.filter(r => waitingOn.includes(r.status))
    const done = rows.filter(r => STATUS_META[r.status].side === 'closed')
    const theirs = rows.filter(r => !mine.includes(r) && !done.includes(r))
    return { mine, theirs, done, all: rows }
  }, [rows, waitingOn])
  // The tiles' numbers: from the server's counts where it gave them, else from the rows (a
  // caller that has only a list). Same statuses per tile either way.
  const tile = useMemo(() => {
    if (!statusCounts) return { mine: buckets.mine.length, theirs: buckets.theirs.length, done: buckets.done.length, all: rows.length }
    const sum = (pred: (s: CaseStatus) => boolean) => Object.entries(statusCounts).reduce((n, [s, v]) => n + (pred(s as CaseStatus) ? (v ?? 0) : 0), 0)
    const mine = sum(s => waitingOn.includes(s))
    const done = sum(s => !waitingOn.includes(s) && STATUS_META[s]?.side === 'closed')
    const all = total ?? sum(() => true)
    return { mine, done, theirs: all - mine - done, all }
  }, [statusCounts, total, buckets, rows.length, waitingOn])
  const kinds = useMemo(() => {
    const seen = new Map<string, string>()
    rows.forEach(r => { const k = kindKey(r); if (k && !seen.has(k)) seen.set(k, kindOf(r) ?? k) })
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]))
  }, [rows])
  const depts = useMemo(() => [...new Set(rows.map(r => r.department_name).filter(Boolean))].sort((a, b) => a.localeCompare(b)), [rows])
  const sections = useMemo(() => [...new Set(rows.map(r => r.pension_section ?? 'Legacy'))].sort((a, b) => a.localeCompare(b, 'en', { numeric: true })), [rows])
  // A tile is one of the filters, and is shown and cleared with them (24 Oct 2026). It used
  // to be neither: it narrowed the table from the other tab, and all the table said for
  // itself was "Awaiting decision · 27 of 46 · show all" in small print above it.
  const filtered = !!(group || kind || dept || section) || bucket !== 'all'
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const statuses = group ? GROUPS.find(g => g.key === group)!.statuses : null
    return buckets[bucket].filter(r =>
      (!statuses || statuses.includes(r.status))
      && (!kind || kindKey(r) === kind)
      && (!dept || r.department_name === dept)
      && (!section || (r.pension_section ?? 'Legacy') === section)
      && (!needle || [r.case_no, r.claimant_name, r.department_name, r.pension_section, STATUS_META[r.status].label, kindOf(r) ?? '', r.case_type ?? '']
                       .some(v => (v ?? '').toLowerCase().includes(needle))))
  }, [buckets, bucket, q, group, kind, dept, section])

  // A filter runs over the whole register, not the tile's slice, so the count it shows is true.
  const narrowTo = (set: () => void) => { set(); setBucket('all'); setPage(1) }
  const clear = () => { setGroup(''); setKind(''); setDept(''); setSection(''); setBucket('all'); setPage(1) }
  const pickBucket = (b: Bucket) => { setBucket(b); setPage(1); if (view) navigate(`/${PRODUCT_SLUG[product]}/cases`) }
  // One face or the other (screens/registerView.ts): the dashboard, or the cases. Until 12 Oct
  // 2026 a department's home drew the cases and then the dashboard below them.
  const showDash = view !== 'cases'
  const showCases = view !== 'dashboard'

  const PAGE = narrow ? PAGE_NARROW : PAGE_WIDE
  const pages = Math.max(1, Math.ceil(shown.length / PAGE))
  const current = Math.min(page, pages)
  const visible = shown.slice((current - 1) * PAGE, current * PAGE)
  // Left/Right on the tiles move between them (F15).
  const tileKeys = (e: React.KeyboardEvent) => { const n = nextTabFor(BUCKETS, bucket, e.key); if (n) { e.preventDefault(); pickBucket(n); (e.currentTarget.querySelector(`[data-bucket="${n}"]`) as HTMLElement | null)?.focus() } }

  const theirsLabel = isDept ? 'With the Office of the Accountant General' : 'With the departments'
  const theirsDesc = isDept ? 'Submitted; awaiting the Pension Wing.' : 'Not yet submitted, or returned for correction.'
  const bucketLabel: Record<Bucket, string> = { mine: isDept ? 'Action required' : 'Awaiting decision', theirs: theirsLabel, done: 'Disposed', all: 'All cases' }
  const showAi = !isDept                                   // the AI's reading is the Office of the Accountant General's
  const showTimeline = isDept                              // where every case stands, on its row
  const cols = 5 + (showDepartment ? 1 : 0) + (showAi ? 1 : 0) + (showTimeline ? 1 : 0)
  const chips = GROUPS.filter(g => isDept || g.ag)
  const filterWords = [bucket === 'all' ? null : bucketLabel[bucket],
                       group ? GROUPS.find(g => g.key === group)?.[isDept ? 'dept' : 'ag'] : null, section || null, dept || null, kind ? (kinds.find(k => k[0] === kind)?.[1] ?? kind) : null].filter(Boolean).join(' · ')

  return (
    <div className="screen container" style={{ paddingTop: 22 }}>
      {showDash && <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 'var(--s4)', flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ marginBottom: 2 }}>{title}</h1>
          <p className="lead" style={{ margin: 0 }}>{lead}</p>
        </div>
        {/* No new-case button here (22 Oct 2026). The dashboard is the figures; filing belongs
            with the register of cases, which is the next tab and where the button now is. */}
      </div>

      <div className="tiles" role="tablist" aria-label="Filter the cases" onKeyDown={tileKeys}>
        <button role="tab" data-bucket="mine" tabIndex={bucket === 'mine' ? 0 : -1} aria-selected={bucket === 'mine'} className={`tile hot${bucket === 'mine' ? ' is-on' : ''}`} onClick={() => pickBucket('mine')}>
          <div className="t">{bucketLabel.mine}</div>
          <div className="n">{tile.mine}</div>
          <div className="d">{isDept ? 'Cases to verify, submit or correct.' : 'Submitted by departments; decision pending.'}</div>
        </button>
        <button role="tab" data-bucket="theirs" tabIndex={bucket === 'theirs' ? 0 : -1} aria-selected={bucket === 'theirs'} className={`tile wait${bucket === 'theirs' ? ' is-on' : ''}`} onClick={() => pickBucket('theirs')}>
          <div className="t">{theirsLabel}</div>
          <div className="n">{tile.theirs}</div>
          <div className="d">{theirsDesc}</div>
        </button>
        <button role="tab" data-bucket="done" tabIndex={bucket === 'done' ? 0 : -1} aria-selected={bucket === 'done'} className={`tile ok${bucket === 'done' ? ' is-on' : ''}`} onClick={() => pickBucket('done')}>
          <div className="t">Disposed</div>
          <div className="n">{tile.done}</div>
          <div className="d">Approved or rejected.</div>
        </button>
        <button role="tab" data-bucket="all" tabIndex={bucket === 'all' ? 0 : -1} aria-selected={bucket === 'all'} className={`tile${bucket === 'all' ? ' is-on' : ''}`} onClick={() => pickBucket('all')}>
          <div className="t">All cases</div>
          <div className="n">{tile.all}</div>
          <div className="d">Every case on this register.</div>
        </button>
      </div>

      {charts}
      </>}
      {showCases && <>
      {view === 'cases'
        ? <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 'var(--s4)', flexWrap: 'wrap' }}>
            <h1>Cases</h1>
            {/* The one place in the portal a case is filed from, besides the landing cards
                (22 Oct 2026). It was the header bar's on this tab and the dashboard's own on
                the other -- one action in two parts of the screen under two names, depending
                on which tab you were on. It sits with the cases, which is what it adds to. */}
            {onNew && <button className="primary big" onClick={onNew}>{newLabel ?? 'New case'}</button>}
          </div>
        : <h2 style={{ margin: 'var(--s5) 0 0' }}>Cases</h2>}
      <div className="row" style={{ marginTop: 'var(--s3)', gap: 'var(--s3)', alignItems: 'center' }}>
        <input placeholder={product === 'GPF' ? 'Search by case number, name or department' : 'Search by case number, name, department or case type'} value={q} onChange={e => { setQ(e.target.value); setPage(1) }}
               style={{ maxWidth: 420 }} aria-label="Search the cases" />
      </div>

      <div className="filter-bar">
        <div className="chips" role="group" aria-label="Filter by status">
          <button type="button" className={`chip-btn${group === '' ? ' is-on' : ''}`} aria-pressed={group === ''} onClick={() => { setGroup(''); setPage(1) }}>All</button>
          {chips.map(g => (
            <button key={g.key} type="button" className={`chip-btn${group === g.key ? ' is-on' : ''}`} aria-pressed={group === g.key}
                    onClick={() => narrowTo(() => setGroup(g.key))}>
              {isDept ? g.dept : g.ag}
            </button>
          ))}
        </div>
        {showDepartment && sections.length > 1 && (
          <select className="filter-select" aria-label="Filter by pension section" value={section} onChange={e => narrowTo(() => setSection(e.target.value))}>
            <option value="">All sections</option>
            {sections.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
        {showDepartment && depts.length > 1 && (
          <select className="filter-select" aria-label="Filter by department" value={dept} onChange={e => narrowTo(() => setDept(e.target.value))}>
            <option value="">All departments</option>
            {depts.map(d => <option key={d} value={d}>{d}</option>)}
          </select>
        )}
        {kinds.length > 0 && (
          <select className="filter-select" aria-label="Filter by pension type" value={kind} onChange={e => narrowTo(() => setKind(e.target.value))}>
            <option value="">{product === 'GPF' ? 'All kinds of claim' : 'All case types'}</option>
            {kinds.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        )}
        {filtered && (
          <>
            <span className="filter-count" role="status" aria-live="polite">Showing {shown.length} case{shown.length === 1 ? '' : 's'} · {filterWords}</span>
            <button type="button" className="ghost filter-clear" onClick={clear}>Clear filters</button>
          </>
        )}
      </div>

      {error && <div className="banner bad" style={{ marginTop: 'var(--s4)' }}><span className="mark">!</span><div className="sub">{error}</div></div>}
      {stale && !error && <div className="muted" role="status" style={{ marginTop: 'var(--s3)', fontSize: 'var(--t-small)' }}>Connection lost — retrying. The list shows what was last received.</div>}

      <div className="card table-wrap register-table" style={{ marginTop: 'var(--s3)', padding: 0 }}>
        <table>
          <colgroup>
            <col className="c-case" />
            <col />
            {showDepartment && <col className="c-dept" />}
            <col className="c-status" />
            {showTimeline && <col className="c-timeline" />}
            {showAi && <col className="c-ai" />}
            <col className="c-updated" />
            <col className="c-go" />
          </colgroup>
          <thead>
            <tr>
              <th>Case</th>
              <th>Claimant</th>
              {showDepartment && <th>Department</th>}
              <th>Status</th>
              {showTimeline && <th>Progress</th>}
              {showAi && <th>AI result</th>}
              <th className="num">Updated</th>
              <th><span className="sr-only">Action</span></th>
            </tr>
          </thead>
          <tbody>
            {loading && rows.length === 0 && <tr><td colSpan={cols} className="muted">Loading…</td></tr>}
            {!loading && !error && shown.length === 0 && (
              <tr><td colSpan={cols}>
                <div className="empty">
                  {/* A tile is one of the filters now, so "no case requires your action" is
                      what the filters say: the empty register is the register being empty. */}
                  <strong>{filtered ? 'No case matches the filters.' : q.trim() ? 'No case matches the search.' : 'No cases in this list.'}</strong>
                  {filtered && <div style={{ marginTop: 8 }}><button type="button" className="ghost" onClick={clear}>Clear filters</button></div>}
                  {onNew && !filtered && !q.trim() && <div style={{ marginTop: 8 }}>Use <em>{newLabel ?? 'New case'}</em> above to file a case.</div>}
                </div>
              </td></tr>
            )}
            {visible.map(r => {
              const run = r.latest_run
              const m = STATUS_META[r.status]
              const step = nextStep({ status: r.status, allowed_actions: [] }, role)
              const mine = waitingOn.includes(r.status)
              const verb = mine && step.action ? VERBS[step.action] ?? 'Open' : 'Open'
              // Green only when the verification found nothing AND every required document is present;
              // findings and missing papers are amber -- something to correct, not an alarm.
              const incomplete = run?.state === 'done' && !run.high_flags && (run.verdict !== 'FORWARD' || run.checklist_result === 'INCOMPLETE')
              const cleared = run?.state === 'done' && r.status === 'APPROVED'
              const ai = !run ? { text: 'Not run', pill: 'neutral', title: 'The verification has not been run on this case.' }
                : run.state === 'done' ? (cleared
                    ? { text: 'Cleared', pill: 'low', title: 'Every finding was cleared and every required document present; the case was approved by an officer.' }
                  : run.high_flags
                    ? { text: `${run.high_flags} finding${run.high_flags === 1 ? '' : 's'}`, pill: 'medium', title: `The verification found ${run.high_flags} finding${run.high_flags === 1 ? '' : 's'} for the Office of the Accountant General to clear.` }
                    : incomplete
                      ? { text: 'Documents missing', pill: 'medium', title: 'No deficiencies in the papers read, but required documents are missing; the engine advises return for correction.' }
                      : { text: 'No deficiencies', pill: 'low', title: 'The latest verification found no deficiencies and every required document.' })
                : run.state === 'failed' ? { text: 'Incomplete', pill: 'medium', title: 'The verification did not complete.' }
                : { text: 'In progress', pill: 'medium', title: 'The verification is running.' }
              const days = daysWaiting(r)
              const kindWord = kindOf(r)
              return (
                <tr key={r.id} onClick={() => onOpen(r.id)} style={{ cursor: 'pointer' }}>
                  <td data-col="Case">
                    <div className="case-no">{r.case_no}</div>
                    <div className="row-hint">{r.documents} document{r.documents === 1 ? '' : 's'}{r.submission_no > 1 ? ` · submission ${r.submission_no}` : ''}</div>
                    {(kindWord || days !== null) && (
                      <div className="row-meta">
                        {kindWord && <span className="row-type" title={r.product === 'GPF' ? undefined : CASE_TYPE_SOURCE_WORDS[r.case_type_source ?? ''] ?? undefined}>
                          {kindWord}{r.product !== 'GPF' && r.case_type_source === 'DETECTED' && <span className="pill neutral" style={{ marginLeft: 6, fontSize: 11, padding: '0 6px' }}>Detected</span>}
                        </span>}
                        {days !== null && <span className={`sla sla-${slaTone(days)}`} title="Days waiting at the present stage">{days}d pending</span>}
                      </div>
                    )}
                  </td>
                  <td data-col="Claimant" className="cell-ellipsis" title={r.claimant_name ?? undefined} style={{ fontSize: 15 }}>
                    {r.claimant_name ?? <span className="muted" title="The claimant's name is read from the documents by the verification">—</span>}
                  </td>
                  {showDepartment && <td data-col="Department" className="cell-ellipsis" title={r.department_name ?? undefined}>
                    {r.department_name}
                    <div className="row-hint">{r.pension_section ?? 'Legacy'}</div>
                  </td>}
                  <td data-col="Status"><span className={`pill ${m.pill}`} title={`${m.label}. ${isDept ? m.dept : m.ag}`}>{SHORT[r.status]}</span>
                    {!isDept && r.holder_label && <div className="row-hint">{r.holder_label}</div>}</td>
                  {showTimeline && <td data-col="Progress"><RowTimeline row={r} /></td>}
                  {showAi && <td data-col="AI result"><span className={`pill ${ai.pill}`} title={ai.title}>{ai.text}</span></td>}
                  <td data-col="Updated" className="num muted" style={{ fontSize: 'var(--t-small)', whiteSpace: 'nowrap' }} title={r.updated_at}>{ago(r.updated_at)}</td>
                  <td data-col="" className="num">
                    <button className={`row-go ${mine ? 'primary' : ''}`} onClick={e => { e.stopPropagation(); onOpen(r.id) }}
                            title={mine && step.action ? step.text : 'Open the case'}>
                      {verb}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <nav className="pager" aria-label="Register pages">
          <button type="button" disabled={current <= 1} onClick={() => setPage(current - 1)}>‹ Prev</button>
          <span className="pager-info" role="status" aria-live="polite">Page {current} of {pages} · {(current - 1) * PAGE + 1}–{Math.min(current * PAGE, shown.length)} of {shown.length}</span>
          <button type="button" disabled={current >= pages} onClick={() => setPage(current + 1)}>Next ›</button>
        </nav>
      )}
      </>}
    </div>
  )
}
