/** A password being chosen: the server's rule as a live checklist, and a Show toggle (F14).
 *
 *  The minimum length comes from the server (`password_min_length` at sign-in), so the
 *  administrator's form and the officer's change-password screen say the same thing, and
 *  neither has a number of its own to drift. */
import { useState } from 'react'

export function passwordChecks(value: string, minLength: number, username?: string): { text: string; ok: boolean }[] {
  const v = value ?? ''
  const u = (username ?? '').trim().toLowerCase()
  return [
    { text: `At least ${minLength} characters`, ok: v.length >= minLength },
    { text: 'Not your username', ok: !u || !v.toLowerCase().includes(u) },
    { text: 'Not a run of one character or a simple sequence', ok: v.length > 0 && !/^(.)\1+$/.test(v) && !/^(?:0123|1234|2345|3456|4567|5678|6789|abcd|qwer|pass)/i.test(v) },
  ]
}

export function PasswordField({ id, label, value, onChange, minLength, username, autoFocus, autoComplete = 'new-password' }:
  { id: string; label: string; value: string; onChange: (v: string) => void; minLength: number; username?: string
    autoFocus?: boolean; autoComplete?: string }) {
  const [show, setShow] = useState(false)
  const checks = passwordChecks(value, minLength, username)
  return (
    <div className="field">
      <label className="label" htmlFor={id}>{label}</label>
      <div className="row" style={{ gap: 8, alignItems: 'center' }}>
        <input id={id} type={show ? 'text' : 'password'} autoFocus={autoFocus} autoComplete={autoComplete} value={value}
               onChange={e => onChange(e.target.value)} required minLength={minLength} aria-describedby={`${id}-rules`} style={{ flex: 1 }} />
        <button type="button" onClick={() => setShow(!show)} aria-pressed={show} aria-label={show ? 'Hide password' : 'Show password'}
                style={{ padding: '6px 10px', fontSize: 'var(--t-small)', minHeight: 0 }}>{show ? 'Hide' : 'Show'}</button>
      </div>
      <ul id={`${id}-rules`} className="hint" style={{ margin: '4px 0 0', paddingLeft: 18, listStyle: 'none' }} aria-live="polite">
        {checks.map(c => (
          <li key={c.text} style={{ color: value ? (c.ok ? 'var(--ok)' : 'var(--muted)') : 'var(--muted)' }}>
            <span aria-hidden="true">{value && c.ok ? '✓ ' : '· '}</span>{c.text}
          </li>
        ))}
      </ul>
    </div>
  )
}
