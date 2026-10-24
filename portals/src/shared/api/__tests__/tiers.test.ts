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
    // "Examination in progress / The examination takes 10 to 20 minutes..." sat above a live
    // bar, a running clock and the page being read, all of which say it as it happens.
    const ag = nextStep({ status: 'AI_CHECKING', allowed_actions: [] }, 'AG_SENIOR_AUDITOR')
    expect(ag.quiet).toBe(true)
    // The department has no analysis screen, only the fact that the office is on it.
    const dept = nextStep({ status: 'AI_CHECKING', allowed_actions: [] }, 'DEPT_OFFICER')
    expect(dept.quiet).toBeUndefined()
    expect(dept.text).toMatch(/Office of the Accountant General is examining/)
  })
  it('and no banner over the findings either', () => {
    // This one was kept on 22 Oct 2026 -- "it says what no button says" -- and the office
    // took it away on 24 Oct 2026. What it said was "Clear each finding, then approve,
    // return (naming the missing documents) or reject the case with a remark. Nothing is
    // approved or returned automatically": a band across the top of the screen telling an
    // officer to read the findings underneath it and press the buttons beside it.
    for (const role of ['AG_AO', 'AG_DAG', 'AG_REVIEWER']) {
      const step = nextStep({ status: 'UNDER_REVIEW', allowed_actions: ['APPROVE', 'REJECT', 'RETURN_TIER'] }, role)
      expect(step.quiet).toBe(true)
      expect(step.action).toBeNull()
    }
  })
  it('the department still hears what is happening to its case', () => {
    // The banners that went are the ones over a screen that already says it. A DDO has no
    // findings screen and no buttons, so the line is all they get.
    const dept = nextStep({ status: 'UNDER_REVIEW', allowed_actions: [] }, 'DEPT_OFFICER')
    expect(dept.quiet).toBeUndefined()
    expect(dept.text).toMatch(/Pension Wing is reviewing the case/)
  })
  it('starting a verification says that it started, and no more', () => {
    // "It takes 10 to 20 minutes; the outcome brings the case to you for a decision" went
    // on 24 Oct 2026: how long it takes is on the screen the officer is then looking at --
    // a bar, a page count and a running clock -- and for most claims it is not ten minutes.
    expect(ACTION_META.RUN_CHECK.done).toBe('Examination started.')
  })
})

describe('user form rules (C4)', () => {
  it('a tier officer takes a wing and no department; a DDO the reverse; the rest neither', () => {
    for (const r of ['AG_SENIOR_AUDITOR', 'AG_ASSISTANT_AO', 'AG_AO']) { expect(needsWing(r)).toBe(true); expect(needsDepartment(r)).toBe(false) }
    expect(needsWing('DEPT_OFFICER')).toBe(false); expect(needsDepartment('DEPT_OFFICER')).toBe(true)
    for (const r of ['AG_DAG', 'ADMIN']) { expect(needsWing(r)).toBe(false); expect(needsDepartment(r)).toBe(false) }
  })
  it("the AG's desk is two roles of its own: every tier, every wing, no wing field", () => {
    // One role for two offices until 24 Oct 2026 -- "AG / Additional AG and senior officers
    // (all wings, every tier)" -- so the register could not say which of them had acted.
    // Separated by name and not by power: tests/test_the_two_ag_desks_are_equal.py holds the
    // pair identical at every decision point, and the words here are just the two offices.
    expect(ROLE_WORDS.AG_REVIEWER).toBe('AG')
    expect(ROLE_WORDS.AG_ADDL).toBe('Additional AG')
    for (const r of ['AG_REVIEWER', 'AG_ADDL']) {
      expect(needsWing(r)).toBe(false)
      expect(needsDepartment(r)).toBe(false)
    }
    expect(CREATABLE_ROLES).toEqual(expect.arrayContaining(
      ['AG_SENIOR_AUDITOR', 'AG_ASSISTANT_AO', 'AG_AO', 'AG_DAG', 'AG_ADDL', 'AG_REVIEWER']))
  })
})
