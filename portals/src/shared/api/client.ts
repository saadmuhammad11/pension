/** One place every request goes through: the token goes on, a refusal comes back as an Error
 *  carrying the server's own words, and a 401 ends the session.
 *
 *  Frontend review F7 (9 Oct 2026): every read and action has a 30-second limit, and what the
 *  officer reads on a failure is plain language. A dropped connection, a gateway error (502,
 *  503, 504) or a timeout all say the same thing -- the connection is slow or the server is
 *  busy and nothing was saved -- because that is all the officer can act on. A body that is not
 *  the API's own JSON (nginx's HTML error page, say) is never shown. Uploads go through
 *  `upload`, which has no time limit (a 256 MB scan on office Wi-Fi takes what it takes) but
 *  reports progress, and carries an Idempotency-Key so a retry cannot file a case twice (F8).
 *
 *  Every request in flight is counted (`requestsInFlight`): the idle timer treats a request
 *  under way as activity, so a long upload or a slow save does not end the session (F9). */
import { getToken, unauthorised } from '../auth/session'

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

/** Reads and actions wait this long before they are given up as a slow connection. */
export const REQUEST_TIMEOUT_MS = 30_000

export const SLOW_OR_BUSY = 'The connection is slow or the server is busy. Your work was not saved. Try again.'

/** The message the officer reads for one failure: the server's own words where it sent a JSON
 *  `detail`, the plain sentence for anything network-shaped, and never a page of HTML. */
export function friendlyMessage(status: number, body: string | null): string {
  if (status === 0 || status === 502 || status === 503 || status === 504) return SLOW_OR_BUSY
  const text = (body ?? '').trim()
  if (text) {
    try {
      const d = JSON.parse(text).detail
      if (typeof d === 'string' && d.trim()) return d
      if (Array.isArray(d)) return d.map((x: { msg?: string }) => x.msg ?? JSON.stringify(x)).join('; ')
    } catch { /* not the API's JSON */ }
  }
  if (status === 401) return 'Your session has ended. Please sign in again.'
  if (status === 403) return 'You are not permitted to do this.'
  if (status === 404) return 'This was not found. It may have been removed, or the address is wrong.'
  if (status === 413) return 'The file is too large for the server to accept.'
  if (status >= 500) return SLOW_OR_BUSY
  return `The request was refused (HTTP ${status}).`
}

async function detailOf(r: Response): Promise<string> {
  let text: string | null = null
  try { text = await r.text() } catch { text = null }
  return friendlyMessage(r.status, text)
}

// -- requests in flight: the idle timer counts them as activity (F9) -----------------------------
let inflight = 0
const inflightListeners = new Set<(n: number) => void>()
export const requestsInFlight = () => inflight
export function onInflightChange(fn: (n: number) => void): () => void {
  inflightListeners.add(fn)
  return () => { inflightListeners.delete(fn) }
}
function begin() { inflight += 1; inflightListeners.forEach(l => l(inflight)) }
function finish() { inflight = Math.max(0, inflight - 1); inflightListeners.forEach(l => l(inflight)) }

export async function request<T>(
  method: string, url: string,
  opts: { json?: unknown; form?: FormData; auth?: boolean; timeoutMs?: number } = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token && opts.auth !== false) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.json) }
  const controller = new AbortController()
  const limit = opts.timeoutMs ?? REQUEST_TIMEOUT_MS
  const timer = limit > 0 ? setTimeout(() => controller.abort(), limit) : null
  begin()
  let r: Response
  try {
    r = await fetch(url, { method, headers, body, signal: controller.signal })
  } catch {
    // A refused connection, a lost network, or our own timeout: the same plain sentence.
    throw new ApiError(0, SLOW_OR_BUSY)
  } finally {
    if (timer) clearTimeout(timer)
    finish()
  }
  if (r.status === 401 && opts.auth !== false) {
    unauthorised()
    throw new ApiError(401, await detailOf(r))
  }
  if (!r.ok) throw new ApiError(r.status, await detailOf(r))
  const text = await r.text()
  // Any change made through the case system -- a case filed, submitted, verified, decided,
  // returned, overridden -- tells every open view to refetch (shared/data/inventory.ts).
  if (method !== 'GET' && url.startsWith('/api/v2/') && !url.startsWith('/api/v2/auth/')) dataChanged.dispatchEvent(new Event('change'))
  return (text ? JSON.parse(text) : null) as T
}

/** Fired after every successful change through the API; the inventory store listens. */
export const dataChanged = new EventTarget()

/** A key for one attempt at a change: the same key on a retry of that attempt, so the server
 *  answers with the original result instead of acting twice (F8). */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`
}

export interface UploadProgress { sent: number; total: number }

/** Send a form with files: progress as it goes, no time limit, one Idempotency-Key per attempt.
 *  XMLHttpRequest, because `fetch` cannot report upload progress. */
export function upload<T>(url: string, form: FormData,
                          opts: { onProgress?: (p: UploadProgress) => void; idempotencyKey?: string } = {}): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    const token = getToken()
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.setRequestHeader('Idempotency-Key', opts.idempotencyKey ?? newIdempotencyKey())
    xhr.upload.onprogress = e => { if (opts.onProgress && e.lengthComputable) opts.onProgress({ sent: e.loaded, total: e.total }) }
    begin()
    xhr.onerror = () => { finish(); reject(new ApiError(0, SLOW_OR_BUSY)) }
    xhr.onabort = () => { finish(); reject(new ApiError(0, SLOW_OR_BUSY)) }
    xhr.onload = () => {
      finish()
      const text = xhr.responseText
      if (xhr.status === 401) { unauthorised(); reject(new ApiError(401, friendlyMessage(401, text))); return }
      if (xhr.status < 200 || xhr.status >= 300) { reject(new ApiError(xhr.status, friendlyMessage(xhr.status, text))); return }
      if (url.startsWith('/api/v2/') && !url.startsWith('/api/v2/auth/')) dataChanged.dispatchEvent(new Event('change'))
      try { resolve((text ? JSON.parse(text) : null) as T) }
      catch { reject(new ApiError(xhr.status, 'The server answered, but not with the expected reply. Reload the page to see whether the change was saved.')) }
    }
    xhr.send(form)
  })
}

/** What a tab may show from a blob. The server sends nothing else as viewable (api/v2 _SERVE_AS). */
const VIEWABLE = new Set(['application/pdf', 'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp'])

/** Open a protected file in a new tab without putting the session token on the URL: the file is
 *  fetched with the Authorization header and shown from a blob. The tab is opened first, in the
 *  click, so a popup blocker does not eat it; it says "Opening…" while the file comes (F12). */
export async function openProtected(url: string, filename?: string): Promise<void> {
  const tab = window.open('', '_blank')
  try {
    if (tab) {
      try { tab.document.title = filename ? `Opening ${filename}…` : 'Opening…'; tab.document.body.textContent = `Opening ${filename ?? 'the document'}…` } catch { /* cross-origin about:blank quirks */ }
    }
    const token = getToken()
    begin()
    let r: Response
    try { r = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} }) }
    catch { throw new ApiError(0, SLOW_OR_BUSY) }
    finally { finish() }
    if (r.status === 401) { unauthorised(); throw new ApiError(401, await detailOf(r)) }
    if (!r.ok) throw new ApiError(r.status, await detailOf(r))
    const blob = await r.blob()
    const href = URL.createObjectURL(blob)
    if (VIEWABLE.has(blob.type)) {
      if (tab) { tab.location.href = href; if (filename) tab.document.title = filename }
      else window.location.href = href
    } else {
      // Anything but a PDF or a picture is saved, never opened: a tab showing a blob runs on the
      // portal's own address, with this session in reach (audit 6 Oct 2026).
      tab?.close()
      const a = Object.assign(document.createElement('a'), { href, download: filename || 'document' })
      document.body.appendChild(a); a.click(); a.remove()
    }
    setTimeout(() => URL.revokeObjectURL(href), 60_000)
  } catch (e) {
    tab?.close()
    throw e
  }
}

export const get = <T,>(url: string) => request<T>('GET', url)
export const post = <T,>(url: string, json?: unknown) => request<T>('POST', url, { json: json ?? {} })
export const postForm = <T,>(url: string, form: FormData) => request<T>('POST', url, { form })
