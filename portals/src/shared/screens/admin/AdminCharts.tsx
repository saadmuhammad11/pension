/** The administrator's own figures, in place of the Accountant General's caseload.
 *
 *  Until 25 Oct 2026 the administrator's overview was the review desk's dashboard: filings
 *  over time, department caseload, where cases are waiting, pending by age, time to decision.
 *  Six charts about decisions the administrator does not take, while the things that ARE
 *  theirs were on no screen at all.
 *
 *  Five charts replaced them, and then four of those five were replaced again the same day:
 *  the first attempt answered the questions but drew three of them as a bullet list and two
 *  pairs of large numbers, which is a dashboard of figures rather than of graphs. A number
 *  says what is true now; a series says whether it is getting better, and that is what an
 *  administrator is actually asking. So each card here is a shape over time or a comparison
 *  across a set, and the one bare number left -- the single department with no account --
 *  sits as a sentence under the chart it belongs to.
 *
 *  Colour carries meaning and nothing else: green is what worked, red what did not, and the
 *  neutral ramp is for counts that are neither.
 */
import { Bars, ChartCard, Columns, SplitBars } from '../../charts/Charts'
import type { Stats } from '../../api/cases'
import { ROLE_WORDS } from './Users'

const fmtN = (n: number) => n.toLocaleString('en-GB')
//: Adding an s covers every word on these cards but one, and "47 entrys" is how that
//: was found (25 Oct 2026).
const PLURALS: Record<string, string> = { entry: 'entries' }
const plural = (n: number, w: string) =>
  `${fmtN(n)} ${n === 1 ? w : PLURALS[w] ?? w + 's'}`
const pct = (n: number, of: number) => (of ? Math.round((n / of) * 100) : 0)

/** "24 Oct", and "today" for the last one in a series. */
const dayLabel = (iso: string) =>
  new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

/** Every day in the window, so a quiet day is a gap in the shape and not a missing column. */
function fill<T extends { day: string }>(rows: T[], days: number, blank: Omit<T, 'day'>): T[] {
  const out: T[] = []
  const found = new Map(rows.map(r => [r.day, r]))
  const d = new Date()
  for (let i = days - 1; i >= 0; i--) {
    const at = new Date(d.getFullYear(), d.getMonth(), d.getDate() - i)
    const key = `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, '0')}-${String(at.getDate()).padStart(2, '0')}`
    out.push(found.get(key) ?? ({ day: key, ...blank } as T))
  }
  return out
}

/** Who holds an account, and how many have never set a password of their own. */
function AccountsCard({ stats }: { stats: Stats }) {
  const a = stats.admin!
  const roles = Object.entries(stats.users_by_role ?? {})
    .sort((x, y) => y[1] - x[1])
    .map(([role, n]) => ({ label: ROLE_WORDS[role] ?? role, value: n, color: 'var(--ramp-2)' }))
  const share = pct(a.must_change_password, a.users_total)
  const gap = a.departments_without_user
  return (
    <ChartCard title="Who holds an account"
               sub={`${plural(a.users_total, 'account')}${a.users_inactive ? ` · ${a.users_inactive} disabled` : ''}`}
               accent={share >= 50 ? 'var(--viz-warn)' : undefined}
               footer={[
                 a.must_change_password
                   ? `${plural(a.must_change_password, 'account')} (${share}%) still hold the password they were issued with.`
                   : 'Every account has a password its holder set.',
                 gap ? `${plural(gap, 'department')} of ${a.departments_total} has no account and cannot file.` : null,
               ].filter(Boolean).join(' ')}>
      {roles.length ? <Bars data={roles} unit="accounts" /> : <div className="empty">No account yet.</div>}
    </ChartCard>
  )
}

/** How many different people touched the system each day. An account issued is not an
 *  account used, and the gap between the two is the administrator's to close. */
function InUseCard({ stats }: { stats: Stats }) {
  const a = stats.admin!
  const days = fill(a.actors_by_day, 14, { people: 0 })
  const busiest = Math.max(0, ...days.map(d => d.people))
  const data = days.map((d, i) => ({
    label: i === days.length - 1 ? 'today' : i % 3 === 0 ? dayLabel(d.day) : '',
    value: d.people,
    color: d.people === busiest && busiest > 0 ? 'var(--ramp-1)' : 'var(--ramp-3)',
    title: dayLabel(d.day),
  }))
  return (
    <ChartCard title="People using the system" sub="different officers each day, last 14 days"
               footer={`${a.people_ever} of ${plural(a.users_total, 'account')} have ever signed in and done something.`}>
      {busiest ? <Columns data={data} height={150} unit="people" />
               : <div className="empty">Nobody has used the system in this period.</div>}
    </ChartCard>
  )
}

/** Accepted against refused. The share is the thing: a day of eleven in and eleven refused
 *  reads as ordinary on a running total of failures and is not. */
function SignInCard({ stats }: { stats: Stats }) {
  const a = stats.admin!
  const days = fill(a.sign_ins_by_day, 7, { ok: 0, refused: 0 })
  const ok = days.reduce((n, d) => n + d.ok, 0)
  const refused = days.reduce((n, d) => n + d.refused, 0)
  const share = pct(refused, ok + refused)
  const rows = days.map(d => ({
    label: dayLabel(d.day),
    values: [d.ok, d.refused],
    sub: d.ok + d.refused ? `${pct(d.refused, d.ok + d.refused)}% refused` : undefined,
  }))
  return (
    <ChartCard title="Signing in" sub={`last 7 days · ${share}% of attempts refused`}
               accent={share >= 25 ? 'var(--viz-warn)' : undefined}
               footer={a.locked_out
                 ? `${plural(a.locked_out, 'account or address')} locked out now. A lockout clears after a minute; an officer who still cannot get in needs their password reset.`
                 : 'Nothing is locked out. A wrong password is usually a forgotten one, but a run of them against one account is not.'}>
      {ok + refused
        ? <SplitBars rows={rows} unit="attempts"
                     series={[{ name: 'Accepted', color: 'var(--viz-good)' },
                              { name: 'Refused', color: 'var(--viz-bad)' }]} />
        : <div className="empty">Nobody has signed in during this period.</div>}
    </ChartCard>
  )
}

/** The examination failing is the administrator's errand: a model key, a disk, a service.
 *  When it failed is the whole of it -- six of one day's runs went at once on an expired key,
 *  which a fortnight's total of eight hides completely. */
function ExaminationsCard({ stats }: { stats: Stats }) {
  const a = stats.admin!
  const days = fill(a.runs_by_day, 7, { done: 0, failed: 0 })
  const done = days.reduce((n, d) => n + d.done, 0)
  const failed = days.reduce((n, d) => n + d.failed, 0)
  const share = pct(failed, done + failed)
  const rows = days.map(d => ({
    label: dayLabel(d.day),
    values: [d.done, d.failed],
    sub: d.failed ? `${plural(d.failed, 'failure')}` : undefined,
  }))
  return (
    <ChartCard title="Examinations" sub={`last 7 days · ${share}% failed`}
               accent={share >= 10 ? 'var(--viz-bad)' : undefined}
               footer={failed
                 ? 'A run fails on a model key, a full disk or a service that is down — never on anything in the case. The reason is on the case’s own screen.'
                 : done ? 'Every examination completed.' : undefined}>
      {done + failed
        ? <SplitBars rows={rows} unit="runs"
                     series={[{ name: 'Completed', color: 'var(--viz-good)' },
                              { name: 'Failed', color: 'var(--viz-bad)' }]} />
        : <div className="empty">No examination ran in this period.</div>}
    </ChartCard>
  )
}

/** The audit log is three quarters sign-in traffic, which the chart above already shows. What
 *  is left is what was actually done to cases, accounts and signatories. */
const ACTION_WORDS: Record<string, string> = {
  CHECKLIST_WAIVE: 'Checklist item waived', FINDING_WAIVE: 'Finding waived',
  FINDING_UPHOLD: 'Finding upheld', SPECIMEN_VIEWED: 'Signature specimen viewed',
  PASSWORD_CHANGE: 'Password changed', PASSWORD_RESET: 'Password reset by the administrator',
  CHECKLIST_NAME: 'Checklist item named', USER_CREATE: 'Account created',
  USER_UPDATE: 'Account changed', USER_DISABLE: 'Account disabled', USER_RENAME: 'Login name changed',
  SIGNATORY_CREATE: 'Signing authority added', SIGNATORY_UPDATE: 'Signing authority changed',
  CASE_OVERRIDE: 'Case decision overridden',
}

function ChangesCard({ stats }: { stats: Stats }) {
  const rows = stats.admin!.changes_by_action
  const total = rows.reduce((n, r) => n + r.n, 0)
  const data = rows.map((r, i) => ({
    label: ACTION_WORDS[r.action] ?? r.action.toLowerCase().replace(/_/g, ' '),
    value: r.n,
    // The override is the one an administrator is answerable for, so it is never the same
    // colour as the rest however rarely it happens.
    color: r.action === 'CASE_OVERRIDE' ? 'var(--viz-warn)'
      : `var(--viz-seq-${Math.min(5, 5 - Math.min(4, i))})`,
  }))
  return (
    <ChartCard title="What has been done" className="span-2"
               sub={`last 14 days · ${plural(total, 'entry')} on the audit log, signing in aside`}
               footer="Every one of these is in the audit log with who did it, when, and the reason they gave.">
      {total ? <Bars data={data} unit="entries" />
             : <div className="empty">Nothing has been recorded in this period.</div>}
    </ChartCard>
  )
}

export function AdminCharts({ stats }: { stats: Stats }) {
  if (!stats.admin) return null
  return (
    <div className="chart-grid">
      <AccountsCard stats={stats} />
      <InUseCard stats={stats} />
      <SignInCard stats={stats} />
      <ExaminationsCard stats={stats} />
      <ChangesCard stats={stats} />
    </div>
  )
}
