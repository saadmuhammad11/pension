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
import { readFileSync } from 'node:fs'

// From the project root: vitest runs with portals/ as its working directory, and
// import.meta.url is not a file URL under the jsdom transform.
const SHELL = readFileSync('src/shared/PortalShell.tsx', 'utf8')

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
