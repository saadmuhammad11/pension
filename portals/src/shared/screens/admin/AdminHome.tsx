/** The administrator's overview: the system in numbers, and the way to each part. */
import { useEffect, useState } from 'react'
import { overview } from '../../api/admin'
import { PRODUCT_SLUG, PRODUCT_WORDS, type Product } from '../../api/cases'
import { Dashboard, useStats } from '../Dashboard'

export function AdminHome({ product }: { product: Product }) {
  const [o, setO] = useState<Awaited<ReturnType<typeof overview>> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { stats, error: statsError } = useStats(undefined, product)
  useEffect(() => { overview().then(setO).catch(e => setError(e instanceof Error ? e.message : String(e))) }, [])
  return (
    <div className="screen container" style={{ paddingTop: 22 }}>
      <h1>System overview — {PRODUCT_WORDS[product].name}</h1>
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
          <Dashboard stats={stats} error={statsError} variant="admin" />
          <div className="row" style={{ gap: 10, marginTop: 'var(--s4)' }}>
            <a className="btn" href={`#/${PRODUCT_SLUG[product]}/cases`} style={{ textDecoration: 'none', padding: '11px 22px', border: '1px solid var(--line)', borderRadius: 10, fontWeight: 600, color: 'var(--ink)', background: '#fff' }}>All {PRODUCT_WORDS[product].cases.toLowerCase()}</a>
            <a className="btn" href="#/users" style={{ textDecoration: 'none', padding: '11px 22px', border: '1px solid var(--line)', borderRadius: 10, fontWeight: 600, color: 'var(--ink)', background: '#fff' }}>Users</a>
            <a className="btn" href="#/audit" style={{ textDecoration: 'none', padding: '11px 22px', border: '1px solid var(--line)', borderRadius: 10, fontWeight: 600, color: 'var(--ink)', background: '#fff' }}>Audit log</a>
          </div>
        </>
      )}
    </div>
  )
}
