/** The header: crest, the portal's name, the signed-in officer, and the way out.
 *
 *  Wraps and trims on small screens: the subtitle and the officer's text go first; the crest,
 *  title, actions and sign-out stay. The user block shows the name once: the administrator's
 *  display name is also its role word, and a line repeated is a line not read. */
import type { ReactNode } from 'react'
import type { Theme } from '../theme/types'
import type { SessionUser } from '../auth/session'

export const Crest = ({ size = 48 }: { size?: number }) => (
  // The State Emblem of Pakistan, supplied by the office 22 Oct 2026, replacing the drawn
  // Punjab crest. White, because every surface it sits on -- the header, the sign-in panel,
  // the demo wall -- is dark green; public/state-emblem-dark.png is the same mark in --green
  // for a light surface. The source was a JPEG whose transparency had been flattened into a
  // checkerboard, so the background is cut by luminance and the alpha carries the antialiasing.
  <img className="crest" src="./state-emblem.png" width={size} height={size}
       alt="Government of Pakistan" />
)

const ROLE_WORDS: Record<string, string> = {
  DEPT_OFFICER: 'DDO (Drawing & Disbursing Officer)', AG_REVIEWER: 'Accountant General', AG_ADDL: 'Additional Accountant General', AG_DAG: 'Deputy Accountant General', ADMIN: 'System Administrator',
  AG_SENIOR_AUDITOR: 'Senior Auditor', AG_ASSISTANT_AO: 'Assistant Accounts Officer', AG_AO: 'Accounts Officer',
}

export function Header(
  { theme, user, onLogout, nav, actions }:
  { theme: Theme; user: SessionUser | null; onLogout?: () => void; nav?: ReactNode; actions?: ReactNode },
) {
  const initials = user ? user.display_name.split(/[\s(—-]+/).filter(Boolean).map(w => w[0]).slice(0, 2).join('').toUpperCase() : ''
  const roleLine = user ? [ROLE_WORDS[user.role] ?? user.role, user.role === 'DEPT_OFFICER' ? user.department_name : null,
                           user.pension_wing ? `AG ${user.pension_wing}` : null].filter(Boolean).join(' · ') : ''
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
