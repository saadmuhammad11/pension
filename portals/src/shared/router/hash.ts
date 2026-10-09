/** A hash router in seventy lines.
 *
 *  Every portal has a handful of flat routes -- the register, a case, a form -- and the built
 *  bundle already runs from `base: './'` so it can be opened from a sub-path or the filesystem.
 *  Hash routes need no server rewrite for that. A routing library would be a dependency to
 *  refetch on a machine that may lose its network, for nothing these portals use.
 */
import { useEffect, useState } from 'react'

export type Params = Record<string, string>

function current(): string {
  const raw = window.location.hash.replace(/^#/, '')
  return raw.startsWith('/') ? raw : '/' + raw
}

/** How many hash changes this page has seen that left a history entry behind them: zero means
 *  Back would leave the portal. A `replace` navigation (the move to the home page after a
 *  deep-link sign-in, a case settling on its product's address) leaves no entry, so it is not
 *  counted; counting it sent "Back to the register" out of the portal (frontend review F17). */
let navigations = 0
let replacing = 0
if (typeof window !== 'undefined') window.addEventListener('hashchange', () => {
  if (replacing > 0) { replacing -= 1; return }
  navigations += 1
})
export const inAppNavigations = () => navigations
/** Tests only: forget what this page has seen. */
export const _resetNavigations = () => { navigations = 0; replacing = 0 }

/** The path after `#`, re-rendered on every change. Always begins with `/`. */
export function useHashPath(): string {
  const [path, setPath] = useState(current)
  useEffect(() => {
    const onChange = () => setPath(current())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return path
}

export function navigate(to: string, { replace = false } = {}): void {
  const target = '#' + (to.startsWith('/') ? to : '/' + to)
  if (replace) {
    // The hashchange this fires must not count as a step Back could retrace (see above); a
    // replace to the address already shown fires none, so only a real change is expected.
    if (window.location.hash !== target) replacing += 1
    window.location.replace(target)
  } else window.location.hash = target
}

/** `match('/cases/:id', '/cases/abc')` → `{ id: 'abc' }`; `null` where the shapes differ. */
export function match(pattern: string, path: string): Params | null {
  const p = pattern.split('/').filter(Boolean)
  const q = path.split('?')[0].split('/').filter(Boolean)
  if (p.length !== q.length) return null
  const params: Params = {}
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(':')) { try { params[p[i].slice(1)] = decodeURIComponent(q[i]) } catch { params[p[i].slice(1)] = q[i] } }
    else if (p[i] !== q[i]) return null
  }
  return params
}

/** The query string of the current hash route, as a map. */
export function query(path: string): Params {
  const i = path.indexOf('?')
  if (i < 0) return {}
  return Object.fromEntries(new URLSearchParams(path.slice(i + 1)))
}

export function href(to: string): string {
  return '#' + (to.startsWith('/') ? to : '/' + to)
}
