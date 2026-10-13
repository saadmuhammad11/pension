import { anyCaseTypeLabel } from './caseTypes'
/** The officer's words for the system's tokens.
 *
 *  Every identifier below is real and load-bearing inside the engine -- `FORM_D_II` selects a
 *  pension formula, `CONTRA-IDENTITY` selects a letter. None of them belong on a screen an
 *  Accountant General's auditor is reading. A page that says "EXTRACT-ROLE-SWAP" is asking the
 *  reader to learn our vocabulary before they can do their job.
 *
 *  So the tokens stay in the data, where they are checkable and stable, and this file is the
 *  only place they become English. Anything without an entry falls back to a de-underscored
 *  form rather than disappearing -- an unlabelled token is a gap to fill, not a thing to hide.
 */

const humanise = (token: string) =>
  token.replace(/_/g, ' ').toLowerCase().replace(/^./, c => c.toUpperCase())

/** Document types, as the office names the papers. */
const DOCUMENTS: Record<string, string> = {
  FORM_B_I: 'Form B-I — pension sanction (superannuation or retiring)',
  FORM_B_II: 'Form B-II — anticipatory pension sanction',
  FORM_B_III: 'Form B-III — final pension after anticipatory',
  FORM_B_IV: 'Form B-IV — pension sanction (invalid or compulsory retirement)',
  FORM_D_I: 'Form D-I — family pension sanction (death in service)',
  FORM_D_II: 'Form D-II — family pension sanction (death of a pensioner)',
  ANNEX_A: 'Annexure-A — descriptive roll and undertaking',
  NADRA_DEATH_CERTIFICATE: 'Death certificate (NADRA)',
  DEATH_CERTIFICATE: 'Death certificate',
  NADRA_FRC: 'Family Registration Certificate (NADRA)',
  CNIC: 'CNIC copy',
  CNIC_DECEASED: 'CNIC of the deceased',
  CNIC_CLAIMANT: 'CNIC of the claimant',
  SUCCESSION_CERTIFICATE: 'Succession certificate',
  LPC: 'Last Pay Certificate',
  SALARY_STATEMENT: 'Salary statement',
  SERVICE_STATEMENT: 'Service statement',
  SERVICE_BOOK: 'Service book',
  QUALIFYING_SERVICE_PROFORMA: 'Proforma for qualifying service',
  POSTING_ORDER: 'Posting or service order',
  DEPUTATION_CHALLANS: 'Deputation contribution challans',
  PPO: 'Pension Payment Order',
  FPPO: 'Family Pension Payment Order',
  PENSION_SLIP: 'Pension payment slip',
  FORWARDING_LETTER: 'Forwarding letter',
  DEATH_OFFICE_ORDER: 'Death office order or obituary',
  OBITUARY: 'Obituary notification',
  NDC: 'No Demand / No Enquiry certificate',
  COMPULSORY_RETIREMENT_ORDER: 'Compulsory retirement order',
  NAME_CHANGE_ORDER: 'Name change order',
  MEDICAL_BOARD_CERTIFICATE: 'Medical board certificate',
  SUPERANNUATION_ORDER: 'Superannuation order',
  VOLUNTARY_RETIREMENT_REQUEST: 'Voluntary retirement request',
  PHOTOGRAPHS: 'Photographs',
  SPECIMEN_SIGNATURES: 'Specimen signatures',
  BANK_OPTION_FORM: 'Bank option form',
  NON_REMARRIAGE_CERTIFICATE: 'Non-remarriage certificate',
  MATRIC_CERTIFICATE: 'Educational certificate',
  SOLE_WIDOW_CERTIFICATE: 'Sole widow certificate',
  NO_REGULAR_INCOME_CERTIFICATE: 'No-regular-income certificate',
  ARREARS_ENTITLEMENT_CERTIFICATE: 'Arrears entitlement certificate',
  LATE_SUBMISSION_REASON: 'Reason for late submission',
  DIVORCE_CERTIFICATE: 'Divorce certificate',
  NIKAH_NAMA: 'Marriage registration (Nikah Nama)',
  AFFIDAVIT: 'Affidavit',
  BANK_FILE: 'Bank file / half',
  COMMUTATION_OPTION: 'Commutation option',
  LIFE_CERTIFICATE: 'Life certificate',
  FILE_COVER: 'File cover',
  OTHER: 'Not identified',
}

/** What a finding is, said plainly. The class is a routing key, not a description. */
const FINDINGS: Record<string, string> = {
  'CONTRA-IDENTITY': 'Identity details do not agree',
  'CONTRA-FAMILY': 'Family details do not agree',
  'CONTRA-MONEY': 'Amounts do not agree',
  'CONTRA-DATE': 'Dates cannot all be true',
  'SERVICE-SHORT': 'Service under the minimum for a monthly pension',
  'RELATION-INELIGIBLE': 'Verify relation eligibility (draft list)',
  'CONTRA-SERVICE': 'Service record does not agree',
  'RULE-CAP': 'Exceeds a statutory limit',
  'RULE-UNDECLARED': 'Recovery not declared on the sanction',
  'AUTH-DEFECT': 'Signature or attestation defect',
  'SPECIMEN-CHECK': 'Signature to compare with the specimen',
  'RELATIONSHIP-UNPROVED': 'Relationship not proved by a document',
  'SLA-BREACH': 'Statutory timeline exceeded',
  'ALIAS-RESOLVED': 'Name spelt differently across documents',
  'SCOPE-CONFUSION': 'Document applied outside its scope',
  'EXTRACT-LOWCONF': 'A page could not be read',
  'CROSS-CHECKS-NOT-RUN': 'The cross-document checks did not run',
  'DATE-AMBIGUOUS': 'A date written with a two-digit year',
  'EXTRACT-DISAGREE': 'Two reads of a page disagree',
  'EXTRACT-ROLE-SWAP': 'Deceased and claimant roles',
}

const STATUSES: Record<string, string> = {
  PRESENT: 'Present',
  MISSING: 'Not found',
  DEFECTIVE: 'Defective',
  NOT_APPLICABLE: 'Not required',
  NOT_REQUIRED: 'Not Required',
  FOUND_NOT_REQUIRED: 'Found (Not Required)',
  WAIVED: 'Approved',
}

const VERDICTS: Record<string, string> = {
  FORWARD: 'Ready to forward',
  RETURN_FOR_CORRECTION: 'Return to department for correction',
  HOLD: 'Hold for exceptional review',
}

// The case-type labels come from config/case_types.json (29 Sep 2026), shared with the rules.

export const documentLabel = (t: string) => DOCUMENTS[t] ?? humanise(t)
export const findingLabel = (c: string) => FINDINGS[c] ?? humanise(c.replace(/-/g, ' '))
export const statusLabel = (s: string) => STATUSES[s] ?? humanise(s)
export const verdictLabel = (v: string) => VERDICTS[v] ?? humanise(v)
export const caseTypeLabel = (t: string | null | undefined) =>
  anyCaseTypeLabel(t) ?? (t ? humanise(t) : 'not yet determined')

/** A national identity number on a screen reads 35201-•••••••-2 unless the officer asks to see
 *  it. Only the middle group is hidden, so a number can still be matched against a paper. */
export const maskIds = (text: string) => text.replace(/\b(\d{5})-\d{7}-(\d)\b/g, '$1-•••••••-$2')
export const hasId = (text: string) => /\b\d{5}-\d{7}-\d\b/.test(text)

/** Model confidence in words; the exact figure belongs in a tooltip, not in a column. */
export const confidenceWord = (c: number) => c >= 0.9 ? 'High' : c >= 0.7 ? 'Medium' : 'Low'

/** An office name a registry typed in capitals, in title case; acronyms stay as they are. */
const ACRONYMS = new Set(['NADRA', 'CNIC', 'PPO', 'FPPO', 'FRC', 'SOP', 'AG', 'PSA', 'DDO', 'CTS', 'SAP', 'GPF', 'ID', 'PDF', 'DAO', 'C&W', 'S&GAD', 'P&D', 'IT'])
export const titleCase = (s: string) =>
  s === s.toUpperCase() && /[A-Z]{4,}/.test(s)
    ? s.toLowerCase().replace(/[\p{L}&']+/gu, w => ACRONYMS.has(w.toUpperCase()) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1))
    : s
