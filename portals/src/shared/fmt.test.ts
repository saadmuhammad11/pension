import { describe, expect, it } from 'vitest'
import { fmtDate, fmtDateTime, money } from './fmt'

describe('fmt', () => {
  it('writes a moment the office way, without seconds', () => {
    expect(fmtDateTime('2026-10-09T11:16:31.123456')).toBe('09 Oct 2026, 11:16')
    expect(fmtDateTime('2026-10-09 11:16:31')).toBe('09 Oct 2026, 11:16')
    expect(fmtDateTime('')).toBe('')
    expect(fmtDateTime('now')).toBe('now')
    expect(fmtDate('2026-01-05')).toBe('05 Jan 2026')
  })
  it('writes an amount in rupees with grouping', () => {
    expect(money(1234567)).toBe('Rs 1,234,567')
    expect(money(null)).toBe('—')
  })
})
