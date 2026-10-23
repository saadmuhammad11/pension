/** What the Accountant General asked for when the case was sent back.
 *
 *  The department's screen read `payload.missing_checklist` off the RETURN event and found
 *  nothing, every time, because that is not the key a return writes (23 Oct 2026). A Senior
 *  Auditor returning a case ticks the lines that are missing or defective and may name a
 *  document in their own words, and api/v2.py records the lot under `items`:
 *
 *      {"items": [{"id": "AG-06", "requirement": "NADRA Family Registration Certificate/s,
 *                  attested by the DDO", "status": "DEFECTIVE", "note": ""}, ...]}
 *
 *  So the DDO was shown the officer's remark and not one word about which papers to attach --
 *  on PC-2026-000031 the officer ticked two lines, on PC-2026-000042 five, and the department
 *  saw none of them. `missing_checklist` is what the system wrote when it returned cases by
 *  itself, before 9 Oct 2026, and old rows still carry it, so both keys are read.
 *
 *  This is the same normalisation api/rounds.py does server-side for the rounds panel; the two
 *  disagreeing is what hid the list in the first place, and the shapes are kept in step here.
 */
export interface ReturnedItem {
  /** A checklist line: AG-06 and its requirement. */
  id?: string
  requirement?: string
  /** MISSING, or DEFECTIVE where a copy was filed and is not good enough. */
  status?: string
  /** A document the officer named in their own words instead of ticking a line. */
  label?: string
  pages?: number[]
  /** What the officer wrote about this one item, as against the remark on the whole case. */
  note?: string
}

export function returnedItems(payload: Record<string, unknown> | undefined): ReturnedItem[] {
  const p = (payload ?? {}) as { items?: unknown; missing_checklist?: unknown }
  const rows = Array.isArray(p.items) && p.items.length ? p.items
    : Array.isArray(p.missing_checklist) ? p.missing_checklist : []
  return (rows as ReturnedItem[]).filter(
    r => !!r && typeof r === 'object' && (!!r.id || !!r.label || !!r.pages?.length))
}
