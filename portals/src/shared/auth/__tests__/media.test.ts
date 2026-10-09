/** F10: image and stream addresses carry a short-lived media token, never the session token. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../portal', () => ({ portal: () => ({ slug: 'ag' }) }))

import { clearMediaToken, currentMediaToken, mediaToken, mediaTokenRejected, withMediaToken } from '../media'
import { setToken, withToken } from '../session'

describe('media token', () => {
  beforeEach(() => { setToken('session-secret'); clearMediaToken() })
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); setToken(null); clearMediaToken() })

  it('fetches a media token with the session and puts THAT on the URL, not the session token', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ token: 'media-1', expires_in: 900 }), { status: 200 })))
    vi.stubGlobal('fetch', fetchMock)
    expect(await mediaToken()).toBe('media-1')
    expect(fetchMock).toHaveBeenCalledWith('/api/v2/auth/media-token', expect.objectContaining({ headers: { Authorization: 'Bearer session-secret' } }))
    const url = withToken('/api/v2/runs/r1/pages/3')
    expect(url).toBe('/api/v2/runs/r1/pages/3?token=media-1')
    expect(url).not.toContain('session-secret')
  })

  it('answers the bare address while no token is held, and asks for one', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ token: 'media-2', expires_in: 900 }), { status: 200 })))
    vi.stubGlobal('fetch', fetchMock)
    expect(withMediaToken('/x')).toBe('/x')
    await mediaToken()
    expect(withMediaToken('/x')).toBe('/x?token=media-2')
  })

  it('a refused image forgets the token and fetches another', async () => {
    let n = 0
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify({ token: `media-${++n}`, expires_in: 900 }), { status: 200 }))))
    await mediaToken()
    expect(currentMediaToken()).toBe('media-1')
    await mediaTokenRejected()
    expect(currentMediaToken()).toBe('media-2')
  })

  it('without a session there is no media token and no request', async () => {
    setToken(null)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    expect(await mediaToken()).toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
