// The labels of the moves between tiers name the tier they go to (C3, 9 Oct 2026).
import { describe, expect, it } from 'vitest'
import { ACTION_META, actionLabel, nextStep } from '../cases'
import { CREATABLE_ROLES, ROLE_WORDS, needsDepartment, needsWing } from '../../screens/admin/Users'

describe('tier moves', () => {
  it('forward names the next tier and return the previous one', () => {
    expect(actionLabel('FORWARD_TIER', 'SENIOR_AUDITOR')).toBe('Forward to Assistant AO')
    expect(actionLabel('FORWARD_TIER', 'ASSISTANT_AO')).toBe('Approve and forward to AO')   // the AAO's forward is their approval
    expect(actionLabel('RETURN_TIER', 'AO')).toBe('Return to Assistant AO')
    expect(actionLabel('RETURN_TIER', 'ASSISTANT_AO')).toBe('Return to Senior Auditor')
    expect(actionLabel('FORWARD_TIER', null)).toBe('Forward to Assistant AO')      // no holder recorded: the Senior Auditor's
    expect(actionLabel('APPROVE', 'AO')).toBe(ACTION_META.APPROVE.label)
  })
  it('a return within the wing needs a remark; a forward does not', () => {
    expect(ACTION_META.RETURN_TIER.needsRemark).toBe('always')
    expect(ACTION_META.FORWARD_TIER.needsRemark).toBe('never')
  })
  it('the next step for a Senior Auditor holding a verified case is to review and forward or return', () => {
    const step = nextStep({ status: 'UNDER_REVIEW', allowed_actions: ['FORWARD_TIER', 'RETURN', 'REQUEST_DOCS'] }, 'AG_SENIOR_AUDITOR')
    expect(step.title).toMatch(/forward or return/)
    const ao = nextStep({ status: 'UNDER_REVIEW', allowed_actions: ['APPROVE', 'REJECT', 'RETURN_TIER'] }, 'AG_AO')
    expect(ao.title).toBe('Findings await your decision')
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
