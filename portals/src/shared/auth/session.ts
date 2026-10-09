/** The signed-in user's token, kept per portal, for this tab only.
 *
 *  The token lives in `sessionStorage` (decision of 25 Sep 2026: a new tab or a reopened
 *  browser always starts at the sign-in page; nothing is remembered across sessions) under a
 *  key that names the portal, and travels as an `Authorization` header. The server reads the
 *  role and department off it on every call, and refuses a token at a portal it was not issued
 *  for; what a user may see follows from their credentials, not from the address they opened.
 */
import { portal } from '../portal'
import { clearMediaToken, withMediaToken } from './media'

export const PORTAL_SLUG = () => portal().slug ?? 'ag'

const key = () => `pension.${PORTAL_SLUG()}.token`
const nextKey = () => `pension.${PORTAL_SLUG()}.next`

/** Minutes without a click, key or scroll before the session ends, and the warning before it. */
/** 0: no idle sign-out. The office asked for it to go (9 Oct 2026): an officer reading a long
 *  case was signed out mid-work. A session still ends with its 12-hour token, on sign-out, and
 *  at once on any 401. Set a number of minutes to bring the timer back. */
export const IDLE_MINUTES = 0
export const IDLE_WARNING_MINUTES = 2

/** The roles the server knows. The three tiers of a pension wing arrived on 9 Oct 2026 (C3);
 *  AG_REVIEWER is the Accountant General's own desk, acting at every tier in every wing. */
export type Role = 'DEPT_OFFICER' | 'AG_SENIOR_AUDITOR' | 'AG_ASSISTANT_AO' | 'AG_AO' | 'AG_DAG' | 'AG_REVIEWER' | 'ADMIN'
export const AG_ROLES: Role[] = ['AG_SENIOR_AUDITOR', 'AG_ASSISTANT_AO', 'AG_AO', 'AG_DAG', 'AG_REVIEWER']
export const AG_READERS: Role[] = AG_ROLES
export const isAgReader = (role: string) => (AG_READERS as string[]).includes(role)

export interface SessionUser {
  id: string
  username: string
  display_name: string
  role: Role
  department_code: string | null
  department_name: string | null
  /** The pension wing (Pension-I … V) a tier officer belongs to (C3, 9 Oct 2026). */
  pension_wing?: string | null
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
  /** The tiers (C3): who decides, who talks to the department, and this officer's own tier and wing. */
  decide: boolean
  return_to_department: boolean
  tier: 'SENIOR_AUDITOR' | 'ASSISTANT_AO' | 'AO' | null
  tier_label: string | null
  pension_wing: string | null
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

/** A URL with a token on it, for `<img src>` and `EventSource`, which cannot send headers.
 *  The token is the short-lived media token (auth/media.ts), never the session token: image
 *  addresses land in the browser's cache and history (frontend review F10, 9 Oct 2026). */
export function withToken(url: string): string {
  return withMediaToken(url)
}

let onUnauthorised: (() => void) | null = null
export function setUnauthorisedHandler(fn: (() => void) | null): void { onUnauthorised = fn }
export function unauthorised(): void { setToken(null); clearMediaToken(); onUnauthorised?.() }

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
