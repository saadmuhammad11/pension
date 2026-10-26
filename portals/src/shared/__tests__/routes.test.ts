/** Every route the shell draws is a route the shell's guard knows.
 *
 *  24 Oct 2026: #/account was added to the renderer and not to `known`, so the guard called it
 *  a wrong address and sent the officer home -- which for a Deputy AG is the pension
 *  dashboard. The screen existed, the link existed, and pressing it opened the dashboard.
 *
 *  The two lists are in the same file a dozen lines apart and still came apart, so this reads
 *  them both rather than trusting that the next one will be remembered.
 */
import { describe, expect, it } from 'vitest'
import { registerView } from '../screens/registerView'
// The shell's own source, as text. Vite's ?raw rather than node:fs: this project has no
// node types, and the bundler already knows how to hand a file over as a string.
import SHELL from '../PortalShell.tsx?raw'

/** The fixed paths the renderer branches on: `cleanPath === '/x'` below the guard. */
const drawn = () => {
  const body = SHELL.slice(SHELL.indexOf('let body: ReactNode'))
  return [...body.matchAll(/cleanPath === '(\/[a-z-]*)'/g)].map(m => m[1])
}
/** The fixed paths the guard accepts. */
const known = () => {
  const guard = SHELL.slice(SHELL.indexOf('const known ='), SHELL.indexOf('if (!known'))
  return [...guard.matchAll(/cleanPath === '(\/[a-z-]*)'/g)].map(m => m[1])
}

describe('the shell draws only what its guard lets through', () => {
  it('finds the two lists', () => {
    expect(drawn().length).toBeGreaterThan(1)
    expect(known().length).toBeGreaterThan(1)
  })

  it('every path the renderer draws is one the guard knows', () => {
    const missing = drawn().filter(p => !known().includes(p))
    expect(missing).toEqual([])
  })

  it('the account screen in particular', () => {
    expect(known()).toContain('/account')
    expect(drawn()).toContain('/account')
  })

  it('and it is allowed only for the desks that may manage their own profile', () => {
    const guard = SHELL.slice(SHELL.indexOf('const allowed ='), SHELL.indexOf('if (!known'))
    expect(guard).toContain("cleanPath !== '/account' || MAY_MANAGE_OWN_PROFILE.includes(user.role)")
  })
})

/** The tabs are an order; where a role lands is not (26 Oct 2026).
 *
 *  The nav listed Cases then Dashboard from 22 Oct and now lists Dashboard then Cases. That
 *  is a change to the bar and nothing else: a department still opens on its cases and the
 *  Office on the dashboard, which is registerView's answer and not the nav's. The two were
 *  tied together once -- each side listed whichever tab that role opened on first -- so the
 *  rule that replaced it is written down here rather than left to the next reader to infer.
 */
describe('swapping the tabs did not move anyone\'s landing screen', () => {
  it('a department opens on its cases', () => {
    expect(registerView('home', 'register')).toBe('cases')
  })

  it('the Office of the Accountant General and the administrator open on the dashboard', () => {
    expect(registerView('home', 'review')).toBe('dashboard')
    expect(registerView('home', 'admin')).toBe('dashboard')
  })

  it('and an address that names a face still wins, whoever is asking', () => {
    for (const home of ['register', 'review', 'admin'] as const) {
      expect(registerView('cases', home)).toBe('cases')
      expect(registerView('dashboard', home)).toBe('dashboard')
    }
  })
})

describe('the nav lists Dashboard before Cases, on both sides', () => {
  it('in that order, once, in the product tab group', () => {
    const tabs = [...SHELL.matchAll(/>(Dashboard|Cases)<\/a>/g)].map(m => m[1])
    expect(tabs).toEqual(['Dashboard', 'Cases'])
  })
})
