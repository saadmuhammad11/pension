/** One place every request goes through: the token goes on, a refusal comes back as an Error
 *  carrying the server's own words, and a 401 ends the session. */
import { getToken, unauthorised } from '../auth/session'

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function detailOf(r: Response): Promise<string> {
  const text = await r.text()
  try {
    const d = JSON.parse(text).detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) return d.map((x: { msg?: string }) => x.msg ?? JSON.stringify(x)).join('; ')
    return text
  } catch { return text || `HTTP ${r.status}` }
}

export async function request<T>(
  method: string, url: string,
  opts: { json?: unknown; form?: FormData; auth?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token && opts.auth !== false) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.json) }
  const r = await fetch(url, { method, headers, body })
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

/** Open a protected file in a new tab without putting the session token on the URL: the file is
 *  fetched with the Authorization header and shown from a blob. The tab is opened first, in the
 *  click, so a popup blocker does not eat it. */
export async function openProtected(url: string, filename?: string): Promise<void> {
  const tab = window.open('', '_blank')
  try {
    const token = getToken()
    const r = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
    if (r.status === 401) { unauthorised(); throw new ApiError(401, await detailOf(r)) }
    if (!r.ok) throw new ApiError(r.status, await detailOf(r))
    const blob = await r.blob()
    const href = URL.createObjectURL(blob)
    if (tab) { tab.location.href = href; if (filename) tab.document.title = filename }
    else window.location.href = href
    setTimeout(() => URL.revokeObjectURL(href), 60_000)
  } catch (e) {
    tab?.close()
    throw e
  }
}

export const get = <T,>(url: string) => request<T>('GET', url)
export const post = <T,>(url: string, json?: unknown) => request<T>('POST', url, { json: json ?? {} })
export const postForm = <T,>(url: string, form: FormData) => request<T>('POST', url, { form })
