/** The register shows one face at a time (12 Oct 2026): the dashboard on its tab, the cases on
 *  theirs, never the dashboard appended below the cases. */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { CaseRegister } from './CaseRegister'
import { registerView } from './registerView'
import type { Product } from '../api/cases'

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
