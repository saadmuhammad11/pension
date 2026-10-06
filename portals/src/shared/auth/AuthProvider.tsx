/** Who is signed in, for the whole portal; and for how long.
 *
 *  Sign-in is required on every visit (the token lives in sessionStorage, so a new tab or a
 *  reopened browser starts at the sign-in page). A session also ends after IDLE_MINUTES without
 *  a click, key or scroll, with a warning IDLE_WARNING_MINUTES before; and at once on any 401.
 *  Signing out clears everything and returns to the sign-in page; a page the visitor asked for
 *  before signing in is opened after they do -- but never a page the previous officer left.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, get, post } from '../api/client'
import { stopInventoryPolling } from '../data/inventory'
import { navigate } from '../router/hash'
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
}

const EMPTY: Capabilities = {
  create_case: false, add_documents: false, run_check: false, forward: false, pick_department: false,
  intake_choices: false, correct_case_type: false, review: false, dispose: false, override: false, manage_users: false,
  audit_log: false, all_departments: false,
}

const Ctx = createContext<Session>({ user: null, can: null, loading: true, login: async () => {}, logout: () => {},
                                    changePassword: async () => {}, notice: null })

const ACTIVITY = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'click'] as const

const currentPath = () => window.location.hash.replace(/^#/, '') || '/'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null)
  const [can, setCan] = useState<Capabilities | null>(null)
  const [loading, setLoading] = useState<boolean>(!!getToken())
  const [notice, setNotice] = useState<string | null>(null)
  const [warning, setWarning] = useState<number | null>(null)      // seconds left, while warning
  const warningRef = useRef<number | null>(null)
  warningRef.current = warning

  const end = useCallback((why: string | null, comeBack: boolean) => {
    // Whatever ended the session, the next sign-in opens the main page (29 Sep 2026); the
    // address is forgotten so the next person at this screen does not land on a case.
    void comeBack; takeNext()
    // The GP Fund frame's cookie is HttpOnly, so only the server can clear it; without this the
    // next person at a shared PC could open /gpf/ as this officer for two hours. Best effort.
    void fetch('/api/v2/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => undefined)
    setToken(null); setUser(null); setCan(null); setWarning(null)
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
    get<{ user: SessionUser; capabilities: Capabilities }>('/api/v2/auth/me')
      .then(r => { setUser(r.user); setCan(r.capabilities); setNotice(null) })
      .catch(e => { if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setToken(null) })
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const r = await post<{ token: string; user: SessionUser; capabilities: Capabilities }>(
      '/api/v2/auth/login', { username, password, portal: PORTAL_SLUG() })
    setToken(r.token)
    setUser(r.user)
    setCan(r.capabilities)
    setNotice(null)
    // Every sign-in opens the portal's main page (decision of 29 Sep 2026), never the page the
    // last session was on: the address bar may still carry a case from before the session ended.
    takeNext()
    navigate('/', { replace: true })
  }, [])

  const changePassword = useCallback(async (current: string, next: string) => {
    // The change ends every other session of this account (token_version), this one included:
    // the reply carries the token to carry on with.
    const r = await post<{ token: string; user: SessionUser; capabilities: Capabilities }>(
      '/api/v2/auth/change-password', { current, new: next })
    setToken(r.token)
    setUser(r.user)
    setCan(r.capabilities)
    navigate('/', { replace: true })
  }, [])

  // Idle timeout. The deadline is kept in a ref and pushed forward by any activity; a one-second
  // tick compares against it, so a laptop that slept still signs out on waking. Once the warning
  // is up, only its buttons count: a pointer moving towards them must not dismiss it.
  const deadline = useRef<number>(0)
  const extend = useCallback(() => { deadline.current = Date.now() + IDLE_MINUTES * 60_000; setWarning(null) }, [])
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
    const tick = window.setInterval(() => {
      const left = Math.round((deadline.current - Date.now()) / 1000)
      if (left <= 0) end(`You were signed out after ${IDLE_MINUTES} minutes without activity.`, true)
      else if (left <= IDLE_WARNING_MINUTES * 60) setWarning(left)
    }, 1000)
    return () => { ACTIVITY.forEach(ev => window.removeEventListener(ev, onActivity)); window.clearInterval(tick) }
  }, [user, end])

  const value = useMemo(() => ({ user, can: can ?? (user ? EMPTY : null), loading, login, logout, changePassword, notice }),
                        [user, can, loading, login, logout, changePassword, notice])
  return (
    <Ctx.Provider value={value}>
      {children}
      {user && warning !== null && (
        <div className="idle-warning" role="alertdialog" aria-live="assertive" aria-label="Session about to end">
          <div>
            <div className="idle-title">Still there?</div>
            <div className="idle-text">You will be signed out in {Math.floor(warning / 60)}:{String(warning % 60).padStart(2, '0')} for inactivity.</div>
          </div>
          <button className="primary" autoFocus onClick={extend}>Stay signed in</button>
          <button onClick={logout}>Sign out now</button>
        </div>
      )}
    </Ctx.Provider>
  )
}

export const useSession = () => useContext(Ctx)
