/** Who is signed in, for the whole portal; and for how long.
 *
 *  Sign-in is required on every visit (the token lives in sessionStorage, so a new tab or a
 *  reopened browser starts at the sign-in page). A session also ends after IDLE_MINUTES without
 *  a click, key or scroll, with a warning IDLE_WARNING_MINUTES before; and at once on any 401.
 *  Signing out clears everything and returns to the sign-in page; a page the visitor asked for
 *  before signing in is opened after they do -- but never a page the previous officer left.
 *
 *  What counts as activity (frontend review F9, 9 Oct 2026): the officer's own pointer, keys
 *  and scrolling on this window; the same inside the GP Fund frame, which posts a message the
 *  portal accepts only from its own origin and its own frame (auth/frameActivity.ts); and any
 *  request in flight, so a slow save or a long upload never ends the session under it. The
 *  countdown is read out at 2:00, 1:00 and 0:30 only -- once a second was unbearable with a
 *  screen reader -- and says that unsaved text will be lost.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, get, post, requestsInFlight } from '../api/client'
import { stopInventoryPolling } from '../data/inventory'
import { navigate } from '../router/hash'
import { clearMediaToken, mediaToken } from './media'
import { gpfExpired, readFrameMessage } from './frameActivity'
import { IDLE_MINUTES, IDLE_WARNING_MINUTES, PORTAL_SLUG, getToken, rememberNext, setToken, setUnauthorisedHandler, takeNext,
         type Capabilities, type SessionUser } from './session'

interface Session {
  user: SessionUser | null
  can: Capabilities | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  /** Replace a password someone else set; the server answers with a fresh session. */
  changePassword: (current: string, next: string) => Promise<void>
  /** Why the last session ended, shown once on the sign-in page. */
  notice: string | null
  /** The shortest password the server accepts: one rule, told by the server (F14). */
  passwordMinLength: number
}

/** What the server says when it is not asked, or has not answered yet (api/settings.py default). */
export const DEFAULT_PASSWORD_MIN_LENGTH = 10

const EMPTY: Capabilities = {
  create_case: false, add_documents: false, run_check: false, forward: false, pick_department: false,
  intake_choices: false, correct_case_type: false, review: false, dispose: false, override: false, manage_users: false,
  audit_log: false, all_departments: false,
  decide: false, return_to_department: false, tier: null, tier_label: null, pension_wing: null,
}

const Ctx = createContext<Session>({ user: null, can: null, loading: true, login: async () => {}, logout: () => {},
                                    changePassword: async () => {}, notice: null, passwordMinLength: DEFAULT_PASSWORD_MIN_LENGTH })

const ACTIVITY = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'click'] as const

/** The seconds left at which the countdown is read out (F9). */
export const ANNOUNCE_AT = new Set([120, 60, 30])

const currentPath = () => window.location.hash.replace(/^#/, '') || '/'

type SessionReply = { token?: string; user: SessionUser; capabilities: Capabilities; password_min_length?: number }

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null)
  const [can, setCan] = useState<Capabilities | null>(null)
  const [loading, setLoading] = useState<boolean>(!!getToken())
  const [notice, setNotice] = useState<string | null>(null)
  const [warning, setWarning] = useState<number | null>(null)      // seconds left, while warning
  const [announced, setAnnounced] = useState<string>('')           // what the screen reader hears
  const [passwordMinLength, setPasswordMinLength] = useState<number>(DEFAULT_PASSWORD_MIN_LENGTH)
  const warningRef = useRef<number | null>(null)
  warningRef.current = warning

  const took = useCallback((r: SessionReply) => {
    setUser(r.user); setCan(r.capabilities); setNotice(null)
    if (typeof r.password_min_length === 'number' && r.password_min_length > 0) setPasswordMinLength(r.password_min_length)
    void mediaToken()                                 // images and the event stream carry this, not the session (F10)
  }, [])

  const end = useCallback((why: string | null, comeBack: boolean) => {
    // Whatever ended the session, the next sign-in opens the main page (29 Sep 2026); the
    // address is forgotten so the next person at this screen does not land on a case.
    void comeBack; takeNext()
    // The server ends the token (a copy would otherwise stay valid for 12 hours) and clears the GP
    // Fund frame's cookie, which is HttpOnly; without this the next person at a shared PC could open
    // /gpf/ as this officer for two hours. The token goes along so the server knows whose session
    // to end; read before it is dropped below. Best effort.
    const ending = getToken()
    void fetch('/api/v2/auth/logout', { method: 'POST', credentials: 'same-origin',
                                        headers: ending ? { Authorization: `Bearer ${ending}` } : {} }).catch(() => undefined)
    setToken(null); clearMediaToken(); setUser(null); setCan(null); setWarning(null); setAnnounced('')
    stopInventoryPolling()                      // no more 3-second asks, and this officer's rows are forgotten

    if (why) setNotice(why)
    navigate('/', { replace: true })
  }, [])

  const logout = useCallback(() => end(null, false), [end])

  useEffect(() => {
    setUnauthorisedHandler(() => end('Your session has ended. Please sign in again.', true))
    return () => setUnauthorisedHandler(null)
  }, [end])

  // A visitor who arrives without a session at a deep link gets that page after signing in.
  // Remembered once, here, and not during render.
  useEffect(() => {
    if (!getToken() && currentPath() !== '/') rememberNext(currentPath())
  }, [])

  // A token in this tab is checked with the server before it is trusted. Only a refusal ends
  // it; a network error keeps it, so a flaky connection does not sign people out.
  useEffect(() => {
    if (!getToken()) return
    get<SessionReply>('/api/v2/auth/me')
      .then(took)
      .catch(e => { if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setToken(null) })
      .finally(() => setLoading(false))
  }, [took])

  const login = useCallback(async (username: string, password: string) => {
    const r = await post<SessionReply>('/api/v2/auth/login', { username, password, portal: PORTAL_SLUG() })
    setToken(r.token ?? null)
    took(r)
    // Every sign-in opens the portal's main page (decision of 29 Sep 2026), never the page the
    // last session was on: the address bar may still carry a case from before the session ended.
    takeNext()
    navigate('/', { replace: true })
  }, [took])

  const changePassword = useCallback(async (current: string, next: string) => {
    // The change ends every other session of this account (token_version), this one included:
    // the reply carries the token to carry on with.
    const r = await post<SessionReply>('/api/v2/auth/change-password', { current, new: next })
    setToken(r.token ?? null)
    took(r)
    navigate('/', { replace: true })
  }, [took])

  // Idle timeout. The deadline is kept in a ref and pushed forward by any activity; a one-second
  // tick compares against it, so a laptop that slept still signs out on waking. Once the warning
  // is up, only its buttons count: a pointer moving towards them must not dismiss it. A request
  // in flight pushes the deadline too (F9): the officer is waiting on the system, not away.
  const deadline = useRef<number>(0)
  const extend = useCallback(() => { deadline.current = Date.now() + IDLE_MINUTES * 60_000; setWarning(null); setAnnounced('') }, [])
  useEffect(() => {
    if (!user) return
    deadline.current = Date.now() + IDLE_MINUTES * 60_000
    let last = 0
    const onActivity = () => {
      if (warningRef.current !== null) return
      const t = Date.now()
      if (t - last > 1000) { last = t; deadline.current = t + IDLE_MINUTES * 60_000 }
    }
    ACTIVITY.forEach(ev => window.addEventListener(ev, onActivity, { passive: true }))
    // The GP Fund frame's word (auth/frameActivity.ts): activity, or an expired frame sign-in.
    const onMessage = (e: MessageEvent) => {
      const m = readFrameMessage(e)
      if (m?.kind === 'activity') onActivity()
      else if (m?.kind === 'expired') gpfExpired()
    }
    window.addEventListener('message', onMessage)
    const tick = window.setInterval(() => {
      if (requestsInFlight() > 0 && warningRef.current === null) deadline.current = Date.now() + IDLE_MINUTES * 60_000
      const left = Math.round((deadline.current - Date.now()) / 1000)
      if (left <= 0) end(`You were signed out after ${IDLE_MINUTES} minutes without activity.`, true)
      else if (left <= IDLE_WARNING_MINUTES * 60) {
        setWarning(left)
        if (ANNOUNCE_AT.has(left)) setAnnounced(`You will be signed out in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')} for inactivity. Unsaved text will be lost.`)
      }
    }, 1000)
    return () => {
      ACTIVITY.forEach(ev => window.removeEventListener(ev, onActivity))
      window.removeEventListener('message', onMessage)
      window.clearInterval(tick)
    }
  }, [user, end])

  const value = useMemo(() => ({ user, can: can ?? (user ? EMPTY : null), loading, login, logout, changePassword, notice, passwordMinLength }),
                        [user, can, loading, login, logout, changePassword, notice, passwordMinLength])
  return (
    <Ctx.Provider value={value}>
      {children}
      {user && warning !== null && (
        <div className="idle-warning" role="alertdialog" aria-label="Session about to end" aria-describedby="idle-text">
          <div>
            <div className="idle-title">Still there?</div>
            <div className="idle-text" id="idle-text">You will be signed out in {Math.floor(warning / 60)}:{String(warning % 60).padStart(2, '0')} for inactivity. Unsaved text will be lost.</div>
          </div>
          <button className="primary" autoFocus onClick={extend}>Stay signed in</button>
          <button onClick={logout}>Sign out now</button>
        </div>
      )}
      {/* Read out at 2:00, 1:00 and 0:30 only; the visible countdown above is not a live region. */}
      <div className="sr-only" aria-live="assertive" aria-atomic="true">{announced}</div>
    </Ctx.Provider>
  )
}

export const useSession = () => useContext(Ctx)
