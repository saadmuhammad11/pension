/** The GP Fund frame's {gpfExpired: 1} reaches the case screen's handler while idle sign-out is off.
 *
 *  Audit of 12 Oct 2026: the only `message` listener that called gpfExpired() lived inside the
 *  idle-timeout effect, which returns at once while IDLE_MINUTES is 0 (session.ts, since 9 Oct),
 *  so the frame never recovered after its two-hour cookie lapsed. The provider now listens for
 *  as long as someone is signed in. */
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../portal', () => ({ portal: () => ({ slug: 'ag' }) }))
vi.mock('../../api/client', () => ({
  ApiError: class extends Error { status = 0 },
  get: () => Promise.resolve({
    user: { id: 'u1', username: 'ag.reviewer', display_name: 'AG desk', role: 'AG_REVIEWER', department_code: null,
            department_name: null, active: true, portal: 'ag' },
    capabilities: {},
  }),
  post: () => Promise.reject(new Error('not used here')),
  requestsInFlight: () => 0,
}))
vi.mock('../../data/inventory', () => ({ stopInventoryPolling: () => {} }))
vi.mock('../../router/hash', () => ({ navigate: () => {} }))
vi.mock('../media', () => ({ mediaToken: () => Promise.resolve(null), clearMediaToken: () => {} }))

import { AuthProvider, useSession } from '../AuthProvider'
import { onGpfExpired, registerGpfFrame } from '../frameActivity'
import { IDLE_MINUTES, setToken } from '../session'

function Probe() {
  const { user } = useSession()
  return <span>{user ? user.username : 'nobody'}</span>
}

/** What the frame posts (GP/backend/web/js/api.js), as the parent window receives it. jsdom's own
 *  window stands in for the frame's: readFrameMessage only asks that the source be a registered window. */
const expiredMessage = () => new MessageEvent('message', { data: { gpfExpired: 1 }, origin: window.location.origin, source: window })

describe('AuthProvider and the GP Fund frame', () => {
  beforeEach(() => setToken('session-secret'))
  afterEach(() => { setToken(null); vi.restoreAllMocks() })

  it('an expired-frame message reaches the registered handler with idle sign-out off', async () => {
    expect(IDLE_MINUTES).toBe(0)                     // the setting the listener used to be gated behind
    const expired = vi.fn()
    const unregister = registerGpfFrame(window)
    const off = onGpfExpired(expired)
    try {
      render(<AuthProvider><Probe /></AuthProvider>)
      await screen.findByText('ag.reviewer')         // signed in: the listener is up
      act(() => { window.dispatchEvent(expiredMessage()) })
      expect(expired).toHaveBeenCalledTimes(1)
      // Activity from the frame is harmless with no idle deadline to push.
      act(() => { window.dispatchEvent(new MessageEvent('message', { data: { gpfActivity: 1 }, origin: window.location.origin, source: window })) })
      expect(expired).toHaveBeenCalledTimes(1)
    } finally { off(); unregister() }
  })

  it('a window the case screen did not register is still ignored', async () => {
    const expired = vi.fn()
    const off = onGpfExpired(expired)
    try {
      render(<AuthProvider><Probe /></AuthProvider>)
      await screen.findByText('ag.reviewer')
      act(() => { window.dispatchEvent(expiredMessage()) })
      expect(expired).not.toHaveBeenCalled()
    } finally { off() }
  })

  it('nothing is heard before anyone is signed in', () => {
    setToken(null)
    const expired = vi.fn()
    const unregister = registerGpfFrame(window)
    const off = onGpfExpired(expired)
    try {
      render(<AuthProvider><Probe /></AuthProvider>)
      expect(screen.getByText('nobody')).toBeInTheDocument()
      act(() => { window.dispatchEvent(expiredMessage()) })
      expect(expired).not.toHaveBeenCalled()
    } finally { off(); unregister() }
  })
})
