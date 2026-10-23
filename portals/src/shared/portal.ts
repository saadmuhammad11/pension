/** Which portal this page is.
 *
 *  In the running system the portal server writes `window.__PORTAL__` into the page for the port
 *  it was served on. On the development server (:5300) the page asks the backend for the list
 *  and picks the one named by `?portal=<slug>`; with no slug it is the AG portal.
 */
import type { Theme } from './theme/types'

export interface PortalConfig {
  kind: 'ag' | 'department' | 'unknown'
  slug: string | null
  code: string | null
  name: string
  port: number
  is_police?: boolean
  theme: Theme
}

declare global {
  interface Window { __PORTAL__?: PortalConfig }
}

const AG_FALLBACK: PortalConfig = {
  kind: 'ag', slug: 'ag', code: null, name: 'Office of the Accountant General Punjab', port: 5184,
  theme: {
    // SERVE PUNJAB, named by the office 22 Oct 2026. The expansion is on the sign-in page and
    // not here: this subtitle is the header's second line on every screen (api/themes.py).
    title: 'SERVE PUNJAB', subtitle: 'Office of the Accountant General Punjab',
    primary: '#0E3527', primary2: '#18573F', primary3: '#1F6B4D', tint: '#EDF4EE', tint2: '#E2EEE8',
    accent: '#C9A227', accent2: '#E7C55B', ink: '#17211C', muted: '#5F6B64', line: '#E3E7E4', bg: '#F5F6F4',
  },
}

let resolved: PortalConfig | null = null

/** The portal, resolved once. Injected config wins; then the dev `?portal=` lookup; then the AG portal. */
export async function resolvePortal(): Promise<PortalConfig> {
  if (resolved) return resolved
  if (window.__PORTAL__ && window.__PORTAL__.kind !== 'unknown') {
    resolved = window.__PORTAL__
    return resolved
  }
  const slug = new URLSearchParams(window.location.search).get('portal')
  if (slug && slug !== 'ag') {
    try {
      const r = await fetch('/api/v2/portals', { signal: AbortSignal.timeout(5000) })
      if (r.ok) {
        const all = await r.json() as { ag: PortalConfig; departments: PortalConfig[] }
        const hit = all.departments.find(d => d.slug === slug)
        if (hit) { resolved = hit; return hit }
      }
    } catch { /* fall through to the AG portal */ }
  }
  resolved = window.__PORTAL__?.kind === 'unknown' ? { ...AG_FALLBACK, ...window.__PORTAL__, kind: 'ag', slug: 'ag' } : AG_FALLBACK
  return resolved
}

/** The portal after `resolvePortal()` has run (main.tsx awaits it before rendering). */
export function portal(): PortalConfig {
  return resolved ?? AG_FALLBACK
}

/** The self-running demo switches portals on one page; nothing in the served system calls this. */
export function setPortalForDemo(p: PortalConfig): void {
  resolved = p
}
