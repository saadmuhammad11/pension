/** The header: crest, the portal's name, the signed-in officer, and the way out.
 *
 *  Wraps and trims on small screens: the subtitle and the officer's text go first; the crest,
 *  title, actions and sign-out stay. The user block shows the name once: the administrator's
 *  display name is also its role word, and a line repeated is a line not read. */
import type { ReactNode } from 'react'
import type { Theme } from '../theme/types'
import type { SessionUser } from '../auth/session'

export const Crest = ({ size = 48 }: { size?: number }) => (
  // Government of the Punjab: crescent and star over a shield with the five rivers, wheat
  // wreath. Drawn, not bitmapped, so it needs no asset and takes the portal's colours.
  <svg className="crest" width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="Government of the Punjab">
    <circle cx="32" cy="32" r="30" fill="var(--green2)" />
    <circle cx="32" cy="32" r="30" fill="none" stroke="var(--gold)" strokeWidth="2.5" />
    <circle cx="32" cy="32" r="24" fill="none" stroke="var(--gold)" strokeWidth=".9" opacity=".55" />
    {[-1, 1].map(side => (
      <g key={side} stroke="var(--gold2)" strokeWidth="1.5" fill="none" strokeLinecap="round" opacity=".9">
        <path d={`M${32 + side * 19} 26 q${side * 4} 12 ${-side * 5} 20`} />
        {[0, 1, 2, 3].map(i => (
          <path key={i} d={`M${32 + side * (19 + i * 0.4)} ${28 + i * 4.6} l${side * 5} -${2.4}`} />
        ))}
      </g>
    ))}
    <path d="M32 12a10.5 10.5 0 1 0 7.4 17.9A8.4 8.4 0 1 1 32 12Z" fill="var(--gold2)" />
    <path d="M43.6 15.4l1.05 2.7 2.85.2-2.2 1.8.72 2.8-2.42-1.6-2.42 1.6.72-2.8-2.2-1.8 2.85-.2z" fill="var(--gold2)" />
    <path d="M32 31c5.6 0 10 1.7 10 1.7v7.6c0 5.4-4.4 9-10 10.7-5.6-1.7-10-5.3-10-10.7v-7.6S26.4 31 32 31Z" fill="var(--sage)" />
    {[0, 1, 2, 3, 4].map(i => (
      <path key={i} d={`M24.4 ${35.4 + i * 3}c3.6 1.5 11.6 1.5 15.2 0`} stroke="var(--green2)"
            strokeWidth="1.35" fill="none" strokeLinecap="round" />
    ))}
  </svg>
)

const ROLE_WORDS: Record<string, string> = {
  DEPT_OFFICER: 'DDO (Drawing & Disbursing Officer)', AG_REVIEWER: 'Pension Wing, AG Punjab', ADMIN: 'System Administrator',
}

export function Header(
  { theme, user, onLogout, nav, actions }:
  { theme: Theme; user: SessionUser | null; onLogout?: () => void; nav?: ReactNode; actions?: ReactNode },
) {
  const initials = user ? user.display_name.split(/[\s(—-]+/).filter(Boolean).map(w => w[0]).slice(0, 2).join('').toUpperCase() : ''
  const roleLine = user ? [ROLE_WORDS[user.role] ?? user.role, user.role === 'DEPT_OFFICER' ? user.department_name : null].filter(Boolean).join(' · ') : ''
  return (
    <header className="site-header">
      <div className="container site-header-row">
        <a href="#/" className="brand">
          <Crest />
          <div className="brand-text">
            <div className="brand-title">{theme.title}</div>
            <div className="brand-sub">
              {theme.subtitle}
              {theme.titleUrdu && <> · <span className="urdu" style={{ display: 'inline-block' }}>{theme.titleUrdu}</span></>}
            </div>
          </div>
        </a>
        {nav}
        {actions}
        {user && (
          <div className="whoami">
            <div className="avatar" title={user.display_name}>{initials}</div>
            <div className="whoami-text">
              <div className="whoami-name">{user.display_name}</div>
              {roleLine !== user.display_name && <div className="whoami-role">{roleLine}</div>}
            </div>
            {onLogout && <button onClick={onLogout} title="Sign out" className="header-cta ghost-cta">Sign out</button>}
          </div>
        )}
      </div>
    </header>
  )
}
