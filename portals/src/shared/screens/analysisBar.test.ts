import { describe, expect, it } from 'vitest'
import { FULL, SPAN, STAGES, barTarget, nextShown, stageOf, type BarFacts } from './analysisBar'

/** The small benchmark case of 12 Oct 2026 as the stream reported it: 14 documents assembled,
 *  6 of them read in stage 6, the cross-checking 325 s of a 611 s run. */
const base = (over: Partial<BarFacts>): BarFacts => ({
  stage: 4, stageAt: 0, stageStepAt: 0, lastPageAt: 0, totalPages: 12, placed: {},
  docs: 14, facts6: 0, extracts: 2, ...over,
})

describe('the analysis bar (12 Oct 2026: stuck in the seventies, then a new screen)', () => {
  it('sizes the stages to how long they really take, in order, ending just short of full', () => {
    for (let i = 0; i < STAGES.length; i++) {
      const [from, to] = SPAN[i]
      expect(to).toBeGreaterThan(from)
      if (i > 0) expect(from).toBe(SPAN[i - 1][1])
    }
    expect(SPAN[0][0]).toBe(0)
    expect(SPAN[STAGES.length - 1][1]).toBe(FULL)
    // Cross-checking is about half the wait on every measured case; classification under a tenth.
    expect(SPAN[4][1] - SPAN[4][0]).toBeGreaterThanOrEqual(40)
    expect(SPAN[1][1] - SPAN[1][0]).toBeLessThanOrEqual(10)
    expect(stageOf('assertions')).toBe(4)
    expect(stageOf('report')).toBe(6)
  })

  it('does not stall near three quarters while stage 6 reads half the documents', () => {
    // Six documents read at a steady 50 s each, the seventh under way: the bar should be
    // past the middle of the stage and still moving, not held to 6/14 of it.
    const facts = base({ facts6: 6, stageAt: 0, stageStepAt: 250_000 })
    const t = barTarget(facts, 280_000, null)
    const [from, to] = SPAN[4]
    expect(t).toBeGreaterThan(from + 0.6 * (to - from))
    expect(t).toBeLessThan(to)
  })

  it('never goes backwards and never passes the stage it is in', () => {
    const facts = base({ facts6: 3, stageStepAt: 100_000 })
    let last = 0
    for (let now = 100_000; now < 2_000_000; now += 10_000) {
      const t = barTarget(facts, now, null)
      expect(t).toBeGreaterThanOrEqual(last)
      expect(t).toBeLessThan(SPAN[4][1])
      last = t
    }
  })

  it('climbs to the end once the run is done, a bounded step a second, so the findings never appear out of nowhere', () => {
    expect(barTarget(base({}), 0, 'done')).toBe(100)
    let shown = 76
    const ticks: number[] = []
    while (shown < FULL) { shown = nextShown(shown, 100, 'done'); ticks.push(shown) }
    expect(ticks.length).toBeLessThanOrEqual(12)                 // within the 12 s the screen allows
    expect(ticks.length).toBeGreaterThanOrEqual(4)               // and visibly, not in one leap
    for (let i = 1; i < ticks.length; i++) expect(ticks[i] - ticks[i - 1]).toBeLessThanOrEqual(5)
  })

  it('moves at most three points a second while the run is live, and never backwards', () => {
    expect(nextShown(40, 60, null)).toBe(43)
    expect(nextShown(59.5, 60, null)).toBe(60)
    expect(nextShown(60, 50, null)).toBe(60)
  })
})
