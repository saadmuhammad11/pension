import { describe, expect, it } from 'vitest'
import { POLL_ACTIVE_MS, POLL_QUIET_MS, pollInterval } from './inventory'

describe('pollInterval (F16)', () => {
  it('polls every 3 s while the officer is at a visible tab', () => expect(pollInterval(false, 5_000)).toBe(POLL_ACTIVE_MS))
  it('backs off to 15 s when the tab is hidden or idle for a minute', () => {
    expect(pollInterval(true, 0)).toBe(POLL_QUIET_MS)
    expect(pollInterval(false, 61_000)).toBe(POLL_QUIET_MS)
  })
})
