/** F17: "Back to the register" after a deep-link sign-in stays in the portal. */
import { beforeEach, describe, expect, it } from 'vitest'
import { _resetNavigations, inAppNavigations, navigate } from '../hash'

const settle = () => new Promise(r => setTimeout(r, 0))

describe('inAppNavigations', () => {
  // jsdom fires the hashchange of the set-up itself a tick later; let it land before counting.
  beforeEach(async () => { window.location.hash = '#/pension/cases/abc'; await settle(); _resetNavigations() })

  it('does not count a replace navigation (the move home after signing in at a deep link)', async () => {
    navigate('/', { replace: true })
    await settle()
    expect(inAppNavigations()).toBe(0)
  })

  it('counts a navigation that leaves a history entry', async () => {
    navigate('/pension/cases/xyz')
    await settle()
    expect(inAppNavigations()).toBe(1)
  })
})
