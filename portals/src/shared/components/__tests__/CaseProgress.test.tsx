/** The last step of the bar has to say what was decided (22 Oct 2026).
 *
 *  PC-2026-000032 was approved, and what the Agriculture DDO saw was four green ticks and the
 *  word "Decision". A rejection drew exactly the same four ticks: the bar carried the fact
 *  that the office had finished and not one word about how. */
import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { CaseProgress } from '../CaseProgress'
import type { CaseStatus } from '../../api/cases'

const last = (c: HTMLElement) => c.querySelectorAll('.progress-step')[c.querySelectorAll('.progress-step').length - 1]

function bar(status: CaseStatus, tier: Parameters<typeof CaseProgress>[0]['holderTier'] = null) {
  return render(<CaseProgress status={status} holderTier={tier} />).container
}

describe('CaseProgress', () => {
  it('an approved case ends on a green tick that says Approved', () => {
    const step = last(bar('APPROVED'))
    expect(step.className).toContain('is-done')
    expect(step.className).not.toContain('is-bad')
    expect(step.querySelector('.progress-dot')?.textContent).toBe('✓')
    expect(step.querySelector('.progress-sub')?.textContent).toBe('Approved')
  })

  it('a rejected case does not get the tick an approved one gets', () => {
    const step = last(bar('REJECTED'))
    expect(step.className).toContain('is-bad')
    expect(step.querySelector('.progress-dot')?.textContent).toBe('✕')
    expect(step.querySelector('.progress-sub')?.textContent).toBe('Rejected')
  })

  it('a returned case is not finished: a number, in red, and what is wanted', () => {
    const step = last(bar('RETURNED'))
    expect(step.className).toContain('is-bad')
    expect(step.className).not.toContain('is-done')
    expect(step.querySelector('.progress-dot')?.textContent).toBe('4')
    expect(step.querySelector('.progress-sub')?.textContent).toBe('Returned for correction')
  })

  it('a case still with the office leaves the decision blank, not ticked', () => {
    const c = bar('UNDER_REVIEW')
    const steps = [...c.querySelectorAll('.progress-step')]
    expect(steps.map(s => s.querySelector('.progress-dot')?.textContent)).toEqual(['✓', '✓', '3', '4'])
    expect(steps[2].querySelector('.progress-sub')?.textContent).toBe('Under review at AG Office')
    expect(last(c).querySelector('.progress-sub')).toBeNull()
  })

  it('only the step the case stands on says anything about status', () => {
    const c = bar('UNDER_REVIEW', 'ASSISTANT_AO')
    expect(c.querySelectorAll('.progress-sub')).toHaveLength(1)
    expect(c.querySelectorAll('.progress-step')[3].querySelector('.progress-sub')).not.toBeNull()
  })
})
