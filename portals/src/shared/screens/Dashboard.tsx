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
import { useEffect, useState } from 'react'
import { fetchStats, type Ageing, type Product, type Stats } from '../api/cases'
import { useInventoryTick } from '../data/inventory'
import { Bars, ChartCard, Columns, Donut, Gauge, SplitBars } from '../charts/Charts'

export function useStats(department?: string | null, product?: Product, pensionSection?: string | null) {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Refetched with the inventory (any change anywhere moves the tick), so the charts and KPI
  // cards move in the same moment as the lists; and once a minute for the ageing figures.
  const tick = useInventoryTick()
  useEffect(() => {
    let live = true
    const load = () => { if (document.visibilityState !== 'visible') return; fetchStats(department, product, pensionSection).then(s => { if (live) { setStats(s); setError(null) } }).catch(e => { if (live) setError(e instanceof Error ? e.message : String(e)) }) }
    load()
    const t = setInterval(load, 60000)
    return () => { live = false; clearInterval(t) }
  }, [department, product, pensionSection, tick])
  return { stats, error }
}

const fmtN = (n: number) => n.toLocaleString('en-PK')
const plural = (n: number, w: string) => `${fmtN(n)} ${w}${n === 1 ? '' : 's'}`

/** Cases filed each week, the last ten weeks, newest on the right. */
function FiledCard({ stats }: { stats: Stats }) {
  const weeks = stats.weeks.slice(-10)
  const total = weeks.reduce((n, w) => n + w.filed, 0)
  const data = weeks.map((w, i) => {
    const d = new Date(w.week + 'T00:00:00')
    const short = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
    // Every other week is labelled; ten labels in a card's width would clip into fragments.
    const last = i === weeks.length - 1
    return { label: last ? 'this week' : (weeks.length - 1 - i) % 2 === 0 ? short : '', value: w.filed, color: 'var(--ramp-2)', title: `Week of ${short}` }
  })
  return (
    <ChartCard title="Cases filed over time" sub={`last ${weeks.length} weeks · ${plural(total, 'case')}`}
               table={{ head: ['Week beginning', 'Filed', 'Decided'], rows: weeks.map(w => [w.week, w.filed, w.decided]) }}>
      {total ? <Columns data={data} height={168} unit="filed" /> : <div className="empty">No case filed in this period.</div>}
    </ChartCard>
  )
}

/** Every department that has filed, ranked; the dark part of each bar is awaiting decision. */
function DepartmentsCard({ stats }: { stats: Stats }) {
  const byTotal = [...stats.by_department].sort((a, b) => b.total - a.total || a.name.localeCompare(b.name))
  const rows = byTotal.map(d => ({ label: d.name, values: [d.awaiting, d.total - d.awaiting], sub: d.awaiting ? `${d.awaiting} awaiting` : undefined }))
  return (
    <ChartCard title="Department caseload" sub={`${plural(byTotal.length, 'department')} · ${plural(stats.total, 'case')} · dark = awaiting your decision`} className="span-2"
               table={{ head: ['Department', 'Cases', 'Approved', 'Rejected', 'Awaiting decision'], rows: byTotal.map(d => [d.name, d.total, d.approved, d.rejected ?? 0, d.awaiting]) }}>
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
               footer={ageing.oldest_case && ageing.oldest_days > 7 ? `Longest waiting: ${ageing.oldest_case}.` : undefined}
               table={{ head: ['Waiting', 'Cases'], rows: data.map(d => [d.label, d.value]) }}>
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
    <ChartCard title="Time to decision" sub={`average against the ${target}-day target`}
               table={{ head: ['Measure', 'Value'], rows: [['Average days, filing to decision', avg ?? '—'], ['Cases decided', stats.decided_total], [`Decided within ${target} days`, within ?? '—']] }}>
      {avg == null
        ? <div className="empty">The Accountant General has not decided a case yet.</div>
        : <Gauge value={avg} max={target} unit="days avg" color={color} label={`Average ${avg} days to decision against a ${target}-day target`}
                 big={pct == null ? '—' : `${pct}%`} bigLabel={`decided within ${target} days`} note={`Target: ${target} days from filing · ${plural(stats.decided_total, 'case')} decided`} />}
    </ChartCard>
  )
}

export function Dashboard(
  { stats, error, variant, department }:
  { stats: Stats | null; error?: string | null; variant: 'department' | 'review' | 'admin'; department?: string | null },
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
    : 'The Accountant General has not decided a case yet.'
  const decisions = (
    <ChartCard title={variant === 'department' ? 'Your cases and the Accountant General\'s decisions' : department ? 'This department\'s cases' : 'Decisions of the Accountant General'}
               sub={`${plural(s.total, 'case')} in all`} footer={s.total ? decisionsFooter : undefined}
               table={{ head: ['Standing', 'Cases'], rows: decisionParts.map(p => [p.label, p.value]) }}>
      {s.total ? <Donut parts={decisionParts} centreLabel="cases" countUp /> : <div className="empty">No case filed yet.</div>}
    </ChartCard>
  )

  if (variant === 'department') {
    return (
      <div className="chart-grid">
        {decisions}
        <FiledCard stats={s} />
        <AgeCard ageing={s.ageing?.with_department} title="Waiting on you, by age" waitingWord="to submit or correct" />
        <AgeCard ageing={s.ageing?.with_ag} title="With the Accountant General, by age" waitingWord="awaiting the Pension Wing" />
      </div>
    )
  }
  if (department) {
    return (
      <div className="chart-grid">
        {decisions}
        <FiledCard stats={s} />
        <AgeCard ageing={s.ageing?.with_ag} title="Pending decisions by age" waitingWord="awaiting decision" />
        <TimeToDecisionCard stats={s} />
      </div>
    )
  }
  return (
    <div className="chart-grid">
      {decisions}
      <FiledCard stats={s} />
      <DepartmentsCard stats={s} />
      <AgeCard ageing={s.ageing?.with_ag} title="Pending decisions by age" waitingWord="awaiting decision" />
      <TimeToDecisionCard stats={s} />
    </div>
  )
}
