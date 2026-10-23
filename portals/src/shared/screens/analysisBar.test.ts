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

describe('the bar does not stall when the count under-reads (23 Oct 2026)', () => {
  // Stage 4 is 46% of the bar, [48, 94]. Its denominator is a guess -- 0.55 of the assembled
  // documents -- and a case that states its facts in fewer documents than that ENDS the stage
  // with the count well short. The bar sat in the sixties and then climbed 30% in seconds.
  const facts = (over: Partial<BarFacts> = {}): BarFacts => ({
    stage: 4, stageAt: 0, stageStepAt: 0, lastPageAt: 0, totalPages: 12,
    placed: {}, docs: 40, facts6: 3, extracts: 0, ...over,
  })

  it('keeps climbing while the count stands still', () => {
    const f = facts({ stageAt: 0, stageStepAt: 60_000 })
    const at2min = barTarget(f, 120_000, null)
    const at6min = barTarget(f, 360_000, null)
    const at12min = barTarget(f, 720_000, null)
    expect(at6min).toBeGreaterThan(at2min + 2)
    expect(at12min).toBeGreaterThan(at6min + 2)
  })

  it('still never leaves its own stage', () => {
    const f = facts({ stageAt: 0, stageStepAt: 0 })
    expect(barTarget(f, 60 * 60_000, null)).toBeLessThan(94)
    expect(barTarget(f, 1000, null)).toBeGreaterThanOrEqual(48)
  })

  it('leaves a case the count reads correctly where it was: the count is ahead', () => {
    // Nine of ten documents cross-checked a few seconds ago: the count says ~0.9 of the way,
    // far beyond the clock's 1 - 1/(1 + 20/400).
    const f = facts({ docs: 20, facts6: 10, stageAt: 0, stageStepAt: 19_000 })
    const byClock = 48 + (94 - 48) * (1 - 1 / (1 + 20 / 400))
    expect(barTarget(f, 20_000, null)).toBeGreaterThan(byClock + 10)
  })

  it('finishing still takes it to the end', () => {
    expect(barTarget(facts(), 120_000, 'done')).toBe(100)
  })
})
