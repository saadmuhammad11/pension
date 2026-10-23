/** The department must be told which papers to attach, not only that the case came back. */
import { describe, expect, it } from 'vitest'
import { returnedItems } from './returnedItems'

describe('what a return asked for', () => {
  it("reads the officer's ticks, which a return records under items", () => {
    // PC-2026-000031, returned by a Senior Auditor on 22 Oct 2026, verbatim.
    const payload = { items: [
      { id: 'AG-06', requirement: 'NADRA Family Registration Certificate/s, attested by the DDO', status: 'DEFECTIVE', note: '' },
      { id: 'AG-26', requirement: 'Proforma for qualifying service', status: 'MISSING', note: '' },
    ] }
    expect(returnedItems(payload).map(d => `${d.id} ${d.status}`)).toEqual(['AG-06 DEFECTIVE', 'AG-26 MISSING'])
  })

  it('reads a document the officer named in their own words, with its pages', () => {
    const payload = { items: [{ label: 'The second page of the service book', pages: [4, 5], note: 'illegible' }] }
    expect(returnedItems(payload)).toEqual([{ label: 'The second page of the service book', pages: [4, 5], note: 'illegible' }])
  })

  it('still reads missing_checklist, which is what the system wrote before 9 Oct 2026', () => {
    const payload = { missing_checklist: [{ id: 'AG-04', requirement: 'Pension Sanctioning Authority form', status: 'MISSING' }] }
    expect(returnedItems(payload).map(d => d.id)).toEqual(['AG-04'])
  })

  it('prefers items where a row carries both', () => {
    const payload = { items: [{ id: 'AG-02', requirement: 'CNICs' }], missing_checklist: [{ id: 'AG-99', requirement: 'stale' }] }
    expect(returnedItems(payload).map(d => d.id)).toEqual(['AG-02'])
  })

  it('a return with no list, and a payload that is not one, give nothing to draw', () => {
    for (const p of [undefined, {}, { items: [] }, { items: 'nonsense' }, { items: [null, {}, { note: 'no subject' }] }]) {
      expect(returnedItems(p as Record<string, unknown> | undefined)).toEqual([])
    }
  })
})
