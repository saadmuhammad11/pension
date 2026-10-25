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

const day = (n: number) => { const d = new Date(); d.setDate(d.getDate() - n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }

const STATS = {
  users_by_role: { DEPT_OFFICER: 97, AG_SENIOR_AUDITOR: 21, ADMIN: 1 },
  admin: {
    users_total: 133, users_inactive: 1, must_change_password: 108, locked_out: 0,
    departments_without_user: 1, departments_total: 87, people_ever: 25,
    actors_by_day: [{ day: day(2), people: 20 }, { day: day(0), people: 3 }],
    sign_ins_by_day: [{ day: day(2), ok: 52, refused: 23 }, { day: day(0), ok: 3, refused: 0 }],
    runs_by_day: [{ day: day(5), done: 19, failed: 6 }, { day: day(0), done: 1, failed: 0 }],
    changes_by_action: [{ action: 'CHECKLIST_WAIVE', n: 45 }, { action: 'CASE_OVERRIDE', n: 2 }],
  },
} as unknown as Stats

describe('what the administrator is shown', () => {
  it('names the accounts that never set a password of their own', () => {
    render(<AdminCharts stats={STATS} />)
    expect(screen.getByText(/108 accounts \(81%\) still hold the password they were issued with/)).toBeTruthy()
  })

  it('says how many departments cannot file, under the chart it belongs to', () => {
    render(<AdminCharts stats={STATS} />)
    expect(screen.getByText(/1 department of 87 has no account and cannot file/)).toBeTruthy()
  })

  it('shows how many accounts have ever been used, not just how many exist', () => {
    render(<AdminCharts stats={STATS} />)
    expect(screen.getByText(/25 of 133 accounts have ever signed in/)).toBeTruthy()
  })

  it('gives the share of sign-ins refused, which a running total hides', () => {
    render(<AdminCharts stats={STATS} />)
    expect(screen.getByText(/last 7 days · 29% of attempts refused/)).toBeTruthy()
  })

  it('gives the share of examinations that failed', () => {
    render(<AdminCharts stats={STATS} />)
    expect(screen.getByText(/last 7 days · 23% failed/)).toBeTruthy()
  })

  it('reads the audit log in words, with signing in left out of it', () => {
    render(<AdminCharts stats={STATS} />)
    expect(screen.getByText('Checklist item waived')).toBeTruthy()
    expect(screen.getByText('Case decision overridden')).toBeTruthy()
    expect(screen.getByText(/47 entries on the audit log/)).toBeTruthy()
  })

  it('every card is a chart, not a figure standing on its own', () => {
    const { container } = render(<AdminCharts stats={STATS} />)
    const cards = container.querySelectorAll('.chart-card')
    expect(cards).toHaveLength(5)
    for (const c of cards) expect(c.querySelector('.chart-plot, .bars, svg, .split-bars')).toBeTruthy()
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
