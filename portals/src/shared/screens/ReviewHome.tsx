/** AG Review: departments on the left, grouped by the Pension section that works them, with their
 *  queues; on the right the cases of the chosen section or department. */
import { useState } from 'react'
import { type DepartmentCount, type Product } from '../api/cases'
import { useInventory } from '../data/inventory'
import { DeptSidebar, type SidebarSelection } from '../components/DeptSidebar'
import { RegisterHome } from './RegisterHome'

export function ReviewHome({ product, view }: { product: Product; view?: 'dashboard' | 'cases' }) {
  const [selected, setSelected] = useState<SidebarSelection>(null)
  // The sidebar counts come with the product's inventory (shared/data/inventory.ts): the same
  // rows the "All departments" list shows, counted on the server -- they cannot disagree.
  const inv = useInventory({ product })
  const counts = (inv.data?.sidebar?.by_department ?? []) as DepartmentCount[]
  const error = inv.stale ? null : inv.error

  const dept = selected?.kind === 'department' ? counts.find(c => c.code === selected.code) : null
  const section = selected?.kind === 'section' ? selected.name : null
  const sectionWord = section === 'LEGACY' ? 'Legacy cases' : section
  // The scope, and only the scope (22 Oct 2026). The heading named the register as well --
  // "Pension cases — all departments", then "Pension cases, all departments" -- and the
  // register is the one thing on the screen the officer cannot be in doubt about: Pension or
  // GP Fund is the tab they pressed to get here, it is underlined in the header above, and the
  // lead below says it again. What the heading has to say is which cases of it these are.
  // A department selected on the left has always been named on its own; the rest now are too.
  const title = dept ? dept.name : sectionWord ?? 'All departments'
  const lead = dept ? `Cases submitted by ${dept.name}${dept.digital ? '' : ' through the Pension Facilitation Centre'}.`
    : section === 'LEGACY' ? 'Cases run on the old single-case portal, before departments and logins existed.'
    : section ? `Cases submitted by the departments ${section} section works. Select a department on the left, or a case below.`
    : 'Cases submitted by all departments. Select a section or a department on the left, or a case below.'
  return (
    <div className="container review-grid" style={{ paddingTop: 22 }}>
      <div className="review-side">
        {error && <div className="banner bad" style={{ marginBottom: 'var(--s3)' }}><span className="mark">!</span><div className="sub">{error}</div></div>}
        {inv.stale && <div className="muted" role="status" style={{ marginBottom: 'var(--s3)', fontSize: 'var(--t-small)' }}>Connection lost — retrying. The list shows what was last received.</div>}
        <DeptSidebar counts={counts} selected={selected} onSelect={setSelected} />
      </div>
      <div style={{ minWidth: 0 }}>
        <RegisterHome product={product} title={title} lead={lead}
          waitingOn={['FORWARDED', 'AI_FAILED', 'UNDER_REVIEW']} showDepartment={!dept}
          department={dept ? dept.code : null} section={section} charts="review" view={view} />
      </div>
    </div>
  )
}
