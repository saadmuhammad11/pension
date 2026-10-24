/** The officer's own account: the password, and for the senior desks the login name.
 *
 *  The password endpoint has existed since the beginning and could only be reached when an
 *  administrator had forced a reset (PortalShell draws ChangePassword on must_change_password).
 *  An officer who simply wanted to change their own password had to ask for one to be reset
 *  first, which is a worse password habit than the one it was guarding (24 Oct 2026).
 *
 *  The login name is the senior desks' own: the Deputy AG, the Additional AG and the AG hold a
 *  login in their own name and no administrator sits above them. A DDO's login is its
 *  department's slug, which identifies the department rather than a person, so that one stays
 *  with the administrator.
 *
 *  Both ask for the current password. Both end every session of the account, this one included
 *  -- the token names the account as it was -- so the officer signs in again afterwards.
 */
import { useState, type FormEvent } from 'react'
import { post } from '../api/client'
import { useSession } from '../auth/AuthProvider'
import { PasswordField } from '../components/PasswordField'
import { ROLE_WORDS } from './admin/Users'

/** Whose account this screen is for at all: the Deputy AG, the Additional AG and the AG.
 *  They hold a login in their own name and no administrator sits above them in the office.
 *  Every other desk's account stays the administrator's to manage, which is what it was.
 *  The server decides the same thing for the rename (v2.MAY_RENAME_SELF). */
export const MAY_MANAGE_OWN_PROFILE = ['AG_DAG', 'AG_REVIEWER', 'AG_ADDL']
const USERNAME = /^[a-z0-9._-]{3,40}$/

export function MyAccount() {
  const { user, changePassword, logout, passwordMinLength } = useSession()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const [pwError, setPwError] = useState<string | null>(null)
  const [pwBusy, setPwBusy] = useState(false)

  const [name, setName] = useState('')
  const [namePw, setNamePw] = useState('')
  const [nameError, setNameError] = useState<string | null>(null)
  const [nameBusy, setNameBusy] = useState(false)

  if (!user) return null
  const mayRename = MAY_MANAGE_OWN_PROFILE.includes(user.role)
  const mismatch = !!again && next !== again
  const badName = !!name && !USERNAME.test(name.trim().toLowerCase())

  async function savePassword(e: FormEvent) {
    e.preventDefault()
    if (!current || !next || next !== again) return
    setPwBusy(true); setPwError(null)
    try { await changePassword(current, next) }
    catch (err) { setPwError(err instanceof Error ? err.message : String(err)) }
    finally { setPwBusy(false) }
  }

  async function saveUsername(e: FormEvent) {
    e.preventDefault()
    const wanted = name.trim().toLowerCase()
    if (!wanted || !namePw || badName) return
    setNameBusy(true); setNameError(null)
    try {
      await post('/api/v2/auth/username', { username: wanted, password: namePw })
      // Every session of the account has just ended, this one with them: sign in again under
      // the name just chosen rather than leave a token naming an account that is gone.
      logout()
    } catch (err) {
      setNameError(err instanceof Error ? err.message : String(err))
    } finally { setNameBusy(false) }
  }

  return (
    <div className="screen container" style={{ paddingTop: 22, maxWidth: 620 }}>
      <h1>My account</h1>
      <p className="lead">{user.display_name} · {ROLE_WORDS[user.role] ?? user.role}</p>

      <div className="card" style={{ marginTop: 'var(--s4)' }}>
        <h3 style={{ marginTop: 0 }}>Password</h3>
        <form onSubmit={savePassword} className="stack">
          <div className="field">
            <label htmlFor="pw-current">Current password</label>
            <div className="field-input">
              <input id="pw-current" type="password" autoComplete="current-password" value={current}
                     onChange={e => setCurrent(e.target.value)} />
            </div>
          </div>
          <PasswordField id="pw-next" label="New password" value={next} onChange={setNext}
                         minLength={passwordMinLength} username={user.username} />
          <div className="field">
            <label htmlFor="pw-again">New password again</label>
            <div className="field-input">
              <input id="pw-again" type="password" autoComplete="new-password" value={again} aria-invalid={mismatch}
                     onChange={e => setAgain(e.target.value)} />
            </div>
          </div>
          {mismatch && <div className="form-error" role="alert">The two new passwords are not the same.</div>}
          {pwError && <div className="form-error" role="alert">{pwError}</div>}
          <div className="row">
            <button className="primary" disabled={pwBusy || !current || !next || mismatch || !again}>
              {pwBusy ? 'Changing…' : 'Change password'}
            </button>
          </div>
          <div className="help">Every session of this account ends, so you will sign in again.</div>
        </form>
      </div>

      {mayRename && (
        <div className="card" style={{ marginTop: 'var(--s4)' }}>
          <h3 style={{ marginTop: 0 }}>Login name</h3>
          <p className="help" style={{ marginTop: 0 }}>
            You sign in as <span className="mono">{user.username}</span>. Your history does not
            move with the name: every case and every audit entry names the account, not the word
            you type to sign in.
          </p>
          <form onSubmit={saveUsername} className="stack">
            <div className="field">
              <label className="label" htmlFor="new-username">New login name</label>
              <input id="new-username" value={name} onChange={e => setName(e.target.value)}
                     autoComplete="off" spellCheck={false} style={{ fontSize: 16 }} />
              <div className="hint">3 to 40 characters: letters, digits, full stop, underscore, hyphen.</div>
            </div>
            {badName && <div className="form-error" role="alert">3 to 40 characters: letters, digits, . _ -</div>}
            <div className="field">
              <label htmlFor="name-pw">Your password</label>
              <div className="field-input">
                <input id="name-pw" type="password" autoComplete="current-password" value={namePw}
                       onChange={e => setNamePw(e.target.value)} />
              </div>
            </div>
            {nameError && <div className="form-error" role="alert">{nameError}</div>}
            <div className="row">
              <button className="primary" disabled={nameBusy || !name || !namePw || badName}>
                {nameBusy ? 'Changing…' : 'Change login name'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
