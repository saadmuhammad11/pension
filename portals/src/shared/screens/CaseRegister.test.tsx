/** The register shows one face at a time (12 Oct 2026): the dashboard on its tab, the cases on
 *  theirs, never the dashboard appended below the cases. */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { CaseRegister } from './CaseRegister'
import { registerView } from './registerView'
import type { CaseStatus, Product } from '../api/cases'

beforeAll(() => {
  // jsdom has no matchMedia; the register asks it for the narrow layout.
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({ matches: false, media: query, addEventListener: () => {}, removeEventListener: () => {} }),
  })
})
afterEach(cleanup)

function draw(product: Product, view: 'dashboard' | 'cases', role = 'DEPT_OFFICER') {
  return render(
    <CaseRegister product={product} rows={[]} title="Register" lead="lead" waitingOn={[]} onOpen={() => {}}
                  onNew={() => {}} newLabel="New case" role={role} view={view}
                  charts={<div data-testid="charts">the figures</div>} />,
  )
}

describe('the register draws one face at a time', () => {
  for (const product of ['PENSION', 'GPF'] as Product[]) {
    it(`${product}: the cases view has the table and no dashboard figures`, () => {
      draw(product, 'cases')
      expect(screen.queryByTestId('charts')).toBeNull()
      expect(screen.getByRole('heading', { level: 1, name: 'Cases' })).toBeTruthy()
      expect(screen.getByRole('button', { name: 'New case' })).toBeTruthy()  // its own, not the header bar's
    })
    it(`${product}: the dashboard view has the figures and no table`, () => {
      draw(product, 'dashboard')
      expect(screen.getByTestId('charts')).toBeTruthy()
      expect(screen.queryByRole('heading', { level: 1, name: 'Cases' })).toBeNull()
    })
  }
  it('the AG register is unchanged: its cases view is the same clean table', () => {
    draw('PENSION', 'cases', 'AG_SENIOR_AUDITOR')
    expect(screen.queryByTestId('charts')).toBeNull()
    expect(screen.getByRole('heading', { level: 1, name: 'Cases' })).toBeTruthy()
  })
})

describe('which face an address shows (registerView)', () => {
  it("a department's home is its cases, and #/{slug}/cases is too", () => {
    expect(registerView('home', 'register')).toBe('cases')
    expect(registerView('cases', 'register')).toBe('cases')
    expect(registerView('dashboard', 'register')).toBe('dashboard')
  })
  it('the AG desk and the administrator open on the dashboard, as before', () => {
    expect(registerView('home', 'review')).toBe('dashboard')
    expect(registerView('home', 'admin')).toBe('dashboard')
    expect(registerView('cases', 'review')).toBe('cases')
    expect(registerView(undefined, 'review')).toBe('dashboard')
  })
})

describe('the new-case button belongs to the cases (22 Oct 2026)', () => {
  it('the cases draw it once; the dashboard draws none', () => {
    draw('PENSION', 'cases')
    expect(screen.getAllByRole('button', { name: 'New case' })).toHaveLength(1)
    cleanup()
    draw('PENSION', 'dashboard')
    expect(screen.queryByRole('button', { name: 'New case' })).toBeNull()
  })
  it('the AG register, which cannot file, draws none', () => {
    render(
      <CaseRegister product="PENSION" rows={[]} title="Register" lead="lead" waitingOn={[]} onOpen={() => {}}
                    role="AG_SENIOR_AUDITOR" view="cases" charts={null} />,
    )
    expect(screen.queryByRole('button', { name: /New case|File a/ })).toBeNull()
  })
})


describe('the cases tab is the whole register (24 Oct 2026)', () => {
  const rows = (n: number, status: CaseStatus, from = 0) => Array.from({ length: n }, (_, i) => ({
    id: `c${from + i}`, case_no: `PC-2026-${String(from + i).padStart(6, '0')}`, status,
    department_code: 'sgad', department_name: 'S&GAD', pension_section: 'Pension-I',
    created_via: 'DEPARTMENT', product: 'PENSION', submission_no: 1,
    created_at: '2026-10-01T00:00:00', updated_at: '2026-10-01T00:00:00',
  })) as unknown as Parameters<typeof CaseRegister>[0]['rows']

  const draw = (list: ReturnType<typeof rows>) => render(
    <CaseRegister product="PENSION" rows={list} title="Cases" lead="lead"
                  waitingOn={['FORWARDED', 'AI_FAILED', 'UNDER_REVIEW']} onOpen={() => {}}
                  role="AG_AO" view="cases" charts={null} />,
  )

  /** One row is the header. */
  const listed = () => screen.getAllByRole('row').length - 1

  it('shows every case, whatever is awaiting a decision', () => {
    // It opened on the AG's own tile and drew that slice: with nothing awaiting a decision
    // the table was empty, and the only word for it -- or for a slice of any other size --
    // was "Awaiting decision · 0 of 17 · show all" in small print above it.
    draw(rows(17, 'APPROVED'))
    expect(listed()).toBe(17)
  })

  it('and still every case when some do await one', () => {
    draw([...rows(5, 'UNDER_REVIEW'), ...rows(12, 'APPROVED', 5)] as ReturnType<typeof rows>)
    expect(listed()).toBe(17)
  })

  it('says neither which slice is shown nor how to escape it, because there is none', () => {
    const { container } = draw(rows(17, 'APPROVED'))
    expect(container.querySelector('.register-count')).toBeNull()
  })

  it('shows twenty on a page', () => {
    draw(rows(25, 'UNDER_REVIEW'))
    expect(screen.getByText(/1–20 of 25/)).toBeTruthy()
    expect(listed()).toBe(20)
  })
})

describe('whose filters the chips are (24 Oct 2026)', () => {
  const chip = (name: RegExp) => screen.queryByRole('button', { name })

  it("the Office is not offered a filter for a case the department has not sent", () => {
    render(<CaseRegister product="PENSION" rows={[]} title="Cases" lead="lead" waitingOn={[]}
                         onOpen={() => {}} role="AG_AO" view="cases" charts={null} />)
    expect(chip(/^Not yet submitted$/)).toBeNull()
    expect(chip(/^Awaiting decision$/)).toBeTruthy()   // the rest of the row is untouched
  })

  it('but the department, whose case it is, still is', () => {
    render(<CaseRegister product="PENSION" rows={[]} title="Cases" lead="lead" waitingOn={[]}
                         onOpen={() => {}} role="DEPT_OFFICER" view="cases" charts={null} />)
    expect(chip(/^Not yet submitted$/)).toBeTruthy()
  })
})

describe('a dashboard tile opens that list of cases (24 Oct 2026)', () => {
  const rows = [
    { id: 'a', case_no: 'PC-2026-000001', status: 'UNDER_REVIEW' },
    { id: 'b', case_no: 'PC-2026-000002', status: 'UNDER_REVIEW' },
    { id: 'c', case_no: 'PC-2026-000003', status: 'RETURNED' },
    { id: 'd', case_no: 'PC-2026-000004', status: 'APPROVED' },
  ].map(r => ({ ...r, department_code: 'sgad', department_name: 'S&GAD', pension_section: 'Pension-I',
                created_via: 'DEPARTMENT', product: 'PENSION', submission_no: 1,
                created_at: '2026-10-01T00:00:00', updated_at: '2026-10-01T00:00:00' })
  ) as unknown as Parameters<typeof CaseRegister>[0]['rows']

  /** Both faces at once, which is what lets one test press a tile and read the table. */
  const draw = () => render(
    <CaseRegister product="PENSION" rows={rows} title="Register" lead="lead"
                  waitingOn={['FORWARDED', 'AI_FAILED', 'UNDER_REVIEW']} onOpen={() => {}}
                  role="AG_AO" charts={null} />,
  )
  const listed = () => screen.getAllByRole('row').slice(1).map(r => r.textContent!.slice(0, 14))
  const tile = (name: RegExp) => screen.getByRole('tab', { name })

  it('opens on the whole register, pressing nothing', () => {
    draw()
    expect(listed()).toHaveLength(4)
  })

  it('"Awaiting decision" shows the cases awaiting a decision', () => {
    draw()
    fireEvent.click(tile(/Awaiting decision/))
    expect(listed()).toEqual(['PC-2026-000001', 'PC-2026-000002'])
  })

  it('"With the departments" shows the cases that are with them', () => {
    draw()
    fireEvent.click(tile(/With the departments/))
    expect(listed()).toEqual(['PC-2026-000003'])
  })

  it('and says which tile it is showing, where the other filters say so', () => {
    draw()
    fireEvent.click(tile(/With the departments/))
    expect(screen.getByRole('status').textContent).toBe('Showing 1 case · With the departments')
  })

  it('and the tile is cleared with the filters, not by small print of its own', () => {
    draw()
    fireEvent.click(tile(/Disposed/))
    expect(listed()).toEqual(['PC-2026-000004'])
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(listed()).toHaveLength(4)
  })
})

describe('the tile survives the move to the cases tab', () => {
  /** What the portal does: the same element, with `view` changed under it (PortalShell keys the
   *  register by product, so changing tab re-renders it rather than mounting a new one). If it
   *  ever remounts, the tile an officer pressed on the dashboard is forgotten on arrival. */
  it('a tile pressed on the dashboard is still the filter on the cases tab', () => {
    const rows = [
      { id: 'a', case_no: 'PC-2026-000001', status: 'UNDER_REVIEW' },
      { id: 'b', case_no: 'PC-2026-000002', status: 'RETURNED' },
    ].map(r => ({ ...r, department_code: 'sgad', department_name: 'S&GAD', pension_section: 'Pension-I',
                  created_via: 'DEPARTMENT', product: 'PENSION', submission_no: 1,
                  created_at: '2026-10-01T00:00:00', updated_at: '2026-10-01T00:00:00' })
    ) as unknown as Parameters<typeof CaseRegister>[0]['rows']
    const el = (view: 'dashboard' | 'cases') => (
      <CaseRegister product="PENSION" rows={rows} title="Register" lead="lead"
                    waitingOn={['FORWARDED', 'AI_FAILED', 'UNDER_REVIEW']} onOpen={() => {}}
                    role="AG_AO" charts={null} view={view} />
    )
    const { rerender } = render(el('dashboard'))
    fireEvent.click(screen.getByRole('tab', { name: /With the departments/ }))
    rerender(el('cases'))
    expect(screen.getAllByRole('row').slice(1).map(r => r.textContent!.slice(0, 14))).toEqual(['PC-2026-000002'])
    expect(screen.getByRole('status').textContent).toBe('Showing 1 case · With the departments')
  })
})

describe('a case nobody has examined is not a case awaiting a decision (26 Oct 2026)', () => {
  const mk = (n: number, status: CaseStatus, from = 0) => Array.from({ length: n }, (_, i) => ({
    id: `c${from + i}`, case_no: `PC-2026-${String(from + i).padStart(6, '0')}`, status,
    department_code: 'sgad', department_name: 'S&GAD', pension_section: 'Pension-I',
    created_via: 'DEPARTMENT', product: 'PENSION', submission_no: 1,
    created_at: '2026-10-01T00:00:00', updated_at: '2026-10-01T00:00:00',
  })) as unknown as Parameters<typeof CaseRegister>[0]['rows']

  /** Four received and not yet read; six read and waiting on an officer. */
  const ROWS = [...mk(4, 'FORWARDED'), ...mk(6, 'UNDER_REVIEW', 4)] as ReturnType<typeof mk>

  const draw = (role: string) => render(
    <CaseRegister product="PENSION" rows={ROWS} title="Cases" lead="lead"
                  waitingOn={['FORWARDED', 'AI_FAILED', 'UNDER_REVIEW']} onOpen={() => {}}
                  role={role} view="cases" charts={null} />,
  )
  const chip = (name: RegExp) => screen.queryByRole('button', { name })
  const listed = () => screen.getAllByRole('row').length - 1

  it('the Office is offered the two separately', () => {
    draw('AG_AO')
    expect(chip(/^Not yet examined$/)).toBeTruthy()
    expect(chip(/^Awaiting decision$/)).toBeTruthy()
  })

  it('"Not yet examined" is only the cases nobody has read', () => {
    draw('AG_AO')
    fireEvent.click(chip(/^Not yet examined$/)!)
    expect(listed()).toBe(4)
  })

  it('and "Awaiting decision" no longer sweeps them up', () => {
    // All ten used to answer to this chip, which read as ten officers' decisions pending.
    draw('AG_AO')
    fireEvent.click(chip(/^Awaiting decision$/)!)
    expect(listed()).toBe(6)
  })

  it('a department sees neither split: the case is simply with the Office', () => {
    draw('DEPT_OFFICER')
    expect(chip(/^Not yet examined$/)).toBeNull()
    const withAg = chip(/^With the AG$/)
    expect(withAg).toBeTruthy()
    fireEvent.click(withAg!)
    expect(listed()).toBe(10)          // everything on the Office's desk, as before
  })
})

describe('the dashboard counts the whole desk in one tile (26 Oct 2026)', () => {
  const mk = (n: number, status: CaseStatus, from = 0) => Array.from({ length: n }, (_, i) => ({
    id: `t${from + i}`, case_no: `PC-2026-${String(from + i).padStart(6, '0')}`, status,
    department_code: 'sgad', department_name: 'S&GAD', pension_section: 'Pension-I',
    created_via: 'DEPARTMENT', product: 'PENSION', submission_no: 1,
    created_at: '2026-10-01T00:00:00', updated_at: '2026-10-01T00:00:00',
  })) as unknown as Parameters<typeof CaseRegister>[0]['rows']

  const ROWS = [...mk(4, 'FORWARDED'), ...mk(6, 'UNDER_REVIEW', 4),
                ...mk(2, 'APPROVED', 10), ...mk(1, 'RETURNED', 12)] as ReturnType<typeof mk>

  /** Both faces, so a tile can be pressed and the table read. */
  const draw = (role: string) => render(
    <CaseRegister product="PENSION" rows={ROWS} title="Register" lead="lead"
                  waitingOn={['FORWARDED', 'AI_FAILED', 'UNDER_REVIEW']} onOpen={() => {}}
                  role={role} charts={null} />,
  )
  const tileOf = (name: RegExp) => screen.queryByRole('tab', { name })
  const listed = () => screen.getAllByRole('row').length - 1

  it('the unread cases have no tile of their own', () => {
    draw('AG_AO')
    expect(tileOf(/Not yet examined/)).toBeNull()
  })

  it('they are counted inside "Awaiting decision" rather than dropped', () => {
    // Four received and six examined: the tile is the ten cases on the desk, not six of them.
    draw('AG_AO')
    expect(tileOf(/Awaiting decision/)!.textContent).toContain('10')
  })

  it('pressing it shows the whole desk', () => {
    draw('AG_AO')
    fireEvent.click(tileOf(/Awaiting decision/)!)
    expect(listed()).toBe(10)
    expect(screen.getByRole('status').textContent).toBe('Showing 10 cases · Awaiting decision')
  })

  it('every case is still in exactly one tile', () => {
    draw('AG_AO')
    const n = (re: RegExp) => Number(tileOf(re)!.textContent!.match(/\d+/)![0])
    expect(n(/Awaiting decision/) + n(/With the departments/) + n(/Disposed/))
      .toBe(n(/All cases/))
  })

  it('a department sees the same four, and they still add up', () => {
    draw('DEPT_OFFICER')
    const n = (re: RegExp) => Number(tileOf(re)!.textContent!.match(/\d+/)![0])
    expect(n(/Action required/) + n(/With the Office/) + n(/Disposed/)).toBe(n(/All cases/))
  })

  it('but the register still offers the split as a chip', () => {
    // Removing the tile was a change to the FIGURES, not to the officer's working list.
    draw('AG_AO')
    expect(screen.queryByRole('button', { name: /^Not yet examined/ })).toBeTruthy()
  })
})
