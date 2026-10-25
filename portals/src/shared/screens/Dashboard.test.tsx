/** The charts show one thing each, at the grain the officer asks for (25 Oct 2026).
 *
 *  Two changes the office asked for. Every card carried a "Table" button that swapped the
 *  chart for its own figures -- a second way of reading the same card, on every card -- and
 *  it has gone. "Cases filed over time" was weekly and only weekly, which is the wrong grain
 *  at both ends: a week hides the day a batch arrived, and ten of them is too short a run to
 *  show a season. The button's place is now a period picker.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { Dashboard } from './Dashboard'
import type { Stats } from '../api/cases'

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (q: string) => ({ matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {} }),
  })
})
afterEach(cleanup)

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const ago = (n: number) => { const d = new Date(); d.setDate(d.getDate() - n); return iso(d) }

/** Three filings today, and one 40 days back -- inside a year, outside a ten-week window. */
const DAYS = [{ day: ago(40), filed: 1, decided: 0 }, { day: ago(0), filed: 3, decided: 0 }]

const STATS = {
  scope: { role: 'AG_AO', department: null }, total: 4,
  by_status: { DRAFT: 0, AI_CHECKING: 0, AI_FAILED: 0, AI_CHECKED: 0, FORWARDED: 0,
               UNDER_REVIEW: 4, APPROVED: 0, REJECTED: 0, RETURNED: 0, DOCS_REQUESTED: 0 },
  weeks: [{ week: ago(7), filed: 0, decided: 0 }, { week: ago(0), filed: 3, decided: 0 }],
  days: DAYS, by_department: [], verdicts: {}, high_flags: {}, checks_total: 0,
  avg_verification_minutes: null, avg_days_to_decision: null, decided_total: 0,
} as unknown as Stats

const draw = () => render(<Dashboard stats={STATS} variant="review" />)

describe('no chart offers a table of itself any more', () => {
  it('not one card draws the button', () => {
    draw()
    expect(screen.queryByRole('button', { name: /^Table$/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Chart$/ })).toBeNull()
  })
})

describe('cases filed over time, at the frequency the officer picks', () => {
  const picker = () => screen.getByRole('combobox', { name: /how often/i })

  it('offers daily, weekly and monthly', () => {
    draw()
    expect([...picker().querySelectorAll('option')].map(o => o.textContent))
      .toEqual(['Daily', 'Weekly', 'Monthly'])
  })

  it('opens on weekly, as it always was', () => {
    draw()
    expect((picker() as HTMLSelectElement).value).toBe('weekly')
    expect(screen.getByText(/last 10 weeks/)).toBeTruthy()
  })

  it('daily counts only what the last thirty days hold', () => {
    // The filing 40 days back falls outside, so three of the four cases are in view.
    draw()
    fireEvent.change(picker(), { target: { value: 'daily' } })
    expect(screen.getByText(/last 30 days · 3 cases/)).toBeTruthy()
  })

  it('monthly reaches back far enough to hold both', () => {
    draw()
    fireEvent.change(picker(), { target: { value: 'monthly' } })
    expect(screen.getByText(/last 12 months · 4 cases/)).toBeTruthy()
  })

  it('the newest column is named for the period, not dated', () => {
    draw()
    fireEvent.change(picker(), { target: { value: 'daily' } })
    expect(screen.getByText('today')).toBeTruthy()
    fireEvent.change(picker(), { target: { value: 'monthly' } })
    expect(screen.getByText('this month')).toBeTruthy()
  })
})

describe('a screen newer than its API still draws the card', () => {
  /** The day series arrived on 25 Oct 2026. Between deploying the portal and restarting the
   *  API, stats carried weeks and no days -- and the card drew an empty chart where the
   *  figures had been. It falls back to the weekly series it always had. */
  const WITHOUT_DAYS = { ...STATS, days: undefined } as unknown as Stats

  it('shows the weekly figures rather than nothing', () => {
    render(<Dashboard stats={WITHOUT_DAYS} variant="review" />)
    expect(screen.getByText(/last 10 weeks · 3 cases/)).toBeTruthy()
    expect(screen.queryByText('No case filed in this period.')).toBeNull()
  })

  it('and offers no period it cannot honour', () => {
    render(<Dashboard stats={WITHOUT_DAYS} variant="review" />)
    expect(screen.queryByRole('combobox', { name: /how often/i })).toBeNull()
  })
})
