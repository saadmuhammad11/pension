/** Switching product must not switch the tab (22 Oct 2026).
 *
 *  "when i switch from pension to gp fund or gpfund to pension the options between the cases
 *  and dashboard auto selects the cases" -- both header links were hard-wired to
 *  #/{slug}/cases, so an officer on a dashboard was moved off it. */
import { describe, expect, it } from 'vitest'
import { productHref } from './productSwitch'

describe('productHref', () => {
  it('a department reading a dashboard stays on the dashboard', () => {
    expect(productHref('GPF', 'dashboard', 'register')).toBe('#/gpf/dashboard')
    expect(productHref('PENSION', 'dashboard', 'register')).toBe('#/pension/dashboard')
  })

  it("the Accountant General's dashboard is the bare address, and it is kept too", () => {
    expect(productHref('GPF', 'home', 'review')).toBe('#/gpf')
    expect(productHref('PENSION', 'dashboard', 'review')).toBe('#/pension')
    expect(productHref('GPF', 'home', 'admin')).toBe('#/gpf')
  })

  it('cases stay cases, whoever is looking', () => {
    for (const home of ['register', 'review', 'admin'] as const) {
      expect(productHref('GPF', 'cases', home)).toBe('#/gpf/cases')
    }
  })

  it("a department's bare address is its cases, so that tab is what it carries", () => {
    expect(productHref('GPF', 'home', 'register')).toBe('#/gpf/cases')
  })

  it('from a case or the filing form, each role lands where its product opens', () => {
    for (const view of ['case', 'analysis', 'new'] as const) {
      expect(productHref('GPF', view, 'register')).toBe('#/gpf/cases')
      expect(productHref('GPF', view, 'review')).toBe('#/gpf')
    }
  })

  it('with no product at all, the same rule decides', () => {
    expect(productHref('PENSION', undefined, 'register')).toBe('#/pension/cases')
    expect(productHref('PENSION', undefined, 'review')).toBe('#/pension')
  })
})
