/** F11: any HTTP answer means online; only network-level failure of every probe means an outage. */
import { describe, expect, it, vi } from 'vitest'
import { checkApiOnline } from '../apiOnline'

describe('checkApiOnline', () => {
  it('treats a 503 (degraded) as online', async () => {
    const f = vi.fn(() => Promise.resolve(new Response('{"ok":false}', { status: 503 }))) as unknown as typeof fetch
    expect(await checkApiOnline({ fetchImpl: f, gapMs: 0 })).toBe(true)
    expect(f).toHaveBeenCalledTimes(1)
  })
  it('calls it an outage only when every probe fails at the network level', async () => {
    const f = vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))) as unknown as typeof fetch
    expect(await checkApiOnline({ fetchImpl: f, gapMs: 0, attempts: 3 })).toBe(false)
    expect(f).toHaveBeenCalledTimes(3)
  })
  it('one dropped probe followed by an answer is online', async () => {
    let n = 0
    const f = vi.fn(() => (++n === 1 ? Promise.reject(new TypeError('x')) : Promise.resolve(new Response('', { status: 200 })))) as unknown as typeof fetch
    expect(await checkApiOnline({ fetchImpl: f, gapMs: 0 })).toBe(true)
  })
})
