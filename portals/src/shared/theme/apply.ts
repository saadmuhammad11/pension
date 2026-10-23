/** Write a theme into the CSS variables the screens already use.
 *
 *  The shared stylesheet (styles/base.css) was written for one portal, in the AG's green and
 *  gold, and every screen reaches for `var(--green)`, `var(--sage)`, `var(--gold)` and so on.
 *  Rather than rename thirty variables across every file, a theme is poured into those same
 *  names: on the Police portal `--green` is navy. The names are historical; the values are the
 *  department's.
 */
import type { Theme } from './types'

function rgba(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const n = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement.style
  const set = (name: string, value: string) => root.setProperty(name, value)
  set('--green', theme.primary)
  set('--green2', theme.primary2)
  set('--green3', theme.primary3)
  set('--sage', theme.tint)
  set('--sage2', theme.tint2)
  set('--gold', theme.accent)
  set('--gold2', theme.accent2)
  set('--ink', theme.ink)
  set('--muted', theme.muted)
  set('--line', theme.line)
  set('--bg', theme.bg)
  // Flat surfaces (28 Sep 2026): a hairline instead of a shadow; one soft shadow for what floats.
  set('--shadow-1', 'none')
  set('--shadow-2', '0 8px 24px -12px rgba(23,33,28,.18)')
  set('--ring', `0 0 0 3px ${rgba(theme.primary3, 0.28)}`)
  set('--accent-a18', rgba(theme.accent, 0.18))
  set('--accent-a55', rgba(theme.accent, 0.55))
  set('--overlay', rgba(theme.primary, 0.72))
  // The tab says what the header says: the portal, then whose office runs it (23 Oct 2026).
  // It was "SERVE PUNJAB — Government of the Punjab", the one place the phrase outlived the
  // header bar, and the one a bookmark keeps.
  document.title = `${theme.title} — ${theme.subtitle}`
  let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (!meta) {
    meta = document.createElement('meta')
    meta.name = 'theme-color'
    document.head.appendChild(meta)
  }
  meta.content = theme.primary
}
