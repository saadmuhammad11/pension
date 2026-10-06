/** Persistent header. BUILD §9.2. */
import { type Role } from '../api'

const Crest = () => (
  // Government of the Punjab: crescent and star over a shield with the five rivers, wheat
  // wreath, gold ring (§9.2). Drawn, not bitmapped, so it stays crisp and needs no external
  // asset -- the portal must run air-gapped.
  //
  // Redrawn for legibility at 58px. The first version layered a crescent, a star, a shield
  // and five river strokes inside a dark disc, and at this size they collapsed into a blob.
  // Fewer, larger elements on a lighter ground survive the reduction.
  <svg width="58" height="58" viewBox="0 0 64 64" role="img"
       aria-label="Government of the Punjab">
    <circle cx="32" cy="32" r="30" fill="#14361F" />
    <circle cx="32" cy="32" r="30" fill="none" stroke="var(--gold)" strokeWidth="2.5" />
    <circle cx="32" cy="32" r="24" fill="none" stroke="var(--gold)" strokeWidth=".9"
            opacity=".55" />
    {/* wheat wreath: two arcs of grain, the shape that reads first at small sizes */}
    {[-1, 1].map(side => (
      <g key={side} stroke="var(--gold2)" strokeWidth="1.5" fill="none" strokeLinecap="round"
         opacity=".9">
        <path d={`M${32 + side * 19} 26 q${side * 4} 12 -${side * 5} 20`} />
        {[0, 1, 2, 3].map(i => (
          <path key={i} d={`M${32 + side * (19 + i * 0.4)} ${28 + i * 4.6}
                            l${side * 5} -${2.4}`} />
        ))}
      </g>
    ))}
    {/* crescent and star */}
    <path d="M32 12a10.5 10.5 0 1 0 7.4 17.9A8.4 8.4 0 1 1 32 12Z" fill="var(--gold2)" />
    <path d="M43.6 15.4l1.05 2.7 2.85.2-2.2 1.8.72 2.8-2.42-1.6-2.42 1.6.72-2.8-2.2-1.8 2.85-.2z"
          fill="var(--gold2)" />
    {/* shield with the five rivers */}
    <path d="M32 31c5.6 0 10 1.7 10 1.7v7.6c0 5.4-4.4 9-10 10.7-5.6-1.7-10-5.3-10-10.7v-7.6
             S26.4 31 32 31Z" fill="#EDF4EE" />
    {[0, 1, 2, 3, 4].map(i => (
      <path key={i} d={`M24.4 ${35.4 + i * 3}c3.6 1.5 11.6 1.5 15.2 0`} stroke="#2D6A4F"
            strokeWidth="1.35" fill="none" strokeLinecap="round" />
    ))}
  </svg>
)

/** The SOP §4 parties, and a plausible officer for each. Until there is authentication the
 *  role is a claim rather than an identity, so it is switched here openly rather than
 *  pretended to be a login. The server refuses a decision claimed under the wrong role
 *  whatever this control says. */
const OFFICER_FOR: Record<Role, { user: string; designation: string }> = {
  ACCOUNTS_OFFICE: { user: 'Syed Haider', designation: 'Auditor, Pension-III (P3)' },
  ADMIN_DEPARTMENT: { user: 'Dept. User', designation: 'School Education Department' },
}

export function Header(
  { role, onRole, onNew }:
  { role: Role; onRole: (r: Role) => void; onNew?: () => void },
) {
  const who = OFFICER_FOR[role]
  const initials = who.user.split(' ').map(w => w[0]).slice(0, 2).join('')
  return (
    <header style={{ background: 'var(--green)', color: '#fff' }}>
      <div className="container" style={{
        display: 'flex', alignItems: 'center', gap: 14, padding: '12px 20px',
      }}>
        <Crest />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 19, fontWeight: 700, letterSpacing: .2 }}>AI Pension Portal</div>
          <div style={{ fontSize: 12, opacity: .82 }}>
            Government of the Punjab · Accountant General Office, Lahore ·{' '}
            <span className="urdu" style={{ display: 'inline-block' }}>اے آئی پنشن پورٹل</span>
          </div>
        </div>
        <span style={{
          background: 'rgba(201,162,39,.18)', color: 'var(--gold2)', border: '1px solid var(--gold)',
          borderRadius: 999, padding: '5px 12px', fontSize: 11, fontWeight: 700, letterSpacing: .5,
        }}>PILOT</span>
        {/* A case does not only begin at the register. An officer who has just dispatched
            one has the next file in their hand, so the way in is on every screen. */}
        {onNew && (
          <button
            onClick={onNew}
            title="Submit a new case for verification"
            style={{
              background: 'rgba(255,255,255,.12)', color: '#fff',
              border: '1px solid rgba(255,255,255,.35)', borderRadius: 999,
              padding: '7px 15px', fontSize: 12, fontWeight: 700, whiteSpace: 'nowrap',
            }}
          >＋ New case</button>
        )}
        <label style={{ display: 'flex', alignItems: 'center', gap: 7, marginLeft: 8 }}>
          <span style={{ fontSize: 11, opacity: .8, fontWeight: 700, letterSpacing: .4 }}>
            ACTING AS
          </span>
          <select
            value={role}
            onChange={e => onRole(e.target.value as Role)}
            style={{
              width: 'auto', minWidth: 210, padding: '7px 34px 7px 11px', fontSize: 12,
              fontWeight: 600, background: 'rgba(255,255,255,.10)', color: '#fff',
              borderColor: 'rgba(255,255,255,.28)',
            }}
          >
            <option value="ACCOUNTS_OFFICE" style={{ color: 'var(--ink)' }}>
              Accounts Office (§4.2)
            </option>
            <option value="ADMIN_DEPARTMENT" style={{ color: 'var(--ink)' }}>
              Administrative Department (§4.1)
            </option>
          </select>
        </label>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{
            width: 34, height: 34, borderRadius: '50%', background: 'var(--gold)',
            color: '#1F2937', display: 'grid', placeItems: 'center', fontWeight: 700, fontSize: 13,
          }}>{initials}</div>
          <div style={{ fontSize: 12, lineHeight: 1.3 }}>
            <div style={{ fontWeight: 700 }}>{who.user}</div>
            <div style={{ opacity: .8 }}>{who.designation}</div>
          </div>
        </div>
      </div>
    </header>
  )
}
