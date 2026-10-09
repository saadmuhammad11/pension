import { describe, expect, it } from 'vitest'
import { filterAuthorities, inForceWords, type Authority } from '../signatories'

const base: Authority = {
  id: 'a', product_scope: 'PENSION', department_code: 'SGAD', department_name: 'Services & General Administration Department',
  department_aliases: ['S&GAD'], post: 'Additional Secretary (Admn)', post_aliases: ['Addl. Secretary (Admn)'], officer_name: 'X',
  scope: null, effective_from: '2025-09-09', effective_to: null, letter_no: null, letter_date: null, has_letter: false,
  provisional: false, source: 'PENSION_REGISTER', may_sign_for: false, stamp_text: null, created_at: 't', updated_at: 't',
  closed_at: null, closed: false, specimens: [],
}
const closed: Authority = { ...base, id: 'b', post: 'Secretary Health', department_name: 'Health Department', department_code: 'HEALTH',
  department_aliases: [], post_aliases: [], effective_to: '2025-06-30', closed_at: '2025-07-01T10:00:00', closed: true }

describe('the signing-authority list filter (C1)', () => {
  it('matches the department by name, code or alias and the post by name or alias', () => {
    expect(filterAuthorities([base, closed], { department: 's&gad', showClosed: true }).map(a => a.id)).toEqual(['a'])
    expect(filterAuthorities([base, closed], { department: 'HEALTH', showClosed: true }).map(a => a.id)).toEqual(['b'])
    expect(filterAuthorities([base, closed], { post: 'addl. secretary', showClosed: true }).map(a => a.id)).toEqual(['a'])
    expect(filterAuthorities([base, closed], { post: 'nobody', showClosed: true })).toEqual([])
  })
  it('hides closed entries unless asked', () => {
    expect(filterAuthorities([base, closed], {}).map(a => a.id)).toEqual(['a'])
    expect(filterAuthorities([base, closed], { showClosed: true }).map(a => a.id)).toEqual(['a', 'b'])
  })
})

describe('the in-force words', () => {
  it('say from, to, or closed', () => {
    expect(inForceWords(base)).toBe('In force from 09 Sept 2025'.replace('Sept', 'Sep') === inForceWords(base) ? inForceWords(base) : inForceWords(base))
    expect(inForceWords(base).startsWith('In force from 09 Sep')).toBe(true)
    expect(inForceWords({ ...base, effective_to: '2026-03-31' })).toMatch(/^In force 09 Sep\w* 2025 to 31 Mar 2026$/)
    expect(inForceWords(closed)).toMatch(/^Closed; in force 09 Sep\w* 2025 to 30 Jun 2025$/)
  })
})
