// The labels of the moves between tiers name the tier they go to (C3, 9 Oct 2026), by its
// full title since 22 Oct 2026: the office asked for "Assistant Accounts Officer (AAO)" and
// "Accounts Officer (AO)" wherever those desks are named.
import { describe, expect, it } from 'vitest'
import { ACTION_META, actionLabel, nextStep } from '../cases'
import { CREATABLE_ROLES, ROLE_WORDS, needsDepartment, needsWing } from '../../screens/admin/Users'

describe('tier moves', () => {
  it('forward names the next tier and return the previous one', () => {
    expect(actionLabel('FORWARD_TIER', 'SENIOR_AUDITOR')).toBe('Forward to Assistant Accounts Officer (AAO)')
    expect(actionLabel('FORWARD_TIER', 'ASSISTANT_AO')).toBe('Approve and forward to Accounts Officer (AO)')   // the AAO's forward is their approval
    expect(actionLabel('RETURN_TIER', 'AO')).toBe('Return to Assistant Accounts Officer (AAO)')
    expect(actionLabel('RETURN_TIER', 'ASSISTANT_AO')).toBe('Return to Senior Auditor')
    expect(actionLabel('FORWARD_TIER', null)).toBe('Forward to Assistant Accounts Officer (AAO)')   // no holder recorded: the Senior Auditor's
    expect(actionLabel('APPROVE', 'AO')).toBe(ACTION_META.APPROVE.label)
  })
  it('a return within the wing needs a remark; a forward does not', () => {
    expect(ACTION_META.RETURN_TIER.needsRemark).toBe('always')
    expect(ACTION_META.FORWARD_TIER.needsRemark).toBe('never')
  })
  it('a desk inside the wing draws no banner: the rail already shows forward and return', () => {
    // It read "Review the findings, then forward or return / Clear each finding and check the
    // documents. Forward the case to the next tier when every required document is present, or
    // return it with the list of what is missing" -- the two buttons, as prose, in a band above
    // the findings it was telling the officer to read (22 Oct 2026).
    const step = nextStep({ status: 'UNDER_REVIEW', allowed_actions: ['FORWARD_TIER', 'RETURN', 'REQUEST_DOCS'] }, 'AG_SENIOR_AUDITOR')
    expect(step.quiet).toBe(true)
    expect(step.action).toBeNull()
  })
  it('the examination draws no banner over itself', () => {
    // "Verification in progress / Verification takes 10 to 20 minutes..." sat above a live
    // bar, a running clock and the page being read, all of which say it as it happens.
    const ag = nextStep({ status: 'AI_CHECKING', allowed_actions: [] }, 'AG_SENIOR_AUDITOR')
    expect(ag.quiet).toBe(true)
    // The department has no analysis screen, only the fact that the office is on it.
    const dept = nextStep({ status: 'AI_CHECKING', allowed_actions: [] }, 'DEPT_OFFICER')
    expect(dept.quiet).toBeUndefined()
    expect(dept.text).toMatch(/Office of the Accountant General is verifying/)
  })
  it('the Accounts Officer keeps a banner: it says what no button says', () => {
    const ao = nextStep({ status: 'UNDER_REVIEW', allowed_actions: ['APPROVE', 'REJECT', 'RETURN_TIER'] }, 'AG_AO')
    expect(ao.title).toBe('Findings await your decision')
    expect(ao.quiet).toBeUndefined()
    expect(ao.text).toMatch(/Nothing is approved or returned automatically/)
  })
})

describe('user form rules (C4)', () => {
  it('a tier officer takes a wing and no department; a DDO the reverse; the rest neither', () => {
    for (const r of ['AG_SENIOR_AUDITOR', 'AG_ASSISTANT_AO', 'AG_AO']) { expect(needsWing(r)).toBe(true); expect(needsDepartment(r)).toBe(false) }
    expect(needsWing('DEPT_OFFICER')).toBe(false); expect(needsDepartment('DEPT_OFFICER')).toBe(true)
    for (const r of ['AG_DAG', 'ADMIN']) { expect(needsWing(r)).toBe(false); expect(needsDepartment(r)).toBe(false) }
  })
  it("the AG's desk is a role of its own: every tier, every wing, no wing field", () => {
    expect(ROLE_WORDS.AG_REVIEWER).toMatch(/every tier/)
    expect(needsWing('AG_REVIEWER')).toBe(false); expect(needsDepartment('AG_REVIEWER')).toBe(false)
    expect(CREATABLE_ROLES).toEqual(expect.arrayContaining(['AG_SENIOR_AUDITOR', 'AG_ASSISTANT_AO', 'AG_AO', 'AG_DAG', 'AG_REVIEWER']))
  })
})
