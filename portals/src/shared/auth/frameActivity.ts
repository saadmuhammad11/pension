/** What the GP Fund frame tells the portal, and how the portal makes sure it was the frame
 *  (frontend review F9, 9 Oct 2026).
 *
 *  The idle timer used to hear only the parent window, so an officer working inside the GP Fund
 *  module for half an hour was signed out under their hands. The module's page now posts
 *  `{gpfActivity: 1}` (throttled) on pointer and key events and `{gpfExpired: 1}` when its own
 *  sign-in cookie is refused. A message counts only when it comes from this origin AND from the
 *  window of a frame this portal opened; anything else is ignored. */

const frames = new Set<Window>()

/** The case screen registers the GP Fund frame's window while it is on screen. */
export function registerGpfFrame(win: Window | null | undefined): () => void {
  if (!win) return () => {}
  frames.add(win)
  return () => { frames.delete(win) }
}

export type FrameMessage = { kind: 'activity' } | { kind: 'expired' } | null

/** The frame's message, or null for anything that is not a registered frame's own word. */
export function readFrameMessage(e: { origin: string; source: unknown; data: unknown }, origin = window.location.origin,
                                 known: Set<Window> = frames): FrameMessage {
  if (e.origin !== origin) return null
  if (!e.source || !known.has(e.source as Window)) return null
  const d = e.data as { gpfActivity?: unknown; gpfExpired?: unknown } | null
  if (!d || typeof d !== 'object') return null
  if (d.gpfExpired) return { kind: 'expired' }
  if (d.gpfActivity) return { kind: 'activity' }
  return null
}

const expiredListeners = new Set<() => void>()
/** The frame's sign-in has lapsed: whoever shows the frame re-signs it and reloads it. */
export function onGpfExpired(fn: () => void): () => void {
  expiredListeners.add(fn)
  return () => { expiredListeners.delete(fn) }
}
export function gpfExpired(): void { expiredListeners.forEach(l => l()) }
