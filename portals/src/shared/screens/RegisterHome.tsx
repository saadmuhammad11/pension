/** The register, fed from the server every few seconds so a status change shows without a reload. */
import { type CaseStatus, type Product, caseHref } from '../api/cases'
import { useInventory } from '../data/inventory'
import { navigate } from '../router/hash'
import { useSession } from '../auth/AuthProvider'
import { CaseRegister } from './CaseRegister'
import { Dashboard, useStats } from './Dashboard'

export function RegisterHome(
  { product, title, lead, waitingOn, newLabel, showDepartment, onNew, department, section, charts = 'department', view }:
  { product: Product; title: string; lead: string; waitingOn: CaseStatus[]; newLabel?: string; showDepartment?: boolean
    onNew?: () => void; department?: string | null
    /** A Pension section (Pension-I .. V, or LEGACY): the cases of all its departments. */
    section?: string | null
    charts?: 'department' | 'review' | 'admin' | null; view?: 'dashboard' | 'cases' },
) {
  const { user } = useSession()
  // The shared inventory (shared/data/inventory.ts): the same rows and server-side counts every
  // other view of this product reads, refetched together whenever anything changes.
  const inv = useInventory({ product, department, section })
  const rows = inv.data?.rows ?? []
  // Rows already on screen stay; a failed refresh is a quiet strip, not a red error (F12).
  const error = inv.stale ? null : inv.error
  const stale = inv.stale
  const loading = inv.loading
  // The cases view draws no chart, so it asks for no statistics (F16).
  const { stats, error: statsError } = useStats(department, product, section, !!charts && view !== 'cases')

  return (
    <CaseRegister product={product} rows={rows} title={title} lead={lead} waitingOn={waitingOn} newLabel={newLabel}
                  showDepartment={showDepartment} onOpen={id => navigate(caseHref(product, id))} onNew={onNew}
                  statusCounts={inv.data?.counts.by_status} total={inv.data?.counts.total}
                  error={error} stale={stale} loading={loading} role={user?.role ?? ''} view={view}
                  charts={charts ? <Dashboard stats={stats} error={statsError} variant={charts} department={department} /> : null} />
  )
}
