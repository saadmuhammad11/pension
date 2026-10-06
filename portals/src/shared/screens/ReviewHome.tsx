/** AG Review: departments on the left, grouped by the Pension section that works them, with their
 *  queues; on the right the cases of the chosen section or department. */
import { useState } from 'react'
import { PRODUCT_WORDS, type DepartmentCount, type Product } from '../api/cases'
import { useInventory } from '../data/inventory'
import { DeptSidebar, type SidebarSelection } from '../components/DeptSidebar'
import { RegisterHome } from './RegisterHome'

export function ReviewHome({ product, view }: { product: Product; view?: 'dashboard' | 'cases' }) {
  const [selected, setSelected] = useState<SidebarSelection>(null)
  // The sidebar counts come with the product's inventory (shared/data/inventory.ts): the same
  // rows the "All departments" list shows, counted on the server -- they cannot disagree.
  const inv = useInventory({ product })
  const counts = (inv.data?.sidebar?.by_department ?? []) as DepartmentCount[]
  const error = inv.error

  const dept = selected?.kind === 'department' ? counts.find(c => c.code === selected.code) : null
  const section = selected?.kind === 'section' ? selected.name : null
  const sectionWord = section === 'LEGACY' ? 'Legacy cases' : section
  const title = dept ? dept.name : section ? `${PRODUCT_WORDS[product].cases} — ${sectionWord}` : `${PRODUCT_WORDS[product].cases} — all departments`
  const lead = dept ? `Cases submitted by ${dept.name}${dept.digital ? '' : ' through the Pension Facilitation Centre'}.`
    : section === 'LEGACY' ? 'Cases run on the old single-case portal, before departments and logins existed.'
    : section ? `Cases submitted by the departments ${section} section works. Select a department on the left, or a case below.`
    : 'Cases submitted by all departments. Select a section or a department on the left, or a case below.'
  return (
    <div className="container review-grid" style={{ paddingTop: 22 }}>
      <div className="review-side">
        {error && <div className="banner bad" style={{ marginBottom: 'var(--s3)' }}><span className="mark">!</span><div className="sub">{error}</div></div>}
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
