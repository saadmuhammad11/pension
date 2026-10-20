import { describe, expect, it } from 'vitest'
import { fmtDate, fmtDateTime, mmss, money } from './fmt'

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

describe('mmss', () => {
  // The elapsed clock on the pension analysis screen and on the GP Fund examination. One
  // definition so the two show the same thing the same way (20 Oct 2026).
  it('reads as minutes and seconds', () => {
    expect(mmss(0)).toBe('0:00')
    expect(mmss(9)).toBe('0:09')
    expect(mmss(59.9)).toBe('0:59')
    expect(mmss(60)).toBe('1:00')
    expect(mmss(125)).toBe('2:05')
    expect(mmss(3600)).toBe('60:00')
  })

  it('never shows a negative time', () => {
    // The module serves elapsed, but a clock that went backwards must not print "-1:-5".
    expect(mmss(-4)).toBe('0:00')
  })
})
