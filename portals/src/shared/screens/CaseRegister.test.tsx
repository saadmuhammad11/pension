/** The register shows one face at a time (12 Oct 2026): the dashboard on its tab, the cases on
 *  theirs, never the dashboard appended below the cases. */
import { cleanup, render, screen } from '@testing-library/react'
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
