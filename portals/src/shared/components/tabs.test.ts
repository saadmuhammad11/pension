import { describe, expect, it } from 'vitest'
import { nextTabFor, tabId } from './tabs'

describe('tab strip keys (F15)', () => {
  const tabs = ['Documents', 'AI findings', 'Remarks & history'] as const
  it('moves right and left, wrapping, and jumps with Home/End', () => {
    expect(nextTabFor(tabs, 'Documents', 'ArrowRight')).toBe('AI findings')
    expect(nextTabFor(tabs, 'Remarks & history', 'ArrowRight')).toBe('Documents')
    expect(nextTabFor(tabs, 'Documents', 'ArrowLeft')).toBe('Remarks & history')
    expect(nextTabFor(tabs, 'AI findings', 'Home')).toBe('Documents')
    expect(nextTabFor(tabs, 'AI findings', 'End')).toBe('Remarks & history')
    expect(nextTabFor(tabs, 'AI findings', 'Enter')).toBeNull()
  })
  it('names a tab and its panel the same way', () => expect(tabId('case-panel', 'AI findings')).toBe('case-panel-ai-findings'))
})
