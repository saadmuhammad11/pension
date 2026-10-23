/** The progress bar of the AI Analysis screen, as arithmetic (AnalysisLive renders it).
 *
 * The bar is driven by real progress -- page 7 of 15 is 7/15 of the reading stage, document
 * 3 of 8 of the cross-checking -- eases forward between two events, never past the start of a
 * stage that has not started, and never goes backwards. Kept apart from the screen so the
 * arithmetic can be tested against what real runs report.
 */

/** The stages as the officer knows them (BUILD §5), and the pipeline ids each covers. */
export const STAGES: [string, string, string[]][] = [
  ['Ingest & page triage', 'Separating and checking the scanned pages', ['bundle', 'ingest']],
  ['Document classification', 'Identifying every document in the bundle', ['identify']],
  ['OCR & layout parsing', 'Reading each prescribed form a second time', ['verify', 'assemble', 'classify']],
  ['Field extraction', 'Reading the details off each document', ['extract']],
  ['Checklist & consistency', 'Checking every document against the others', ['assertions']],
  ['Identity', 'The sanctioning signature against the specimen', ['signatures']],
  ['Findings & recommendation', 'Writing up what was found', ['determine', 'report']],
]

/** Where each stage sits on the bar, [from, to] percent, sized to how long it really takes.
 *
 *  Measured on the three benchmark cases of 12 Oct 2026 (12, 29 and 43 pages; tools/bench.py):
 *  ingest 1-3% of the wait, classification 4-6%, the OCR second reading and assembly 10-14%,
 *  field extraction 26-37%, cross-checking 47-53%, the signature and the findings under 3%.
 *  The earlier spans gave classification 42% of the bar, so the bar raced to 47% in the first
 *  minute and then crawled for the next ten. */
export const SPAN: Record<number, [number, number]> = {
  0: [0, 3], 1: [3, 10], 2: [10, 21], 3: [21, 48], 4: [48, 94], 5: [94, 97], 6: [97, 99.5],
}
/** Seconds a stage with no page count usually takes -- how fast the bar creeps inside it. */
export const TAU: Record<number, number> = { 0: 15, 1: 60, 2: 70, 3: 180, 4: 400, 5: 12, 6: 10 }

/** Stage 6 reads the documents that state a fact the rules need -- about half of those
 *  assembled (6 of 14, 13 of 26 and 28 of 51 on the benchmark cases), never all of them. The
 *  bar used every assembled document as the denominator and so stalled near three quarters. */
export const SHARE_OF_DOCUMENTS_CROSS_CHECKED = 0.55

/** How far the bar may move in one second: a stage that ends sooner than its share of the
 *  bar is caught up over seconds, not in one leap; and once the run is done the climb to the
 *  end is quicker, so the findings are not kept waiting. */
export const STEP_PER_SECOND = 3
export const STEP_PER_SECOND_WHEN_DONE = 5
/** The bar counts as full from here: the findings open once it is. */
export const FULL = 99.5

export function stageOf(id: string): number {
  return STAGES.findIndex(([, , keys]) => keys.includes(id))
}

/** What the stream has said so far, as facts (AnalysisLive derives them from the events). */
export interface BarFacts {
  stage: number
  stageAt: number
  stageStepAt: number
  lastPageAt: number
  totalPages: number
  placed: Record<number, unknown>
  docs: number
  facts6: number
  extracts: number
}

/** Where the bar should be now, in percent. */
export function barTarget(facts: BarFacts, now: number, finished: string | null): number {
  if (finished) return 100
  const [from, to] = SPAN[facts.stage]
  const range = to - from
  const since = (now - facts.stageAt) / 1000
  let frac: number
  if (facts.stage === 1 && facts.totalPages > 0) {
    const read = Object.keys(facts.placed).length
    const perPage = read > 1 ? Math.max(2, (facts.lastPageAt - facts.stageAt) / 1000 / read) : 12
    const between = 1 - Math.exp(-((now - facts.lastPageAt) / 1000) / perPage)
    frac = Math.min(0.985, (read + 0.85 * between) / facts.totalPages)
  } else if ((facts.stage === 4 && facts.docs > 0) || (facts.stage === 3 && facts.extracts > 0)) {
    // One document at a time, like the pages: n of the file's documents started, and between
    // two of them, forward at the pace this case has shown so far.
    const n = facts.stage === 4 ? facts.facts6 : facts.extracts
    const of = facts.stage === 4
      ? Math.max(Math.round(facts.docs * SHARE_OF_DOCUMENTS_CROSS_CHECKED), n + 1)
      : Math.max(3, n + 1)
    const perDoc = n > 1 ? Math.max(8, (facts.stageStepAt - facts.stageAt) / 1000 / (n - 1)) : TAU[facts.stage] / 3
    const onThis = (now - facts.stageStepAt) / 1000
    const between = onThis / (onThis + perDoc)          // never reaches 1, never stops
    // Whichever evidence is further along: the count, or the clock (23 Oct 2026).
    //
    // The count alone could stall. Its denominator is a guess -- SHARE_OF_DOCUMENTS_CROSS_
    // CHECKED of the assembled documents -- and where a case states its facts in fewer
    // documents than that, the stage ENDS with the count well short of its denominator. Stage
    // 4 is 46% of the bar, so the bar sat in the sixties for minutes and then climbed 30% in
    // seconds when the next stage started: "stuck at a percent and suddenly spikes till the
    // end very fast". The clock cannot stall -- 1 - 1/(1 + t/TAU) rises forever -- so taking
    // the larger of the two keeps the bar moving on a case the count under-reads, and leaves
    // it exactly as it was on a case the count reads correctly, where the count is ahead.
    const byCount = (Math.max(0, n - 1) + between) / of
    const byClock = 1 - 1 / (1 + since / TAU[facts.stage])
    frac = Math.min(0.985, Math.max(byCount, byClock))
  } else {
    // No count to go by: forward on a curve that slows but never stops.
    frac = 1 - 1 / (1 + since / TAU[facts.stage])
  }
  return from + range * Math.min(frac, 0.985)
}

/** The next value on screen: toward the target, never backwards, a bounded step a second. */
export function nextShown(shown: number, target: number, finished: string | null): number {
  const gap = target - shown
  if (gap <= 0.01) return shown
  return shown + Math.min(gap, finished ? STEP_PER_SECOND_WHEN_DONE : STEP_PER_SECOND)
}
