/** The administrator's own figures, in place of the Accountant General's caseload.
 *
 *  Until 25 Oct 2026 the administrator's overview was the review desk's dashboard: filings
 *  over time, department caseload, where cases are waiting, pending by age, time to decision.
 *  Six charts about decisions the administrator does not take. Meanwhile the things that are
 *  theirs were on no screen at all -- on the day this was written, 108 of 133 accounts had
 *  never changed the password they were issued with, and 17 departments of 103 had no active
 *  account, which means they cannot file a case and nobody is told.
 *
 *  So these five answer "is the system in good order", which is the administrator's question,
 *  and the caseload charts stay on the dashboards of the people who work the cases.
 */
import { Bars, ChartCard, Columns } from '../../charts/Charts'
import type { Stats } from '../../api/cases'
import { ROLE_WORDS } from './Users'

const fmtN = (n: number) => n.toLocaleString('en-GB')
const plural = (n: number, w: string) => `${fmtN(n)} ${w}${n === 1 ? '' : 's'}`

/** Who holds an account, and how many have never set a password of their own. */
function AccountsCard({ stats }: { stats: Stats }) {
  const a = stats.admin!
  const roles = Object.entries(stats.users_by_role ?? {})
    .sort((x, y) => y[1] - x[1])
    .map(([role, n]) => ({ label: ROLE_WORDS[role] ?? role, value: n, color: 'var(--ramp-2)' }))
  const share = a.users_total ? Math.round((a.must_change_password / a.users_total) * 100) : 0
  return (
    <ChartCard title="Who holds an account"
               sub={`${plural(a.users_total, 'account')}${a.users_inactive ? ` · ${a.users_inactive} disabled` : ''}`}
               accent={share >= 50 ? 'var(--viz-warn)' : undefined}
               footer={a.must_change_password
                 ? `${plural(a.must_change_password, 'account')} (${share}%) still have the password they were issued with and have not set one of their own.`
                 : 'Every account has a password its holder set.'}>
      {roles.length ? <Bars data={roles} /> : <div className="empty">No account yet.</div>}
    </ChartCard>
  )
}

/** A department with no active account cannot file a case, and says so nowhere else. */
function DepartmentsWithoutUserCard({ stats }: { stats: Stats }) {
  const a = stats.admin!
  const missing = a.departments_without_user
  return (
    <ChartCard title="Departments that cannot file"
               sub={`${missing.length} of ${plural(a.departments_total, 'department')} have no active account`}
               accent={missing.length ? 'var(--viz-bad)' : undefined}
               footer={missing.length ? 'A department with no account has no way to submit a case.' : undefined}>
      {missing.length ? (
        <ul className="plain-list">
          {missing.slice(0, 8).map(d => <li key={d.code}>{d.name}</li>)}
          {missing.length > 8 && <li className="muted">and {missing.length - 8} more</li>}
        </ul>
      ) : <div className="empty">Every department has someone who can file.</div>}
    </ChartCard>
  )
}

/** What has been done to accounts, departments and cases, day by day. */
function AuditCard({ stats }: { stats: Stats }) {
  const days = stats.audit_by_day ?? []
  const total = days.reduce((n, d) => n + d.n, 0)
  const data = days.map((d, i) => {
    const short = new Date(d.day + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
    return { label: i === days.length - 1 ? 'today' : i % 3 === 0 ? short : '', value: d.n,
             color: 'var(--ramp-3)', title: short }
  })
  return (
    <ChartCard title="Recorded in the audit log" sub={`last ${plural(days.length, 'day')} · ${fmtN(total)} entries`}>
      {total ? <Columns data={data} height={140} unit="entries" />
             : <div className="empty">Nothing recorded in this period.</div>}
    </ChartCard>
  )
}

/** Sign-in refusals and lockouts: the only sign an account is under attack or an officer is
 *  locked out and waiting for the administrator. */
function SignInCard({ stats }: { stats: Stats }) {
  const a = stats.admin!
  return (
    <ChartCard title="Sign-in refusals"
               sub={`${plural(a.sign_in_failures, 'wrong attempt')} in the last 14 days`}
               accent={a.locked_out ? 'var(--viz-warn)' : undefined}
               footer={a.locked_out
                 ? `${plural(a.locked_out, 'account or address')} locked out now. A lockout clears itself after a minute; an officer who cannot get in needs their password reset.`
                 : 'Nothing is locked out.'}>
      <div className="kpi-pair">
        <div><div className="label">Wrong attempts</div><div className="figure">{fmtN(a.sign_in_failures)}</div></div>
        <div><div className="label">Locked out now</div><div className="figure">{fmtN(a.locked_out)}</div></div>
      </div>
    </ChartCard>
  )
}

/** The examination failing is the administrator's errand: a model key, a disk, a service. */
function ExaminationHealthCard({ stats }: { stats: Stats }) {
  const a = stats.admin!
  const ran = a.runs_done + a.runs_failed
  const rate = ran ? Math.round((a.runs_failed / ran) * 100) : 0
  return (
    <ChartCard title="Examinations that failed"
               sub={ran ? `${a.runs_failed} of ${plural(ran, 'run')} in the last 14 days` : 'No examination ran in the last 14 days'}
               accent={rate >= 10 ? 'var(--viz-bad)' : undefined}
               footer={a.runs_failed
                 ? 'A run fails on a model key, a full disk or a service that is down — not on anything in the case. The reason is on the case’s own screen.'
                 : ran ? 'Every examination completed.' : undefined}>
      <div className="kpi-pair">
        <div><div className="label">Completed</div><div className="figure">{fmtN(a.runs_done)}</div></div>
        <div><div className="label">Failed</div><div className="figure" style={a.runs_failed ? { color: 'var(--red)' } : undefined}>{fmtN(a.runs_failed)}</div></div>
      </div>
    </ChartCard>
  )
}

export function AdminCharts({ stats }: { stats: Stats }) {
  if (!stats.admin) return null
  return (
    <div className="chart-grid">
      <AccountsCard stats={stats} />
      <DepartmentsWithoutUserCard stats={stats} />
      <AuditCard stats={stats} />
      <SignInCard stats={stats} />
      <ExaminationHealthCard stats={stats} />
    </div>
  )
}
