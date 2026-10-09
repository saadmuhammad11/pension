/** The sign-in page: the office's mark on the left, the form on the right.
 *
 *  Full-width split (design of 28 Sep 2026, from the pension-portal mockup): a dark brand panel
 *  with the crest, the system's name and the five-rivers motif, and beside it one clear form.
 *  Stacks on narrow screens. The server decides whether this account belongs at this portal.
 *  Nothing is remembered across sessions (decision of 25 Sep 2026), so there is no
 *  "keep me signed in"; a lost password is reset by the administrator.
 *
 *  ChangePassword is the same page for an account whose password someone else set (5 Oct 2026):
 *  the server refuses everything else until the officer has chosen their own. */
import { useState, type FormEvent } from 'react'
import type { Theme } from '../theme/types'
import type { PortalConfig } from '../portal'
import { useSession } from '../auth/AuthProvider'
import { Crest } from '../components/Header'
import { PasswordField } from '../components/PasswordField'

const RIVERS = [
  'M-40 120 C 140 60, 260 220, 440 150 S 700 240, 720 180',
  'M-40 300 C 160 250, 300 400, 470 320 S 720 420, 740 350',
  'M-40 480 C 130 430, 300 560, 460 500 S 720 590, 740 520',
  'M-40 660 C 150 610, 300 740, 470 680 S 720 760, 740 700',
  'M-40 820 C 140 780, 300 900, 470 840 S 720 900, 740 860',
]

function Brand({ theme, portal }: { theme: Theme; portal: PortalConfig }) {
  const dept = portal.kind === 'department'
  const orgSub = theme.subtitle.replace(/^Government of the Punjab\s*·\s*/, '')
  return (
      <section className="auth-brand" aria-labelledby="brandTitle">
        <svg className="auth-rivers" viewBox="0 0 600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
          <g fill="none" stroke="var(--gold2)" strokeWidth="1.2" strokeOpacity=".5">
            {RIVERS.map(d => <path key={d} className="river" d={d} />)}
          </g>
        </svg>
        <header className="auth-top">
          <Crest size={56} />
          <div className="auth-org">
            <span className="org">Government of the Punjab</span>
            <span className="org-sub">{dept ? `${portal.name} · ${orgSub}` : orgSub}</span>
          </div>
        </header>
        <div className="auth-hero">
          <h1 id="brandTitle">{theme.title}</h1>
          <p className="lead-line">{dept ? 'AI Management Information System. ' : ''}Secure, Transparent, and Efficient.</p>
        </div>
        <footer className="auth-foot">
          <span className="pb-chip"><img src="./tmc-logo.png" alt="TallyMarks Consulting (TMC)" /></span>
          <span className="pb-text">
            <span className="pb-by">Powered by</span>
            <span className="pb-name">TallyMarks Consulting</span>
          </span>
        </footer>
      </section>
  )
}

function ErrorLine({ text }: { text: string }) {
  return (
    <div className="form-error" role="alert" aria-live="assertive">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16h.01" />
      </svg>
      <span>{text}</span>
    </div>
  )
}

export function Login({ theme, portal }: { theme: Theme; portal: PortalConfig }) {
  const { login, notice } = useSession()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const dept = portal.kind === 'department'

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) return
    setBusy(true); setError(null)
    try { await login(username.trim(), password) }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  return (
    <main className="auth">
      <Brand theme={theme} portal={portal} />

      <section className="auth-signin" aria-labelledby="signinTitle">
        <div className="auth-inner">
          <div className="auth-head">
            <span className="kicker">Secure officer access</span>
            <h2 id="signinTitle">Sign in</h2>
          </div>
          <form onSubmit={submit} noValidate>
            {notice && !error && (
              <div className="banner warn" style={{ margin: 0 }}>
                <span className="mark" aria-hidden="true">!</span><div className="sub">{notice}</div>
              </div>
            )}
            {error && <ErrorLine text={error} />}
            <div className="field">
              <label htmlFor="u">Username</label>
              <div className="field-input">
                <span className="lead-icon" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="8" r="4" /><path d="M4 20.5c0-3.6 3.6-6.5 8-6.5s8 2.9 8 6.5" />
                  </svg>
                </span>
                <input id="u" type="text" autoFocus autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false}
                       placeholder="Your username" value={username} onChange={e => setUsername(e.target.value)} aria-invalid={!!error} />
              </div>
            </div>
            <div className="field">
              <label htmlFor="p">Password</label>
              <div className="field-input">
                <span className="lead-icon" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" />
                  </svg>
                </span>
                <input id="p" type={show ? 'text' : 'password'} autoComplete="current-password" placeholder="Your password"
                       value={password} onChange={e => setPassword(e.target.value)} aria-invalid={!!error} />
                <button type="button" className="pw-toggle" onClick={() => setShow(!show)} aria-pressed={show}
                        aria-label={show ? 'Hide password' : 'Show password'}>
                  {show ? 'Hide' : 'Show'}
                </button>
              </div>
            </div>
            <button className="btn-primary" type="submit" disabled={busy || !username.trim() || !password}>
              {busy ? <><span className="spinner" aria-hidden="true" /> Signing in…</> : 'Sign in'}
            </button>
          </form>
          <p className="auth-note">
            {dept ? `Only ${portal.name} accounts sign in at this address. ` : ''}
            Authorised users only. Access is logged to an append-only audit trail. For password assistance, contact the system administrator.
          </p>
        </div>
      </section>
    </main>
  )
}

export function ChangePassword({ theme, portal }: { theme: Theme; portal: PortalConfig }) {
  const { user, changePassword, logout, passwordMinLength } = useSession()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const mismatch = !!again && next !== again

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!current || !next || next !== again) return
    setBusy(true); setError(null)
    try { await changePassword(current, next) }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  return (
    <main className="auth">
      <Brand theme={theme} portal={portal} />
      <section className="auth-signin" aria-labelledby="changeTitle">
        <div className="auth-inner">
          <div className="auth-head">
            <span className="kicker">{user?.display_name ?? 'Your account'}</span>
            <h2 id="changeTitle">Choose your own password</h2>
          </div>
          <form onSubmit={submit} noValidate>
            <div className="banner warn" style={{ margin: 0 }}>
              <span className="mark" aria-hidden="true">!</span>
              <div className="sub">Your password was set by the administrator. Choose your own before you continue: at least
                {passwordMinLength} characters, not a common password, and not your username.</div>
            </div>
            {error && <ErrorLine text={error} />}
            <div className="field">
              <label htmlFor="cur">Current password</label>
              <div className="field-input">
                <input id="cur" type="password" autoFocus autoComplete="current-password" value={current}
                       onChange={e => setCurrent(e.target.value)} />
              </div>
            </div>
            <PasswordField id="new" label="New password" value={next} onChange={setNext} minLength={passwordMinLength} username={user?.username} />
            <div className="field">
              <label htmlFor="again">New password again</label>
              <div className="field-input">
                <input id="again" type="password" autoComplete="new-password" value={again} aria-invalid={mismatch}
                       onChange={e => setAgain(e.target.value)} />
              </div>
            </div>
            {mismatch && <ErrorLine text="The two new passwords differ." />}
            <button className="btn-primary" type="submit" disabled={busy || !current || !next || next !== again || next.length < passwordMinLength}>
              {busy ? <><span className="spinner" aria-hidden="true" /> Saving…</> : 'Save and continue'}
            </button>
            <button type="button" onClick={logout}>Sign out</button>
          </form>
        </div>
      </section>
    </main>
  )
}
