/** The opening wall: every portal as a tile in its own colours, arriving one by one with a
 *  running count; the driver then zooms the wall into a few of them. */
import { useEffect, useState } from 'react'
import { Crest } from '../shared/components/Header'
import portals from './data/portals.json'
import tmcLogo from './data/tmc-logo.png'

export interface Tile { slug: string; name: string; primary: string; primary2: string; accent: string; kind: 'ag' | 'admin' | 'department' }

export function tiles(): Tile[] {
  const p = portals as { ag: { theme: { primary: string; primary2: string; accent: string } }; departments: { slug: string; name: string; theme: { primary: string; primary2: string; accent: string } }[] }
  const out: Tile[] = [
    { slug: 'ag', name: 'AG Review — Pension Wing', primary: p.ag.theme.primary, primary2: p.ag.theme.primary2, accent: p.ag.theme.accent, kind: 'ag' },
    { slug: 'admin', name: 'Administration', primary: '#1F2937', primary2: '#374151', accent: '#C9A227', kind: 'admin' },
  ]
  for (const d of p.departments) out.push({ slug: d.slug, name: d.name, primary: d.theme.primary, primary2: d.theme.primary2, accent: d.theme.accent, kind: 'department' })
  return out
}

export function PortalWall({ list, stepMs, focus, onPick }: { list: Tile[]; stepMs: number; focus: string | null; onPick?: (slug: string) => void }) {
  const [shown, setShown] = useState(0)
  useEffect(() => {
    setShown(0)
    let i = 0
    const t = window.setInterval(() => { i += 1; setShown(i); if (i >= list.length) window.clearInterval(t) }, stepMs)
    return () => window.clearInterval(t)
  }, [list, stepMs])
  return (
    <div className="wall">
      <div className="wall-head">
        <div className="wall-title">AI Pension Management System</div>
        <div className="wall-sub">Government of the Punjab · one portal for every department{onPick ? ' — choose a portal to sign in (every password is 1234)' : ''}</div>
        <div className="wall-count"><span className="num">{Math.min(shown, list.length)}</span> of {list.length} portals</div>
      </div>
      <div className="wall-grid">
        {list.map((t, i) => (
          <div key={t.slug} data-slug={t.slug} className={`wall-tile${i < shown ? ' is-in' : ''}${focus === t.slug ? ' is-focus' : ''}${onPick ? ' is-clickable' : ''}`}
               style={{ ['--tile' as string]: t.primary, ['--tile2' as string]: t.primary2, ['--tile-accent' as string]: t.accent }}
               role={onPick ? 'button' : undefined} tabIndex={onPick ? 0 : undefined}
               onClick={onPick ? () => onPick(t.slug) : undefined} onKeyDown={onPick ? e => { if (e.key === 'Enter') onPick(t.slug) } : undefined}>
            <div className="wall-crest"><Crest /></div>
            <div className="wall-name">{t.name}</div>
            <div className="wall-kind">{t.kind === 'ag' ? 'Accountant General' : t.kind === 'admin' ? 'System administration' : 'Department portal'}</div>
          </div>
        ))}
      </div>
      <div className="wall-foot">
        <span>Office of the Accountant General, Punjab · A.G. Complex, Turner Road, Lahore</span>
        <a className="powered wall-powered" href="https://tmcltd.com/" target="_blank" rel="noreferrer" title="TallyMarks Consulting">
          <span>Powered by</span><img src={tmcLogo} alt="TMC — TallyMarks Consulting" />
        </a>
      </div>
    </div>
  )
}
