/** The AI verification as a stream of stage events, in the shapes AnalysisLive reads
 *  (the same message forms the real pipeline writes), timed for a demo: ~40 s end to end. */
import report from './data/report.json'

export interface DemoEvent { seq: number; at: string; stage: string; message: string; level?: 'warn' | 'error'; state?: string; delay: number }

const pages = (report as { pages: { page: number; document_type: string; confidence: number }[] }).pages
const docs = (report as { documents: { type: string; pages: number[] }[] }).documents

export function buildEvents(): DemoEvent[] {
  const out: Omit<DemoEvent, 'seq' | 'at'>[] = []
  const push = (stage: string, message: string, delay: number, extra: Partial<DemoEvent> = {}) => out.push({ stage, message, delay, ...extra })
  push('bundle', `bundle 94fe91578dec: Family Pension.pdf (12 pages, 15.1 MB)`, 400)
  push('ingest', `${pages.length} source pages rendered at 200 dpi; all legible`, 1400)
  push('ingest', 'fingerprint sha256 94fe91578dec… recorded on every finding', 700)
  for (const p of pages) {
    push('identify', `p. ${p.page} ${p.document_type} ${p.confidence.toFixed(2)}`, 900 + (p.page % 3) * 250)
  }
  push('identify', `${docs.length} documents assembled from ${pages.length} pages`, 900)
  push('classify', 'form text FORM_D_II p. 4 — second OCR reading of the prescribed form', 1600)
  push('classify', 'case type FAMILY_PENSION_DEATH_AFTER_RETIREMENT (0.98): signed Form D-II at p. 4', 1200)
  push('verify', 'form text ANNEX_A p. 5 — family list read a second time', 1300)
  for (const [doc, page] of [['FORM_D_II', 4], ['ANNEX_A', 5], ['NADRA_FRC', 6], ['CNIC', 2], ['BANK_OPTION_FORM', 7], ['NADRA_DEATH_CERTIFICATE', 10], ['PENSION_SLIP', 11]] as const) {
    push('extract', `stage 4 reading ${doc} p. ${page}`, 1500)
  }
  push('extract', 'pension Rs 82,575 · net pension Rs 82,575 · retired 20.06.2023 · died 03.07.2026', 1200)
  push('assertions', 'stage 6 CNIC 00001-0000112-2 stated by FORM_D_II p. 4, ANNEX_A p. 5, NADRA_FRC p. 6, BANK_OPTION_FORM p. 7 — agree', 1500)
  push('assertions', 'stage 6 deceased Akbar Hussain: FORM_D_II p. 4, NADRA_DEATH_CERTIFICATE p. 10, PENSION_SLIP p. 11 — agree', 1400)
  push('assertions', 'stage 6 family on ANNEX_A p. 5 against NADRA_FRC p. 6: 10 members, all matched', 1500)
  push('assertions', 'stage 6 NADRA_FRC p. 6 issued from another family member\'s seat — noted, LOW', 1100, { level: 'warn' })
  push('assertions', 'stage 6 recoveries: Form D-II declares nil; no demand found in the file', 1000)
  push('signatures', 'signature FORM_D_II p. 4 — Pension Sanctioning Authority, CPO Lahore; stamp beside it', 1800)
  push('signatures', 'specimen register: signing officer on file; match left to the desk', 1200)
  push('determine', 'rule pack PB-2024.12: family pension, death after retirement (D-II)', 1300)
  push('determine', 'provisional: BLOCKING-07 engaged — confirmation by the desk required (16 Sep 2026 decision)', 1200, { level: 'warn' })
  push('report', 'checklist 14 of 14 required documents present · 0 HIGH findings · recommendation HOLD', 1400)
  push('end', 'report written', 600, { state: 'done' })
  return out.map((e, i) => ({ ...e, seq: i + 1, at: new Date().toISOString().slice(0, 19) }))
}
