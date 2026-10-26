/** The GP Fund reading shows its shape, as the pension analysis does (26 Oct 2026).
 *
 *  The claim's own screen inside the frame has listed its stages since the beginning; the
 *  portal's progress card showed only the live line, so an officer watching a two-minute read
 *  could not tell a slow stage from a stuck one.
 */
import { describe, expect, it } from 'vitest'
import { GPF_STAGES, gpfPct, gpfStageAt } from './CaseDetail'

describe('the GP Fund stage list', () => {
  it('names every stage the module emits', () => {
    const covered = GPF_STAGES.flatMap(([, , keys]) => keys)
    for (const emitted of ['queued', 'ingest', 'classify', 'extract', 'page-done', 'illegible',
                           'assemble', 'done']) {
      expect(covered).toContain(emitted)
    }
  })

  it('walks forward in the order the module runs', () => {
    expect(gpfStageAt('ingest')).toBeLessThan(gpfStageAt('classify'))
    expect(gpfStageAt('classify')).toBeLessThan(gpfStageAt('extract'))
    expect(gpfStageAt('extract')).toBeLessThan(gpfStageAt('assemble'))
    expect(gpfStageAt('assemble')).toBeLessThan(gpfStageAt('done'))
  })

  it('treats the end of a page as reading, not a stage of its own', () => {
    // Every page cycles classify -> extract -> page-done, so a list following the raw stage
    // would walk its ticks backwards on every page of the claim.
    expect(gpfStageAt('page-done')).toBe(gpfStageAt('extract'))
  })

  it('a stage it has never heard of does not throw the list to the end', () => {
    expect(gpfStageAt('something-the-module-adds-later')).toBe(0)
  })

  it('every row says what it is doing while it is the one running', () => {
    for (const [name, sub] of GPF_STAGES) {
      expect(name.length).toBeGreaterThan(0)
      expect(sub.length).toBeGreaterThan(0)
    }
  })
})

describe('the stage list describes the run, not the page under the model', () => {
  /** What the module emits while eight pages are in its hands at once: page 3 is being
   *  classified while page 1 is being extracted and page 2 has just finished. Following the
   *  bare stage walks the ticks between the first three rows several times a second. */
  const BURST = ['classify', 'extract', 'page-done', 'classify', 'extract', 'classify',
                 'page-done', 'extract', 'classify']

  it('the raw stage really does go backwards, which is the thing to defend against', () => {
    const raw = BURST.map(gpfStageAt)
    expect(raw.some((v, i) => i > 0 && v < raw[i - 1])).toBe(true)
  })

  it('a high-water mark over the same burst never goes backwards', () => {
    let reached = 0
    const shown = BURST.map(st => (reached = Math.max(reached, gpfStageAt(st))))
    expect(shown.every((v, i) => i === 0 || v >= shown[i - 1])).toBe(true)
    expect(shown[shown.length - 1]).toBe(gpfStageAt('extract'))
  })

  it('and it still advances when the run genuinely moves on', () => {
    let reached = 0
    for (const st of [...BURST, 'assemble', 'done']) reached = Math.max(reached, gpfStageAt(st))
    expect(reached).toBe(gpfStageAt('done'))
  })
})

describe('how far the read has got', () => {
  /** PC-2026-000077, eight pages in the model's hands at once: the tick was already on
   *  "Reading the fields" while the bar sat at 0%, because the figure counted only pages
   *  FINISHED (26 Oct 2026). */
  it('moves as soon as a page is in the model\'s hands', () => {
    expect(gpfPct({ total: 6, done: 0, inFlight: 0, state: 'running' })).toBe(0)
    expect(gpfPct({ total: 6, done: 0, inFlight: 6, state: 'running' })).toBe(50)
  })

  it('never goes backwards as a page finishes', () => {
    // A page starting adds a half; the same page finishing adds the other half.
    const starting = gpfPct({ total: 6, done: 0, inFlight: 1, state: 'running' })
    const finished = gpfPct({ total: 6, done: 1, inFlight: 0, state: 'running' })
    expect(finished).toBeGreaterThan(starting)
  })

  it('never reaches the end while work is still out', () => {
    // done + inFlight <= total, so the most it can show mid-read is half the remainder.
    expect(gpfPct({ total: 6, done: 5, inFlight: 1, state: 'running' })).toBeLessThan(100)
  })

  it('and is complete only when the read is', () => {
    expect(gpfPct({ total: 6, done: 6, inFlight: 0, state: 'done' })).toBe(100)
  })

  it('says nothing before the module has counted the pages', () => {
    expect(gpfPct(null)).toBe(0)
    expect(gpfPct({ state: 'queued' })).toBe(0)
  })
})
