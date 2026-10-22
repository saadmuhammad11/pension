// The progress bar shows the desks inside the Accountant General's office only to someone who
// is allowed to know which desk a case is on (22 Oct 2026).
//
// api/v2.py:673 nulls holder_tier for a department user on purpose -- "the DDO sees 'with the
// Accountant General', not which desk". When the three desks first became steps of their own,
// progressStep defaulted a null tier to SENIOR_AUDITOR, which showed a DDO the very thing the
// server withholds. A null tier now means the office, not a guess at the desk.
import { describe, expect, it } from 'vitest'
import { progressStep, progressSteps } from '../cases'

describe('progress steps', () => {
  it('shows the desks when the desk is known', () => {
    expect(progressSteps('SENIOR_AUDITOR')).toEqual([
      'Documents filed', 'Received', 'Senior Auditor',
      'Assistant Accounts Officer (AAO)', 'Accounts Officer (AO)', 'Decision',
    ])
  })

  it('shows the office, and no desk, when the desk is not known', () => {
    for (const tier of [null, undefined]) {
      expect(progressSteps(tier)).toEqual(
        ['Documents filed', 'Office of the Accountant General', 'Under review', 'Decision'])
      expect(progressSteps(tier)).not.toContain('Senior Auditor')
    }
  })

  it('a case under review stands on the desk holding it', () => {
    expect(progressStep('UNDER_REVIEW', 'SENIOR_AUDITOR')).toBe(2)
    expect(progressStep('UNDER_REVIEW', 'ASSISTANT_AO')).toBe(3)
    expect(progressStep('UNDER_REVIEW', 'AO')).toBe(4)
  })

  it('a department sees it with the office, never at a desk', () => {
    const at = progressStep('UNDER_REVIEW', null)
    expect(progressSteps(null)[at]).toBe('Under review')
  })

  it('submitted but not yet taken up is Received, not a desk', () => {
    expect(progressStep('FORWARDED', null)).toBe(1)
    expect(progressSteps('SENIOR_AUDITOR')[1]).toBe('Received')
  })

  it('a decided case is at the end of whichever bar is shown', () => {
    for (const tier of ['AO', null] as const) {
      const at = progressStep('APPROVED', tier)
      expect(at).toBe(progressSteps(tier).length - 1)
      expect(progressSteps(tier)[at]).toBe('Decision')
    }
  })

  it('a case not yet submitted is at the start, whoever is looking', () => {
    for (const tier of ['SENIOR_AUDITOR', null] as const) {
      expect(progressStep('DRAFT', tier)).toBe(0)
    }
  })
})
