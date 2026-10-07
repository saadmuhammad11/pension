/** The signed-in user's token, kept per portal, for this tab only.
 *
 *  The token lives in `sessionStorage` (decision of 25 Sep 2026: a new tab or a reopened
 *  browser always starts at the sign-in page; nothing is remembered across sessions) under a
 *  key that names the portal, and travels as an `Authorization` header. The server reads the
 *  role and department off it on every call, and refuses a token at a portal it was not issued
 *  for; what a user may see follows from their credentials, not from the address they opened.
 */
import { portal } from '../portal'

export const PORTAL_SLUG = () => portal().slug ?? 'ag'

const key = () => `pension.${PORTAL_SLUG()}.token`
const nextKey = () => `pension.${PORTAL_SLUG()}.next`

/** Minutes without a click, key or scroll before the session ends, and the warning before it. */
export const IDLE_MINUTES = 30
export const IDLE_WARNING_MINUTES = 2

export interface SessionUser {
  id: string
  username: string
  display_name: string
  role: 'DEPT_OFFICER' | 'AG_REVIEWER' | 'AG_DAG' | 'ADMIN'
  department_code: string | null
  department_name: string | null
  active: boolean
  portal: string | null
  /** The password was set by someone else and must be replaced before anything else (5 Oct 2026). */
  must_change_password?: boolean
}

export interface Capabilities {
  create_case: boolean
  add_documents: boolean
  run_check: boolean
  forward: boolean
  pick_department: boolean
  intake_choices: boolean
  /** The AG and the administrator may correct a declared case type, with a remark. */
  correct_case_type: boolean
  review: boolean
  dispose: boolean
  override: boolean
  manage_users: boolean
  audit_log: boolean
  all_departments: boolean
}

export function getToken(): string | null {
  try { return sessionStorage.getItem(key()) } catch { return null }
}

export function setToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(key(), token)
    else sessionStorage.removeItem(key())
    // Anything an older build left in localStorage is a session that must not outlive the tab.
    localStorage.removeItem(key())
  } catch { /* private window: the session lasts as long as the page */ }
}

/** The page a visitor asked for before they were sent to sign in; honoured once after login. */
export function rememberNext(path: string): void {
  try { if (path && path !== '/' ) sessionStorage.setItem(nextKey(), path); } catch { /* ignore */ }
}
export function takeNext(): string | null {
  try { const v = sessionStorage.getItem(nextKey()); sessionStorage.removeItem(nextKey()); return v } catch { return null }
}

/** A URL with the token on it, for `<img src>` and `EventSource`, which cannot send headers. */
export function withToken(url: string): string {
  const t = getToken()
  if (!t) return url
  return url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(t)
}

let onUnauthorised: (() => void) | null = null
export function setUnauthorisedHandler(fn: (() => void) | null): void { onUnauthorised = fn }
export function unauthorised(): void { setToken(null); onUnauthorised?.() }

/** Ask the server whether the session still stands; used when an <img> or event stream fails,
 *  which cannot tell a 401 from a network hiccup. */
export async function recheckSession(): Promise<void> {
  const t = getToken()
  if (!t) return
  try {
    const r = await fetch('/api/v2/auth/me', { headers: { Authorization: `Bearer ${t}` }, signal: AbortSignal.timeout(5000) })
    if (r.status === 401) unauthorised()
  } catch { /* network: keep the session */ }
}
