/** The administrator's overview: the system in numbers, and the way to each part. */
import { useEffect, useState } from 'react'
import { overview } from '../../api/admin'
import { PRODUCT_WORDS, type Product } from '../../api/cases'
import { Dashboard, useStats } from '../Dashboard'

export function AdminHome({ product }: { product: Product }) {
  const [o, setO] = useState<Awaited<ReturnType<typeof overview>> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { stats, error: statsError } = useStats(undefined, product)
  useEffect(() => { overview().then(setO).catch(e => setError(e instanceof Error ? e.message : String(e))) }, [])
  return (
    <div className="screen container" style={{ paddingTop: 22 }}>
      {/* Not "Pension system overview" (22 Oct 2026): the product is the tab pressed to get
          here, underlined in the header, and named again in the lead directly below. */}
      <h1>System overview</h1>
      <p className="lead">All departments, {PRODUCT_WORDS[product].cases.toLowerCase()} and users. Overrides and changes to user accounts are entered in the audit log.</p>
      {error && <div className="banner bad"><span className="mark">!</span><div className="sub">{error}</div></div>}
      {!o && !error && <div className="skeleton" style={{ height: 120, marginTop: 'var(--s4)' }} />}
      {o && (
        <>
          <div className="kpi-grid" style={{ marginTop: 'var(--s4)' }}>
            <div className="kpi card"><div className="label">Cases</div><div style={{ fontSize: 'var(--t-figure)', fontWeight: 700 }}>{o.cases}</div></div>
            <div className="kpi card"><div className="label">Departments</div><div style={{ fontSize: 'var(--t-figure)', fontWeight: 700 }}>{o.departments}</div></div>
            <div className="kpi card"><div className="label">Users</div><div style={{ fontSize: 'var(--t-figure)', fontWeight: 700 }}>{o.users}</div></div>
            <div className="kpi card"><div className="label">Audit entries</div><div style={{ fontSize: 'var(--t-figure)', fontWeight: 700 }}>{o.audit_entries}</div></div>
          </div>
          <Dashboard stats={stats} error={statsError} variant="admin" product={product} />
          {/* A row of links to the cases, Users, the Audit log and Signing authorities stood
              here (23 Oct 2026). The header carries all four, on this screen and on every
              other, which is where the administrator reaches them from the rest of the time;
              a second copy at the foot of one page is a second thing to keep in step and
              teaches nobody where the first one is. */}
        </>
      )}
    </div>
  )
}
