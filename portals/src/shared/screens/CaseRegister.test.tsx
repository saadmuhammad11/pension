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


describe('the register opens on something to look at', () => {
  const rows = (n: number, status: CaseStatus) => Array.from({ length: n }, (_, i) => ({
    id: `c${i}`, case_no: `PC-2026-${String(i).padStart(6, '0')}`, status,
    department_code: 'sgad', department_name: 'S&GAD', pension_section: 'Pension-I',
    created_via: 'DEPARTMENT', product: 'PENSION', submission_no: 1,
    created_at: '2026-10-01T00:00:00', updated_at: '2026-10-01T00:00:00',
  })) as unknown as Parameters<typeof CaseRegister>[0]['rows']

  /** The line beside the search box: which bucket is open, and how much of the register it is. */
  const counted = (container: HTMLElement) => container.querySelector('.register-count')!.textContent

  const draw = (list: ReturnType<typeof rows>) => render(
    <CaseRegister product="PENSION" rows={list} title="Cases" lead="lead"
                  waitingOn={['FORWARDED', 'AI_FAILED', 'UNDER_REVIEW']} onOpen={() => {}}
                  role="AG_AO" view="cases" charts={null} />,
  )

  it('shows the cases when nothing awaits a decision, instead of an empty table', () => {
    // 24 Oct 2026: it opened on "Awaiting decision · 0 of 17" with no rows under it, and the
    // only way through was the small "show all" beside the count.
    const { container } = draw(rows(17, 'APPROVED'))
    expect(counted(container)).toMatch(/^All cases · 17 of 17/)
    expect(screen.getAllByRole('row').length).toBeGreaterThan(1)
  })

  it('but still opens on the decisions when there are some', () => {
    const { container } = draw(rows(5, 'UNDER_REVIEW'))
    expect(counted(container)).toMatch(/^Awaiting decision · 5 of 5/)
  })

  it('shows twenty on a page', () => {
    draw(rows(25, 'UNDER_REVIEW'))
    expect(screen.getByRole('status').textContent).toMatch(/1–20 of 25/)
  })
})
