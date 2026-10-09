import { describe, expect, it } from 'vitest'
import { DISPOSITION_WORDS, clearsLastOpenFinding } from './CaseFindings'

describe('the last open finding (F4)', () => {
  const flags = [{ id: 'F1' }, { id: 'F2' }, { id: 'F3' }]
  it('is the one whose clearing leaves nothing open', () => {
    const disposed = { F1: { action: 'WAIVE' }, F2: { action: 'WAIVE' } }
    expect(clearsLastOpenFinding(flags, disposed, 'F3', 'WAIVE')).toBe(true)
    expect(clearsLastOpenFinding(flags, { F1: { action: 'WAIVE' } }, 'F3', 'WAIVE')).toBe(false)
  })
  it('an upheld finding still stands, so upholding never clears the last one', () => {
    const disposed = { F1: { action: 'WAIVE' }, F2: { action: 'UPHOLD' } }
    expect(clearsLastOpenFinding(flags, disposed, 'F3', 'WAIVE')).toBe(false)
    expect(clearsLastOpenFinding(flags, { F1: { action: 'WAIVE' }, F2: { action: 'WAIVE' } }, 'F3', 'UPHOLD')).toBe(false)
  })
  it('the labels say what happens, not "approve" or "return"', () => {
    expect(DISPOSITION_WORDS.UPHOLD).toContain('the finding stands')
    expect(DISPOSITION_WORDS.UPHOLD).not.toContain('return')
  })
})
