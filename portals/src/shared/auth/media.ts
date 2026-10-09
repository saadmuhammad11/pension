/** A short-lived token for the addresses that cannot carry a header: page images, signature
 *  cut-outs, the run's event stream (frontend review F10, 9 Oct 2026).
 *
 *  Until then those URLs carried the 12-hour session token, and the browser's cache kept them.
 *  The server now issues a separate media token (scope "media", 15 minutes, GET only, accepted on
 *  the image and event routes alone) from GET /api/v2/auth/media-token. It is fetched when the
 *  session starts, refreshed well before it expires, and refetched at once when an image comes
 *  back 401 (`mediaTokenRejected`). A session token never goes on a URL any more. */
import { getToken, unauthorised } from './session'

const REFRESH_AHEAD_MS = 3 * 60_000           // refresh three minutes before expiry
let token: string | null = null
let expiresAt = 0
let pending: Promise<string | null> | null = null
let timer: ReturnType<typeof setTimeout> | null = null
const listeners = new Set<() => void>()

export function currentMediaToken(): string | null {
  return token && Date.now() < expiresAt ? token : null
}

/** The media token, fetching one if none is held or it is about to expire. Null when there is no
 *  session, or the server could not be reached (the caller shows the address without a token and
 *  the image route refuses it; `recheckSession` then tells whether the session itself has ended). */
export function mediaToken(): Promise<string | null> {
  if (!getToken()) return Promise.resolve(null)
  if (token && Date.now() < expiresAt - REFRESH_AHEAD_MS) return Promise.resolve(token)
  if (pending) return pending
  pending = (async () => {
    try {
      const r = await fetch('/api/v2/auth/media-token', { headers: { Authorization: `Bearer ${getToken() ?? ''}` }, signal: AbortSignal.timeout(10_000) })
      if (r.status === 401) { unauthorised(); return null }
      if (!r.ok) return token && Date.now() < expiresAt ? token : null
      const body = await r.json() as { token: string; expires_in: number }
      token = body.token
      expiresAt = Date.now() + Math.max(60, body.expires_in) * 1000
      schedule()
      listeners.forEach(l => l())
      return token
    } catch {
      return token && Date.now() < expiresAt ? token : null
    } finally {
      pending = null
    }
  })()
  return pending
}

function schedule() {
  if (timer) clearTimeout(timer)
  const inMs = Math.max(30_000, expiresAt - REFRESH_AHEAD_MS - Date.now())
  timer = setTimeout(() => { if (getToken()) void mediaToken() }, inMs)
}

/** An image or stream was refused: the token has expired or been revoked. Forget it and fetch
 *  another; the listeners (screens showing images) re-render with the new one. */
export function mediaTokenRejected(): Promise<string | null> {
  token = null; expiresAt = 0
  return mediaToken()
}

/** Sign-out: forget the token and stop refreshing it. */
export function clearMediaToken(): void {
  token = null; expiresAt = 0
  if (timer) { clearTimeout(timer); timer = null }
}

/** Re-render when a new media token arrives (addresses built with `withMediaToken` change). */
export function onMediaToken(fn: () => void): () => void {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

/** The URL with the media token on it, for `<img src>` and `EventSource`. Without a token held
 *  yet, the bare URL: the server answers 401, the caller asks for a token and tries again. */
export function withMediaToken(url: string): string {
  const t = currentMediaToken()
  if (!t) { void mediaToken(); return url }
  return url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(t)
}
