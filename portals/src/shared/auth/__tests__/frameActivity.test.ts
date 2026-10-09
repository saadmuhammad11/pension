/** F9: only the GP Fund frame's own messages, from this origin, count as activity. */
import { describe, expect, it } from 'vitest'
import { readFrameMessage } from '../frameActivity'

describe('readFrameMessage', () => {
  const frame = {} as Window
  const known = new Set<Window>([frame])
  it('accepts activity and expiry from the registered frame at this origin', () => {
    expect(readFrameMessage({ origin: 'https://p', source: frame, data: { gpfActivity: 1 } }, 'https://p', known)).toEqual({ kind: 'activity' })
    expect(readFrameMessage({ origin: 'https://p', source: frame, data: { gpfExpired: 1 } }, 'https://p', known)).toEqual({ kind: 'expired' })
  })
  it('ignores another origin, another window, and other shapes', () => {
    expect(readFrameMessage({ origin: 'https://evil', source: frame, data: { gpfActivity: 1 } }, 'https://p', known)).toBeNull()
    expect(readFrameMessage({ origin: 'https://p', source: {} as Window, data: { gpfActivity: 1 } }, 'https://p', known)).toBeNull()
    expect(readFrameMessage({ origin: 'https://p', source: frame, data: 'gpfActivity' }, 'https://p', known)).toBeNull()
    expect(readFrameMessage({ origin: 'https://p', source: frame, data: { gpfHeight: 900 } }, 'https://p', known)).toBeNull()
  })
})
