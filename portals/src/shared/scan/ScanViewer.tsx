/** The page-scanning view: a document page with a scan line moving over it. 30 Sep 2026.
 *
 *  Shared by the pension AI Analysis screen and the GP Fund reading screen, and knows nothing
 *  of either: the caller says which page to show, what to label it, and whether the work is
 *  live. Everything it does is presentation:
 *
 *  *   **No blank frames.** A new page is fetched and decoded off screen first; only then does
 *      it cross-fade in over the page already showing. A page that fails to load leaves the
 *      current one in place.
 *  *   **The scan line sweeps the page, not the frame.** It lives inside the page's own box, so
 *      a landscape table, a sideways CNIC and a full A4 scan are each swept edge to edge. It is
 *      a transform animation on its own layer: no layout work per frame.
 *  *   **The frame never resizes.** A fixed aspect ratio (4:3, 3:4 on a phone); the page is
 *      fitted inside it whatever its shape.
 *  *   **Calm when slow.** The line keeps its pace however long the backend takes; the caller's
 *      `note` appears beneath instead of the view freezing or restarting.
 *  *   **A clean finish.** `state="done"` fades the line out and shows a quiet check.
 *
 *  Themed with CSS variables on any ancestor: --scan-accent (the line and the check),
 *  --scan-bg (the frame). Honours prefers-reduced-motion.
 *
 *  Props
 *    src      URL of the page to show, or null while there is none yet (a waiting state)
 *    pageKey  identity of the page (its number); a change is what triggers the cross-fade
 *    label    the overlay on the page ("Cross-checking · NADRA FRC"); null for none
 *    caption  [left, right] under the page ("Page 6 of 15", "Checklist & consistency")
 *    state    'live' | 'done' | 'failed'
 *    note     a line under the frame while the backend is slow; null for none
 *    waiting  the text of the waiting state, before the first page exists
 */
import { useEffect, useRef, useState } from 'react'
import './scan.css'

export type ScanState = 'live' | 'done' | 'failed'

interface Layer { key: string; url: string; revoke: boolean }

export function ScanViewer({ src, pageKey, label, caption, state = 'live', note, waiting = 'Preparing the pages…' }: {
  src: string | null
  pageKey: string | number | null
  label?: string | null
  caption?: [string, string]
  state?: ScanState
  note?: string | null
  waiting?: string
}) {
  const [front, setFront] = useState<Layer | null>(null)
  const [back, setBack] = useState<Layer | null>(null)
  const wanted = useRef<string | null>(null)
  const layers = useRef<Layer[]>([])

  // Fetch and decode the next page off screen; cross-fade only once it can be drawn at once.
  useEffect(() => {
    if (!src || pageKey === null) return
    const key = String(pageKey)
    if (front?.key === key) return
    wanted.current = key
    let cancelled = false
    ;(async () => {
      let url = src, revoke = false
      try {
        const r = await fetch(src, { cache: 'force-cache' })
        if (!r.ok) throw new Error(String(r.status))
        url = URL.createObjectURL(await r.blob()); revoke = true
        const img = new Image()
        img.src = url
        await img.decode().catch(() => undefined)
      } catch {
        // Could not fetch it ahead: fall back to the address itself (the <img> will try); if
        // even that is not the page still wanted, keep what is showing.
        if (cancelled || wanted.current !== key) return
      }
      if (cancelled || wanted.current !== key) { if (revoke) URL.revokeObjectURL(url); return }
      const next = { key, url, revoke }
      layers.current.push(next)
      setFront(prev => { setBack(prev); return next })
    })()
    return () => { cancelled = true }
  }, [src, pageKey])   // eslint-disable-line react-hooks/exhaustive-deps

  // Free the blobs of pages no longer on screen.
  useEffect(() => {
    const keep = new Set([front?.url, back?.url])
    layers.current = layers.current.filter(l => {
      if (keep.has(l.url)) return true
      if (l.revoke) URL.revokeObjectURL(l.url)
      return false
    })
  }, [front, back])
  useEffect(() => () => { layers.current.forEach(l => l.revoke && URL.revokeObjectURL(l.url)) }, [])

  return (
    <div className={`scan scan-${state}`} data-live-analysis={state === 'live' ? '' : undefined}>
      <div className="scan-frame">
        {!front ? (
          <div className="scan-waiting">
            <div className="scan-orbit" aria-hidden="true"><span /><span /><span /></div>
            <div>{waiting}</div>
          </div>
        ) : (
          <>
            {back && back.key !== front.key && (
              <div className="scan-sheet scan-out" key={`b${back.key}`} onAnimationEnd={() => setBack(null)}>
                <img src={back.url} alt="" />
              </div>
            )}
            <div className="scan-sheet scan-in" key={`f${front.key}`}>
              <img src={front.url} alt={caption?.[0] ?? 'Page'} />
              <div className="scan-line" aria-hidden="true" />
            </div>
            {state === 'done' && <div className="scan-check" aria-hidden="true">✓</div>}
          </>
        )}
        {label && front && <div className="scan-label" key={label}>{label}</div>}
        {caption && (
          <div className="scan-caption">
            <span>{caption[0]}</span>
            <span>{caption[1]}</span>
          </div>
        )}
      </div>
      <div className="scan-note" aria-live="polite">{note ?? ''}</div>
    </div>
  )
}
