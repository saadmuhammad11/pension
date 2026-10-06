/** The scanned page a finding was read from.
 *
 *  A finding names its page — "the card at p.2", "Annex-A contradicts the FRC at p.10" —
 *  and the whole reason for citing a page is that somebody can look at it. Until now the
 *  officer had to go and find that page in the original PDF, which on a fifty-one page
 *  bundle is the difference between checking a finding and taking it on trust.
 */
import { openProtected } from '../api/client'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { pageImageUrl } from '../api'

export function PagePreview(
  { runId, page, document: doc, onClose, srcFor }:
  { runId: string; page: number; document?: string; onClose: () => void
    /** Where the page image is, for pages that are not a pension run's (the GP Fund claim's). */
    srcFor?: (page: number) => string },
) {
  const imageUrl = (pg: number) => srcFor ? srcFor(pg) : pageImageUrl(runId, pg)
  const [zoom, setZoom] = useState(false)
  // Pages arrive as scanned: a landscape table, a CNIC copied sideways, a form fed in upside
  // down. Turning the page is for the officer's eyes only; the case file is not changed.
  const [turn, setTurn] = useState(0)
  const rotate = (by: number) => setTurn(t => (t + by + 360) % 360)
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null)
  const [room, setRoom] = useState(0)
  const pane = useRef<HTMLDivElement>(null)

  useEffect(() => { setTurn(0); setNatural(null) }, [runId, page])

  // The page behind must not scroll while the dialog is open (it did on phones).
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [])

  // Escape closes it; R and L turn it. An officer reading a finding has a hand on the keyboard.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'r' || e.key === 'R') rotate(90)
      else if (e.key === 'l' || e.key === 'L') rotate(-90)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // The width the page has to fit into, kept current as the window changes.
  useEffect(() => {
    const el = pane.current
    if (!el) return
    const measure = () => setRoom(el.clientWidth - 2 * 16)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // A CSS rotation does not change the space an element takes up, so a page turned on its
  // side would spill out of the pane. The page is sized for its turned shape instead: fitted
  // to the pane's width, or at its own size, and the box around it is what gets laid out.
  const sideways = turn === 90 || turn === 270
  let frame: { w: number; h: number } | null = null
  let shown: { w: number; h: number } | null = null
  if (natural && room > 0) {
    const across = sideways ? natural.h : natural.w
    const scale = zoom ? 1 : room / across
    shown = { w: natural.w * scale, h: natural.h * scale }
    frame = sideways ? { w: shown.h, h: shown.w } : shown
  }

  // Drawn on <body>, not where it is used: the review screen animates its sections with a
  // transform, and inside a transformed element `position: fixed` is fixed to that element,
  // not the screen -- the dialog opened half off the top of the window.
  return createPortal(
    <div
      role="dialog" aria-modal="true" aria-label={`Page ${page}`}
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'var(--overlay, rgba(18,41,30,.72))', zIndex: 100,
        display: 'grid', placeItems: 'center', padding: 'clamp(6px, 2vw, 22px)',
        animation: 'enter .2s ease both', backdropFilter: 'blur(2px)',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: '#fff', borderRadius: 14, maxWidth: zoom ? '98vw' : 940,
          width: '100%', maxHeight: '92dvh', display: 'flex', flexDirection: 'column',
          boxShadow: 'var(--shadow-2)', overflow: 'hidden',
        }}
      >
        <div className="card-head" style={{ margin: 0, padding: 'var(--s4) var(--s5)' }}>
          <div>
            <h3 style={{ margin: 0 }}>Page {page}</h3>
            {doc && <div className="muted" style={{ fontSize: 'var(--t-small)' }}>{doc}</div>}
          </div>
          <div className="row preview-tools" style={{ gap: 'var(--s2)', flexWrap: 'wrap' }}>
            <button onClick={() => rotate(-90)} title="Rotate left (L)" aria-label="Rotate left">Rotate left</button>
            <button onClick={() => rotate(90)} title="Rotate right (R)" aria-label="Rotate right">Rotate right</button>
            <button onClick={() => setZoom(z => !z)}>
              {zoom ? 'Fit to width' : 'Actual size'}
            </button>
            <a className="btn" href={imageUrl(page).split('?')[0]} rel="noreferrer"
               onClick={e => { e.preventDefault(); openProtected(imageUrl(page).split('?')[0], `page ${page}`).catch(() => {}) }}
               style={{ textDecoration: 'none', display: 'inline-block',
                        padding: '11px 22px', border: '1px solid var(--line)',
                        borderRadius: 10, fontWeight: 600, color: 'var(--ink)' }}>
              Open full page ↗
            </a>
            <button className="primary" onClick={onClose}>Close</button>
          </div>
        </div>
        {/* minHeight 0: a flex child will not shrink below its content otherwise, and a tall
            page pushed the dialog's own header -- and its buttons -- off the top of the screen. */}
        <div ref={pane} style={{ overflow: 'auto', background: 'var(--bg)', padding: 16,
                                 flex: '1 1 auto', minHeight: 0 }}>
          <div style={{
            position: 'relative', margin: '0 auto',
            width: frame ? frame.w : '100%', height: frame ? frame.h : 'auto',
          }}>
            <img
              src={imageUrl(page)}
              alt={`Scanned page ${page}${turn ? `, turned ${turn}°` : ''}`}
              onLoad={e => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
              style={shown ? {
                position: 'absolute', left: '50%', top: '50%', width: shown.w, height: shown.h,
                maxWidth: 'none', transform: `translate(-50%, -50%) rotate(${turn}deg)`,
                transition: 'transform .2s ease',
                border: '1px solid var(--line)', background: '#fff',
              } : {
                display: 'block', width: '100%', border: '1px solid var(--line)', background: '#fff',
              }}
            />
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
