/** Every department with its queue, for AG Review, grouped by the Pension section of the AG office
 *  that works it (29 Sep 2026): "All departments" on top, then Pension-I to Pension-V as collapsible
 *  groups whose headers carry the section's own counts and select the whole section; departments
 *  inside alphabetical. The legacy bucket sits below the groups. Searchable, collapsible on phones. */
import { useEffect, useMemo, useState } from 'react'
import type { DepartmentCount } from '../api/cases'

export type SidebarSelection = { kind: 'department'; code: string } | { kind: 'section'; name: string } | null

const SECTION_ORDER = ['Pension-I', 'Pension-II', 'Pension-III', 'Pension-IV', 'Pension-V']
const LEGACY = 'LEGACY'
const STORE = 'pension.ag.sidebar.sections'

function readCollapsed(): Record<string, boolean> {
  try { return JSON.parse(sessionStorage.getItem(STORE) || '{}') } catch { return {} }
}

export function DeptSidebar(
  { counts, selected, onSelect }:
  { counts: DepartmentCount[]; selected: SidebarSelection; onSelect: (s: SidebarSelection) => void },
) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)                       // the phone drawer
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(readCollapsed)   // expanded by default
  useEffect(() => { try { sessionStorage.setItem(STORE, JSON.stringify(collapsed)) } catch { /* private window */ } }, [collapsed])

  const byName = (a: DepartmentCount, b: DepartmentCount) => a.name.localeCompare(b.name, 'en', { sensitivity: 'base' })
  const groups = useMemo(() => {
    const extra = [...new Set(counts.map(c => c.pension_section).filter((s): s is string => !!s))].filter(s => !SECTION_ORDER.includes(s)).sort()
    return [...SECTION_ORDER, ...extra].map(name => ({ name, depts: counts.filter(c => c.pension_section === name).sort(byName) })).filter(g => g.depts.length)
  }, [counts])
  const legacy = useMemo(() => counts.filter(c => !c.pension_section).sort(byName), [counts])

  const needle = q.trim().toLowerCase()
  const matches = (c: DepartmentCount) => !needle || c.name.toLowerCase().includes(needle) || c.code.toLowerCase().includes(needle)
    || (c.pension_section ?? '').toLowerCase().includes(needle)
  const shownGroups = groups.map(g => ({ ...g, depts: g.depts.filter(matches) })).filter(g => !needle || g.depts.length)
  const shownLegacy = legacy.filter(matches)

  const totalWaiting = counts.reduce((n, c) => n + c.awaiting_review, 0)
  const totalAll = counts.reduce((n, c) => n + c.total, 0)
  const currentLabel = selected?.kind === 'department' ? (counts.find(c => c.code === selected.code)?.name ?? selected.code)
    : selected?.kind === 'section' ? (selected.name === LEGACY ? 'Legacy cases' : selected.name) : 'All departments'
  const pick = (s: SidebarSelection) => { onSelect(s); setOpen(false) }
  const isSel = (sel: SidebarSelection) => !sel ? selected === null
    : sel.kind === 'department' ? selected?.kind === 'department' && selected.code === sel.code
    : selected?.kind === 'section' && selected.name === sel.name

  const row = (label: string, waiting: number, all: number, sel: SidebarSelection, cls = '') => {
    const active = isSel(sel)
    return (
      <button key={sel ? `${sel.kind}:${sel.kind === 'department' ? sel.code : sel.name}` : '*'} className={`dept-row${active ? ' is-active' : ''}${cls}`}
              onClick={() => pick(sel)} aria-current={active ? 'true' : undefined}>
        <span className="dept-name">{label}</span>
        {waiting > 0 && <span className="pill medium dept-waiting" title="Awaiting decision">{waiting}</span>}
        <span className="dept-total muted mono" title="All cases">{all}</span>
      </button>
    )
  }

  return (
    <nav className={`dept-sidebar${open ? ' is-open' : ''}`} aria-label="Departments">
      <button className="dept-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>{currentLabel}</span>
        <span className="muted" style={{ fontSize: 'var(--t-small)' }}>{open ? 'Hide list' : 'Change'}</span>
      </button>
      <div className="dept-body">
        <div className="label" style={{ padding: '0 10px 6px' }}>Departments</div>
        <input className="dept-search" placeholder="Search departments or sections" value={q} onChange={e => setQ(e.target.value)} aria-label="Search departments" />
        <div className="help" style={{ padding: '6px 10px 8px' }}>Awaiting decision · total cases</div>
        {row('All departments', totalWaiting, totalAll, null)}
        <div className="dept-rule" />
        <div className="dept-list">
          {shownGroups.map(g => {
            const waiting = g.depts.reduce((n, c) => n + c.awaiting_review, 0)
            const all = g.depts.reduce((n, c) => n + c.total, 0)
            const isOpen = needle ? true : !collapsed[g.name]
            const active = isSel({ kind: 'section', name: g.name })
            return (
              <section key={g.name} className={`dept-group${isOpen ? ' is-open' : ''}`}>
                <div className={`dept-group-head${active ? ' is-active' : ''}`}>
                  <button type="button" className="dept-caret" aria-label={`${isOpen ? 'Collapse' : 'Expand'} ${g.name}`} aria-expanded={isOpen}
                          onClick={() => setCollapsed({ ...collapsed, [g.name]: isOpen })}>{isOpen ? '▾' : '▸'}</button>
                  <button type="button" className={`dept-row dept-section${active ? ' is-active' : ''}`} onClick={() => pick({ kind: 'section', name: g.name })}
                          aria-current={active ? 'true' : undefined} title={`${g.depts.length} departments`}>
                    <span className="dept-name">{g.name}</span>
                    {waiting > 0 && <span className="pill medium dept-waiting" title="Awaiting decision">{waiting}</span>}
                    <span className="dept-total muted mono" title="All cases">{all}</span>
                  </button>
                </div>
                {isOpen && <div className="dept-group-body">
                  {g.depts.map(c => row(c.name, c.awaiting_review, c.total, { kind: 'department', code: c.code }, ' dept-in-group'))}
                </div>}
              </section>
            )
          })}
          {shownLegacy.length > 0 && <>
            <div className="dept-rule" />
            {shownLegacy.map(c => row(c.name, c.awaiting_review, c.total, { kind: 'section', name: LEGACY }))}
          </>}
          {shownGroups.length === 0 && shownLegacy.length === 0 && <div className="empty" style={{ padding: 12 }}>No department matches.</div>}
        </div>
      </div>
    </nav>
  )
}
