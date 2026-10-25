/** The dashboard strip above a register or review queue: the figures an officer decides by.
 *
 *  Same data as the list below it (GET /api/v2/stats over the same scope), so the charts and
 *  the rows always agree. Two columns (design of 28 Sep 2026, from the pension-portal mockup):
 *    review/admin, all departments — the Accountant General's decisions (donut) beside the
 *        cases filed each week; every department's caseload, ranked, with the part awaiting
 *        decision in blue, across the full width; then the pending queue by age beside the
 *        time-to-decision gauge.
 *    review, one department — that department's cases, its filings, its queue by age, its
 *        time to decision.
 *    department — the standing of its own cases, its filings, what is waiting on it by age and
 *        what waits at the AG by age. The AI's reading is not shown to a department (28 Sep 2026).
 *  Colour means one thing everywhere: blue = with the Accountant General, green = approved,
 *  red = rejected, amber = sent back, slate = still with the department.
 */
import { useEffect, useMemo, useState } from 'react'
import { downloadMonthlyRegister, fetchStats, recentMonths, type Ageing, type Product, type Stats } from '../api/cases'
import { useInventoryTick } from '../data/inventory'
import { Bars, ChartCard, Columns, Donut, Gauge, SplitBars } from '../charts/Charts'

export function useStats(department?: string | null, product?: Product, pensionSection?: string | null, enabled = true) {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Refetched with the inventory (any change anywhere moves the tick), so the charts and KPI
  // cards move in the same moment as the lists; and once a minute for the ageing figures.
  // Not fetched at all for a view that draws no chart (the cases list, F16).
  const tick = useInventoryTick()
  useEffect(() => {
    if (!enabled) return
    let live = true
    const load = () => { if (document.visibilityState !== 'visible') return; fetchStats(department, product, pensionSection).then(s => { if (live) { setStats(s); setError(null) } }).catch(e => { if (live) setError(e instanceof Error ? e.message : String(e)) }) }
    load()
    const t = setInterval(load, 60000)
    return () => { live = false; clearInterval(t) }
  }, [department, product, pensionSection, tick, enabled])
  return { stats, error }
}

const fmtN = (n: number) => n.toLocaleString('en-PK')
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const plural = (n: number, w: string) => `${fmtN(n)} ${w}${n === 1 ? '' : 's'}`

/** How many periods each frequency shows, and what a column of it is called. */
const PERIODS = {
  daily: { label: 'Daily', columns: 30, word: 'days', now: 'today' },
  weekly: { label: 'Weekly', columns: 10, word: 'weeks', now: 'this week' },
  monthly: { label: 'Monthly', columns: 12, word: 'months', now: 'this month' },
} as const
type Period = keyof typeof PERIODS

/** The first day of the period a date falls in. */
function bucketOf(d: Date, period: Period): Date {
  const b = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  if (period === 'weekly') b.setDate(b.getDate() - ((b.getDay() + 6) % 7))   // Monday
  if (period === 'monthly') b.setDate(1)
  return b
}

function stepBack(d: Date, period: Period, n: number): Date {
  const b = new Date(d)
  if (period === 'daily') b.setDate(b.getDate() - n)
  if (period === 'weekly') b.setDate(b.getDate() - 7 * n)
  if (period === 'monthly') b.setMonth(b.getMonth() - n)
  return b
}

/** Cases filed over time, newest on the right, at whichever frequency the officer picks.
 *
 *  Weekly only until 25 Oct 2026, which is the wrong grain at both ends: a week hides the
 *  day a batch arrived, and ten of them is too short a run to show a season. The server
 *  sends every day that saw something over thirteen months (api/v2 stats "days") and the
 *  bucketing is done here, so changing the period costs no request.
 */
function FiledCard({ stats }: { stats: Stats }) {
  const [period, setPeriod] = useState<Period>('weekly')
  const { columns, word, now } = PERIODS[period]
  const buckets = useMemo(() => {
    const end = bucketOf(new Date(), period)
    const keys: string[] = []
    for (let i = columns - 1; i >= 0; i--) keys.push(iso(stepBack(end, period, i)))
    const filed = new Map(keys.map(k => [k, 0]))
    for (const d of stats.days ?? []) {
      const k = iso(bucketOf(new Date(d.day + 'T00:00:00'), period))
      if (filed.has(k)) filed.set(k, filed.get(k)! + d.filed)
    }
    return keys.map(k => ({ key: k, filed: filed.get(k)! }))
  }, [stats.days, period, columns])

  const total = buckets.reduce((n, b) => n + b.filed, 0)
  // Labels thin out as the columns multiply: thirty of them in a card's width would clip
  // into fragments, so every other week is named and only every fifth day.
  const every = period === 'daily' ? 5 : period === 'weekly' ? 2 : 1
  const data = buckets.map((b, i) => {
    const d = new Date(b.key + 'T00:00:00')
    const short = period === 'monthly'
      ? d.toLocaleDateString('en-GB', { month: 'short', year: '2-digit' })
      : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
    const last = i === buckets.length - 1
    return { label: last ? now : (buckets.length - 1 - i) % every === 0 ? short : '',
             value: b.filed, color: 'var(--ramp-2)',
             title: period === 'weekly' ? `Week of ${short}` : short }
  })
  const picker = (
    <select className="chart-period" aria-label="How often to group the cases"
            value={period} onChange={e => setPeriod(e.target.value as Period)}>
      {(Object.keys(PERIODS) as Period[]).map(k => <option key={k} value={k}>{PERIODS[k].label}</option>)}
    </select>
  )
  return (
    <ChartCard title="Cases filed over time" sub={`last ${columns} ${word} · ${plural(total, 'case')}`}
               control={picker}>
      {total ? <Columns data={data} height={168} unit="filed" /> : <div className="empty">No case filed in this period.</div>}
    </ChartCard>
  )
}

/** Every department that has filed, ranked; the dark part of each bar is awaiting decision. */
function DepartmentsCard({ stats }: { stats: Stats }) {
  const byTotal = [...stats.by_department].sort((a, b) => b.total - a.total || a.name.localeCompare(b.name))
  const rows = byTotal.map(d => ({ label: d.name, values: [d.awaiting, d.total - d.awaiting], sub: d.awaiting ? `${d.awaiting} awaiting` : undefined }))
  return (
    <ChartCard title="Department caseload" sub={`${plural(byTotal.length, 'department')} · ${plural(stats.total, 'case')} · dark = awaiting your decision`} className="span-2">
      {rows.length
        ? <div className="dept-bars"><SplitBars rows={rows} series={[{ name: 'Awaiting decision', color: 'var(--ramp-1)' }, { name: 'Other', color: 'var(--ramp-4)' }]} height={30} /></div>
        : <div className="empty">No case filed yet.</div>}
    </ChartCard>
  )
}

const AGE_BUCKETS: { key: keyof Ageing['buckets']; label: string; color: string }[] = [
  { key: '0-3', label: '0–3 days', color: 'var(--ramp-3)' },
  { key: '4-7', label: '4–7 days', color: 'var(--gold)' },
  { key: '8-14', label: '8–14 days', color: 'var(--viz-warn)' },
  { key: '15+', label: '15+ days', color: 'var(--viz-bad)' },
]

/** The pending queue grouped by how long each case has waited at its present stage. */
function AgeCard({ ageing, title, waitingWord }: { ageing: Ageing | undefined; title: string; waitingWord: string }) {
  if (!ageing) return <ChartCard title={title}><div className="empty">Available after the next start of the service.</div></ChartCard>
  const data = AGE_BUCKETS.map(b => ({ label: b.label, value: ageing.buckets[b.key], color: b.color }))
  return (
    <ChartCard title={title} sub={ageing.total ? `${fmtN(ageing.total)} ${waitingWord} · oldest ${plural(ageing.oldest_days, 'day')}` : `Nothing ${waitingWord}`}
               footer={ageing.oldest_case && ageing.oldest_days > 7 ? `Longest waiting: ${ageing.oldest_case}.` : undefined}>
      {ageing.total ? <div className="age-bars"><Bars data={data} height={34} /></div> : <div className="empty">No case is waiting.</div>}
    </ChartCard>
  )
}

/** Average days from filing to the Accountant General's decision, against the office's target. */
function TimeToDecisionCard({ stats }: { stats: Stats }) {
  const target = stats.decision_target_days ?? 7
  const avg = stats.avg_days_to_decision
  const within = stats.decided_within_target
  const pct = stats.decided_total && within != null ? Math.round(within / stats.decided_total * 100) : null
  const color = avg == null ? 'var(--viz-neutral)' : avg <= target ? 'var(--viz-good)' : avg <= target * 1.5 ? 'var(--viz-warn)' : 'var(--viz-bad)'
  return (
    <ChartCard title="Time to decision" sub={`average against the ${target}-day target`}>
      {avg == null
        ? <div className="empty">The Office of the Accountant General has not decided a case yet.</div>
        : <Gauge value={avg} max={target} unit="days avg" color={color} label={`Average ${avg} days to decision against a ${target}-day target`}
                 big={pct == null ? '—' : `${pct}%`} bigLabel={`decided within ${target} days`} note={`Target: ${target} days from filing · ${plural(stats.decided_total, 'case')} decided`} />}
    </ChartCard>
  )
}

//: Off the screen for now, at the office's asking (23 Oct 2026). The endpoint is live and
//: tested -- GET /api/v2/reports/monthly.csv -- and so is everything below; this is the one
//: line that decides whether the control is drawn. Set it true to bring it back.
const MONTHLY_REGISTER_ON_SCREEN = false

/** The month's cases, as a spreadsheet, for whoever is signed in (23 Oct 2026).
 *
 *  Every officer and every DDO: the download is scoped by the same rule the register is, so a
 *  department gets its own cases and an officer their wing's, and nobody is shown anything the
 *  register would not show them. A month is the month a case was FILED in -- the month its
 *  case number belongs to, and the one reading that does not change as the office works. */
function MonthlyRegister({ product, department }: { product: Product; department?: string | null }) {
  const months = recentMonths()
  const [month, setMonth] = useState(months[0].value)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function go() {
    setBusy(true); setError(null)
    try { await downloadMonthlyRegister(month, product, department) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  return (
    <div className="row" style={{ gap: 'var(--s2)', alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 'var(--s3)' }}>
      <div className="field" style={{ margin: 0 }}>
        <label className="label" htmlFor="month-register">Monthly register</label>
        <select id="month-register" value={month} onChange={e => setMonth(e.target.value)} style={{ minWidth: 190 }}>
          {months.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
      </div>
      <button type="button" onClick={go} disabled={busy}>{busy ? 'Preparing…' : 'Download spreadsheet'}</button>
      {error && <span className="help" style={{ color: 'var(--red)' }}>{error}</span>}
    </div>
  )
}

/** Where the office's pending cases are standing, and the oldest at each desk.
 *
 *  "Three cases at the Assistant Accounts Officer" is a fact an officer can do nothing with
 *  until they know which three and since when, so each desk carries its oldest case by number
 *  and the number that have been there over a week. The bar is the whole desk; the darker part
 *  is the share of it that has waited more than a week, which is what "stuck" means here.
 *
 *  A department never sees this card: the server sends it no by_desk at all, because a DDO is
 *  told the case is with the Office of the Accountant General and not which desk holds it. */
function DesksCard({ stats }: { stats: Stats }) {
  // The server sends by_desk to the oversight roles only (api/v2.py OVERSIGHT_ROLES), so its
  // absence is the answer: a tier officer and a department are not shown the desks at all,
  // rather than shown an empty chart of them.
  const desks = stats.by_desk
  if (!desks) return null
  const waiting = desks.reduce((n, d) => n + d.total, 0)
  const stuck = desks.reduce((n, d) => n + d.waiting_over_a_week, 0)
  const worst = desks.reduce<typeof desks[number] | null>((w, d) => d.oldest_days > (w?.oldest_days ?? -1) ? d : w, null)
  return (
    <ChartCard title="Where cases are waiting" className="span-2"
               sub={waiting ? `${plural(waiting, 'case')} with the office · ${stuck} waiting over a week` : 'No case is with the office'}
               footer={worst?.oldest_case ? `Longest wait: ${worst.oldest_case}, ${plural(worst.oldest_days, 'day')} at the ${worst.label}.` : undefined}>
      {waiting
        ? <SplitBars series={[{ name: 'Waiting over a week', color: 'var(--viz-warn)' },
                              { name: 'Waiting up to a week', color: 'var(--viz-await)' }]}
                    rows={desks.map(d => ({
                      label: d.label,
                      values: [d.waiting_over_a_week, Math.max(0, d.total - d.waiting_over_a_week)],
                      sub: d.oldest_case ? `oldest ${d.oldest_case}, ${plural(d.oldest_days, 'day')} here` : undefined,
                    }))} />
        : <div className="empty">No case is with the office.</div>}
    </ChartCard>
  )
}

export function Dashboard(
  { stats, error, variant, department, product = 'PENSION' }:
  { stats: Stats | null; error?: string | null; variant: 'department' | 'review' | 'admin'
    department?: string | null
    /** Which register the monthly download is of; the charts themselves are already scoped. */
    product?: Product },
) {
  if (!stats && error) return <div className="banner bad" style={{ marginTop: 'var(--s4)' }}><span className="mark">!</span><div className="sub">The statistics could not be loaded: {error}</div></div>
  if (!stats) return <div className="skeleton" style={{ height: 120, marginTop: 'var(--s4)' }} />
  const s = stats
  const approved = s.by_status.APPROVED
  const rejected = s.by_status.REJECTED
  // The verification runs on the AG's desk (28 Sep 2026): those cases are with the AG.
  const withAg = s.by_status.FORWARDED + s.by_status.AI_CHECKING + s.by_status.AI_FAILED + s.by_status.UNDER_REVIEW
  const sentBack = s.by_status.RETURNED + s.by_status.DOCS_REQUESTED
  const withDept = s.by_status.DRAFT + s.by_status.AI_CHECKED

  // The Accountant General's decisions, over whatever is in scope.
  const decisionParts = [
    { label: 'Approved', value: approved, color: 'var(--viz-good)' },
    { label: 'Rejected', value: rejected, color: 'var(--viz-bad)' },
    { label: 'Awaiting decision', value: withAg, color: 'var(--viz-await)' },
    { label: 'Sent back for correction', value: sentBack, color: 'var(--viz-warn)' },
    { label: 'With the department, not yet submitted', value: withDept, color: 'var(--viz-neutral)' },
  ]
  const decisionsFooter = approved + rejected
    ? `${approved} approved and ${rejected} rejected so far${s.avg_days_to_decision != null ? `; on average ${s.avg_days_to_decision} days from filing to decision` : ''}.`
    : 'The Office of the Accountant General has not decided a case yet.'
  const decisions = (
    <ChartCard title={variant === 'department' ? 'Your cases and the Office of the Accountant General\'s decisions' : department ? 'This department\'s cases' : 'Decisions of the Office of the Accountant General'}
               sub={`${plural(s.total, 'case')} in all`} footer={s.total ? decisionsFooter : undefined}>
      {s.total ? <Donut parts={decisionParts} centreLabel="cases" countUp /> : <div className="empty">No case filed yet.</div>}
    </ChartCard>
  )

  if (variant === 'department') {
    return (<>
      {MONTHLY_REGISTER_ON_SCREEN && <MonthlyRegister product={product} />}
      <div className="chart-grid">
        {decisions}
        <FiledCard stats={s} />
        <AgeCard ageing={s.ageing?.with_department} title="Waiting on you, by age" waitingWord="to submit or correct" />
        <AgeCard ageing={s.ageing?.with_ag} title="With the Office of the Accountant General, by age" waitingWord="awaiting the Pension Wing" />
      </div>
    </>)
  }
  if (department) {
    return (<>
      {MONTHLY_REGISTER_ON_SCREEN && <MonthlyRegister product={product} department={department} />}
      <div className="chart-grid">
        {decisions}
        <FiledCard stats={s} />
        <DesksCard stats={s} />
        <AgeCard ageing={s.ageing?.with_ag} title="Pending decisions by age" waitingWord="awaiting decision" />
        <TimeToDecisionCard stats={s} />
      </div>
    </>)
  }
  return (<>
    {MONTHLY_REGISTER_ON_SCREEN && <MonthlyRegister product={product} />}
    <div className="chart-grid">
      {decisions}
      <FiledCard stats={s} />
      <DesksCard stats={s} />
      <DepartmentsCard stats={s} />
      <AgeCard ageing={s.ageing?.with_ag} title="Pending decisions by age" waitingWord="awaiting decision" />
      <TimeToDecisionCard stats={s} />
    </div>
  </>)
}
