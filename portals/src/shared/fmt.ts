/** One way to write a moment and an amount, for every screen (frontend review F17, 9 Oct 2026).
 *
 *  Dates as the office writes them -- "09 Oct 2026, 11:16" -- from the API's ISO strings; the
 *  seconds and the microseconds the server keeps are not shown. Amounts in rupees with the
 *  grouping the office uses; the same words the GP Fund page uses (GP/backend/web/js/ui.js). */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-10-09T11:16:31.123456" → "09 Oct 2026, 11:16". Anything unparseable comes back as given. */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso)
  if (!m) return iso
  const month = MONTHS[Number(m[2]) - 1]
  if (!month) return iso
  return `${m[3]} ${month} ${m[1]}, ${m[4]}:${m[5]}`
}

/** "2026-10-09" (or a full ISO moment) → "09 Oct 2026". */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  const month = m ? MONTHS[Number(m[2]) - 1] : undefined
  return m && month ? `${m[3]} ${month} ${m[1]}` : iso
}

/** Whole rupees with thousands grouping: 1234567 → "1,234,567". */
export function fmtAmount(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return Math.round(n).toLocaleString('en-PK')
}

/** "Rs 1,234,567" -- the office's way of writing an amount. */
export function money(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `Rs ${fmtAmount(n)}`
}
