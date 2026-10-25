/** The administrator's overview is about the administrator's work (25 Oct 2026).
 *
 *  It used to be the review desk's dashboard: six charts about decisions the administrator
 *  does not take. The figures that are theirs were on no screen -- accounts still on the
 *  password they were issued with, departments with nobody who can file, sign-in refusals,
 *  examinations that failed.
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { AdminCharts } from './AdminCharts'
import type { Stats } from '../../api/cases'

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (q: string) => ({ matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {} }),
  })
})
afterEach(cleanup)

const STATS = {
  users_by_role: { DEPT_OFFICER: 97, AG_SENIOR_AUDITOR: 21, ADMIN: 1 },
  audit_by_day: [{ day: '2026-10-24', n: 529 }],
  admin: {
    users_total: 133, users_inactive: 1, must_change_password: 108,
    locked_out: 0, sign_in_failures: 1,
    departments_without_user: Array.from({ length: 17 }, (_, i) => ({ code: `D${i}`, name: `Department ${i}` })),
    departments_total: 103, runs_failed: 2, runs_done: 70,
  },
} as unknown as Stats

describe('what the administrator is shown', () => {
  it('names the accounts that never set a password of their own', () => {
    render(<AdminCharts stats={STATS} />)
    expect(screen.getByText(/108 accounts \(81%\) still have the password they were issued with/)).toBeTruthy()
  })

  it('says which departments cannot file at all', () => {
    render(<AdminCharts stats={STATS} />)
    expect(screen.getByText('17 of 103 departments have no active account')).toBeTruthy()
    expect(screen.getByText('Department 0')).toBeTruthy()
    expect(screen.getByText('and 9 more')).toBeTruthy()          // eight listed, the rest counted
  })

  it('counts the examinations that failed, which is the administrator\'s errand', () => {
    render(<AdminCharts stats={STATS} />)
    expect(screen.getByText('2 of 72 runs in the last 14 days')).toBeTruthy()
  })

  it('shows sign-in refusals and whether anything is locked out', () => {
    render(<AdminCharts stats={STATS} />)
    expect(screen.getByText('Nothing is locked out.')).toBeTruthy()
  })

  it('draws the audit log it has always been sent and never showed', () => {
    render(<AdminCharts stats={STATS} />)
    expect(screen.getByText(/Recorded in the audit log/)).toBeTruthy()
  })

  it('draws none of the caseload charts the review desk gets', () => {
    render(<AdminCharts stats={STATS} />)
    for (const gone of [/Cases filed over time/, /Department caseload/, /Where cases are waiting/,
                        /Time to decision/, /Pending decisions by age/]) {
      expect(screen.queryByText(gone)).toBeNull()
    }
  })

  it('draws nothing at all for a user the server sends no admin figures for', () => {
    const { container } = render(<AdminCharts stats={{} as Stats} />)
    expect(container.firstChild).toBeNull()
  })
})
