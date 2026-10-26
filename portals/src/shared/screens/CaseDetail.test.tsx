/** The GP Fund reading shows its shape, as the pension analysis does (26 Oct 2026).
 *
 *  The claim's own screen inside the frame has listed its stages since the beginning; the
 *  portal's progress card showed only the live line, so an officer watching a two-minute read
 *  could not tell a slow stage from a stuck one.
 */
import { describe, expect, it } from 'vitest'
import { GPF_STAGES, gpfStageAt } from './CaseDetail'

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
