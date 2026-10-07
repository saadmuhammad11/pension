/** The case-level API: /api/v2/cases and /api/v2/departments. Shapes mirror api/v2.py. */
import { get, post, postForm } from './client'

export type CaseStatus =
  | 'DRAFT' | 'AI_CHECKING' | 'AI_FAILED' | 'AI_CHECKED' | 'FORWARDED' | 'UNDER_REVIEW'
  | 'APPROVED' | 'REJECTED' | 'RETURNED' | 'DOCS_REQUESTED'

export type CaseAction =
  | 'ADD_DOCS' | 'RUN_CHECK' | 'FORWARD' | 'TAKE_UP' | 'APPROVE' | 'REJECT' | 'RETURN'
  | 'REQUEST_DOCS' | 'OVERRIDE'

export interface CaseRun {
  id: string
  case_id: string
  run_id: string
  submission_no: number
  started_by: string
  started_at: string
  finished_at: string | null
  state: 'queued' | 'running' | 'done' | 'failed'
  verdict: string | null
  high_flags: number | null
  blocking_flags: string[]
  checklist_result: string | null
  error: string | null
  auto_forward: number
}

export interface CaseEvent {
  id: string
  seq: number
  action: string
  from_status: CaseStatus | null
  to_status: CaseStatus
  actor_id: string | null
  actor_name: string | null
  actor_role: string | null
  actor_department: string | null
  remark: string
  payload: Record<string, unknown>
  run_id: string | null
  at: string
}

export interface CaseDocument {
  id: string
  submission_no: number
  seq: number
  filename: string
  sha256: string
  bytes: number
  uploaded_by: string
  uploaded_at: string
  /** The document this one was filed in place of (30 Sep 2026). */
  replaces_document_id?: string | null
  /** The round in which the department replaced this document; it is no longer read. */
  superseded_in_submission?: number | null
}

export interface OpenIssues {
  verdict: string | null
  blocking_flags: string[]
  high_flags: { id: string; title: string; class: string }[]
  missing_checklist: { id: string; requirement: string; status: string }[]
  checklist_result: string | null
  claimant_name?: string | null
  has_issues: boolean
}

/** The two products behind one portal (28 Sep 2026): pension cases, and GP Fund claims examined by the GP Fund module. */
export type Product = 'PENSION' | 'GPF'
export const PRODUCT_SLUG: Record<Product, string> = { PENSION: 'pension', GPF: 'gpf' }
export const PRODUCT_OF_SLUG: Record<string, Product> = { pension: 'PENSION', gpf: 'GPF', gpfund: 'GPF' }
/** A case's own address, under its product (30 Sep 2026), so the header knows which product is open. */
export const caseHref = (product: Product, id: string, analysis = false) =>
  `/${PRODUCT_SLUG[product]}/cases/${encodeURIComponent(id)}${analysis ? '/analysis' : ''}`
export const PRODUCT_WORDS: Record<Product, { name: string; cases: string; file: string; verify: string }> = {
  PENSION: { name: 'Pension', cases: 'Pension cases', file: 'File a pension case', verify: 'Verify case with AI' },
  GPF: { name: 'GP Fund', cases: 'GP Fund cases', file: 'File a GP Fund case', verify: 'Examine with AI' },
}
/** The kinds of GP Fund claim the module's reader accepts. */
export const GPF_KINDS: { id: string; label: string }[] = [
  { id: 'final', label: 'Final payment' }, { id: 'death', label: 'Final payment — death' }, { id: 'dismissal', label: 'Final payment — dismissal' },
  { id: 'refundable', label: 'Refundable advance' }, { id: 'nonrefundable', label: 'Non-refundable advance' },
  { id: 'missing_credits', label: 'Missing credits' }, { id: 'balance_transfer', label: 'Balance transfer' },
]
export const gpfKindLabel = (id: string | null | undefined) => GPF_KINDS.find(k => k.id === id)?.label ?? (id ?? '')

interface CaseBase {
  id: string
  case_no: string
  department_code: string
  department_name: string
  pension_section: string | null
  created_via: 'DEPARTMENT'
  product: Product
  /** The GP Fund module's own case, once its examination has read the papers. */
  gpf_case_id: string | null
  created_by: string
  status: CaseStatus
  status_label: string
  claimant_name: string | null
  variant: string | null
  /** The pension case type the case is worked as (config/case_types.json), and where it came from:
   *  DECLARED by the department, CORRECTED by the AG, or DETECTED by the AI for a case filed before
   *  the declaration existed. The AI's own reading is kept beside it (AG only). */
  case_type: string | null
  case_type_source: 'DECLARED' | 'CORRECTED' | 'DETECTED' | null
  detected_case_type: string | null
  detected_case_type_confidence: number | null
  intake: Record<string, unknown>
  submission_no: number
  current_run_id: string | null
  created_at: string
  updated_at: string
  latest_run: CaseRun | null
}

export interface CaseSummary extends CaseBase {
  documents: number
  last_event: { action: string; remark: string; actor_name: string | null; actor_role: string | null; at: string } | null
}

export interface CaseFull extends CaseBase {
  documents: CaseDocument[]
  runs: CaseRun[]
  events: CaseEvent[]
  forwarded_with: OpenIssues | null
  officer_remark: string | null
  allowed_actions: CaseAction[]
}

export interface Department { code: string; name: string; digital: number; pension_section: string | null }

export interface DepartmentCount {
  code: string
  name: string
  digital: boolean
  /** The AG office's Pension section (Pension-I .. V) that works the department's cases; null for the legacy bucket. */
  pension_section: string | null
  total: number
  awaiting_review: number
  by_status: Partial<Record<CaseStatus, number>>
}

export const getCase = (id: string) => get<CaseFull>(`/api/v2/cases/${encodeURIComponent(id)}`)

export interface NewCaseFields {
  product?: Product
  /** Mandatory for a pension case. */
  case_type?: string
  gpf_kind?: string
  gazetted?: string
  department_code?: string
  claimant_name?: string
  variant?: string
  annual_pay?: Record<string, string>
  commutation_percent?: string
  retirement_date?: string
  pension_in_payment?: string
  date_of_death?: string
}

export function createCase(files: File[], fields: NewCaseFields) {
  const form = new FormData()
  files.forEach(f => form.append('files', f))
  form.append('product', fields.product ?? 'PENSION')
  if (fields.case_type) form.append('case_type', fields.case_type)
  if (fields.gpf_kind) form.append('gpf_kind', fields.gpf_kind)
  if (fields.gazetted) form.append('gazetted', fields.gazetted)
  if (fields.department_code) form.append('department_code', fields.department_code)
  if (fields.claimant_name) form.append('claimant_name', fields.claimant_name)
  if (fields.variant) form.append('variant', fields.variant)
  if (fields.annual_pay && Object.keys(fields.annual_pay).length) form.append('annual_pay', JSON.stringify(fields.annual_pay))
  for (const k of ['commutation_percent', 'retirement_date', 'pension_in_payment', 'date_of_death'] as const) {
    if (fields[k]) form.append(k, fields[k] as string)
  }
  return postForm<{ case: CaseFull }>('/api/v2/cases', form)
}

/** Put a corrected paper in place of one already filed; the old one stays on file, superseded. */
export function replaceDocument(caseId: string, docId: string, file: File) {
  const form = new FormData()
  form.append('files', file)
  return postForm<CaseFull>(`/api/v2/cases/${encodeURIComponent(caseId)}/documents/${encodeURIComponent(docId)}/replace`, form)
}

/** The record of each submission round (api.rounds). `checks` is the AG's only. */
export interface RoundCheck {
  run_id: string; mode: 'FULL' | 'INCREMENTAL'; base_run_id: string | null; base_submission_no: number | null
  started_at: string; finished_at: string | null; state: string; duration_s: number | null
  documents: { id: string; filename: string; submission_no: number; status: 'EARLIER' | 'NEW' | 'REPLACEMENT' | 'SUPERSEDED' }[]
  steps: { mode?: string; pages_total?: number; pages_read?: number; pages_reused?: number; new_pages?: number[]; duration_s?: number | null
           steps?: Record<string, { run?: number | string; reused?: number | Record<string, number> }> }
  resolution: (RequestItem & { resolution: string; located?: number[]; on_new_pages?: boolean })[]
  changes: { new?: RoundFinding[]; cleared?: RoundFinding[]; unchanged?: RoundFinding[] }
  carried: { dispositions?: { flag_id: string; from_flag_id: string; action: string; officer: string }[]; checklist?: { action: string; item_id: string | null }[] }
}
export interface RoundFinding { id: string; severity: string; class: string; title: string; pages: number[]; from_new_documents: boolean }
export interface CaseRound {
  submission_no: number; opened_at: string; submitted_at: string | null; closed_at: string | null; closed_action: string | null
  requests: { action: string; items: RequestItem[]; remark: string; by: string | null; at: string }[]
  documents: { id: string; filename: string; uploaded_at: string; replaces: string | null; superseded_in_submission: number | null }[]
  checks?: RoundCheck[]
  requested_items?: { id: string | null; label: string; on_file: boolean }[]
}
export const fetchRounds = (caseId: string) =>
  get<{ rounds: CaseRound[]; submission_no: number }>(`/api/v2/cases/${encodeURIComponent(caseId)}/rounds`).then(r => r.rounds)

export function addDocuments(caseId: string, files: File[]) {
  const form = new FormData()
  files.forEach(f => form.append('files', f))
  return postForm<CaseFull>(`/api/v2/cases/${encodeURIComponent(caseId)}/documents`, form)
}

/** Change the case type: a department while the case is on its side; the AG or the administrator
 *  at any point, with a remark (audited). The AI's own reading is never overwritten. */
export const setCaseType = (caseId: string, body: { case_type: string; variant?: string; remark?: string }) =>
  post<CaseFull>(`/api/v2/cases/${encodeURIComponent(caseId)}/case-type`, body)

export interface CaseTypeColumn { id: string; label: string; documents: { id: string; requirement: string }[] }
export interface CaseTypeInfo {
  id: string; label: string; family: string; hint: string; prescribed_form: string
  variants: CaseTypeColumn[]
  /** What every column of the type demands: the list to show before the claimant is known. */
  documents: { id: string; requirement: string }[]
}
export const fetchCaseTypes = () => get<{ case_types: CaseTypeInfo[] }>('/api/v2/case-types').then(r => r.case_types)

export const runCheck = (caseId: string) =>
  post<{ run_id: string; resumed: boolean; documents: number }>(`/api/v2/cases/${encodeURIComponent(caseId)}/check`)

const PATH: Record<Exclude<CaseAction, 'ADD_DOCS' | 'RUN_CHECK'>, string> = {
  FORWARD: 'forward', TAKE_UP: 'take-up', APPROVE: 'approve', REJECT: 'reject', RETURN: 'return',
  REQUEST_DOCS: 'request-docs', OVERRIDE: 'override',
}

/** One thing the AG asks the department for: a checklist item, or a document and pages in words. */
export interface RequestItem { id?: string; requirement?: string; status?: string; label?: string; pages?: number[]; note?: string; kind?: 'CHECKLIST' | 'DOCUMENT' }

export const act = (caseId: string, action: keyof typeof PATH, body: { remark?: string; reason?: string; to_status?: CaseStatus; items?: RequestItem[] }) =>
  post<{ event: CaseEvent; case: CaseFull }>(`/api/v2/cases/${encodeURIComponent(caseId)}/${PATH[action]}`, body)

export const departments = () => get<Department[]>('/api/v2/departments')

/** What the GP Fund module holds for a case (AG only): the reading job, its case, the frame's address. */
export interface GpfState {
  status: CaseStatus
  gpf_case_id: string | null
  module_up: boolean
  officer: string
  job: { state: string; stage?: string; done?: number; total?: number; page?: number; artefact?: string; message?: string; elapsed?: number; detail?: string } | null
  case: { id?: string; version?: number; position?: Record<string, number>; caseDisp?: string | null; meta?: Record<string, unknown>; counts?: Record<string, number>; error?: string } | null
  embed_url?: string
  view?: GpfView
}
export const gpfState = (caseId: string) => get<GpfState>(`/api/v2/cases/${encodeURIComponent(caseId)}/gpf`)

/** The GP Fund module's own view of its case (GP/backend/gpf/service.py view), 30 Sep 2026. */
export interface GpfEvidence { page: number; label?: string }
export interface GpfItem {
  id: string; code: string; ref?: string; title: string; doc?: string; status: 'hard' | 'adv' | 'conf' | 'sap' | 'ok'
  finding?: string; remedy?: string; evidence?: GpfEvidence[]; group?: string
  cure?: { kind: 'verify' | 'doc' | 'qr' | 'sap'; vid?: string; qid?: string } | null
  disposition?: { action: string; ground?: string; authority?: string; by?: string; at?: string } | null
  verified?: { ok: boolean; note?: string; by?: string; at?: string } | null
}
export interface GpfView {
  id: string; version: number; issued: boolean; returns: number; caseDisp: string | null; caseNote?: string
  officer: { id: string; name: string; desig: string }
  meta: { label?: string; kind?: string; personnelNo?: string; gazetted?: string; subject?: string; dept?: string }
  lists: { hard: GpfItem[]; adv: GpfItem[]; conf: GpfItem[]; sap: GpfItem[]; ok: GpfItem[] }
  position: { hard: number; adv: number; open: number; conf: number; sap: number; waived: number; mayAdvance: boolean }
  sap: { present?: boolean; source?: string; payslip?: Record<string, string | number | null> | null
         recalc?: { reportDate?: string; rows?: number; lastClosing?: number } | null }
  doa: { status?: string; version?: string }
  /** The GP Fund balance and advance balance as the pay slip prints them (rules_family.fund_position):
   *  extracted, never calculated. */
  balances?: {
    gpf: { value: number; source: 'payslip'; page?: number | null; month?: string | null } | null
    loan: { value: number; source: 'payslip'; page?: number | null; month?: string | null } | null
    reportClosing: { value: number; asOf?: string | null } | null
    payslip: boolean
  }
  dispositions: Record<string, { action: string; ground?: string; authority?: string; by?: string; at?: string }>
  disposalOptions: { action: string; allowed: boolean; reason: string }[]
  history: { v: number; at: string; by: string; desig?: string; reason: string }[]
}
const gpfPath = (caseId: string, rest: string) => `/api/v2/cases/${encodeURIComponent(caseId)}${rest}`
export const gpfAct = (caseId: string, action: 'verify' | 'dispositions' | 'dispose' | 'sap', body: Record<string, unknown>) =>
  post<{ case: GpfView; status: CaseStatus }>(gpfPath(caseId, `/gpf/${action}`), body)
export function gpfCure(caseId: string, resultId: string, file: File) {
  const form = new FormData()
  form.append('resultId', resultId); form.append('values', '{}'); form.append('file', file)
  return postForm<{ case: GpfView; status: CaseStatus }>(gpfPath(caseId, '/gpf-cure'), form)
}
export const gpfIssuePack = (caseId: string) => get<Record<string, unknown>>(gpfPath(caseId, '/gpf-issue-pack'))
export const gpfSapTemplate = (caseId: string) => get<{ template: string }>(gpfPath(caseId, '/gpf-sap-template'))
export const gpfPageUrl = (caseId: string, page: number) => gpfPath(caseId, `/gpf/pages/${page}`)

/** The document's address, without a token: open it with `openProtected`. */
export const documentUrl = (caseId: string, docId: string) =>
  `/api/v2/cases/${encodeURIComponent(caseId)}/documents/${encodeURIComponent(docId)}`

/** How each status reads, in plain words: the pill, whose desk it is on, and what happens next. */
export const STATUS_META: Record<CaseStatus, {
  label: string
  /** neutral grey · info blue (with the Accountant General) · low green · medium amber · high red. */
  pill: 'neutral' | 'info' | 'low' | 'medium' | 'high'
  side: 'department' | 'ag' | 'closed'
  /** One sentence for the person who filed it. */
  dept: string
  /** One sentence for the AG reviewer. */
  ag: string
  /** Where it sits on the progress bar: 0 filed · 1 with the AG · 2 Verification · 3 decided. */
  step: number
}> = {
  DRAFT: { label: 'Not yet submitted', pill: 'neutral', side: 'department', step: 0,
    dept: 'Attach the documents, then submit the case to the Accountant General.', ag: 'The department has not yet submitted this case.' },
  AI_CHECKING: { label: 'Verification in progress', pill: 'info', side: 'ag', step: 2,
    dept: 'The Office of the Accountant General is verifying the case.', ag: 'Verification takes 10 to 20 minutes. You may leave this page and return; the outcome brings the case to you, or returns it to the department for missing documents.' },
  AI_FAILED: { label: 'Verification incomplete', pill: 'medium', side: 'ag', step: 2,
    dept: 'The Office of the Accountant General is verifying the case.', ag: 'The verification did not complete. Verify the case again.' },
  AI_CHECKED: { label: 'Verified, not yet submitted', pill: 'neutral', side: 'department', step: 0,
    dept: 'Submit the case to the Accountant General.', ag: 'Verified by the department; not yet submitted.' },
  FORWARDED: { label: 'Submitted to Accountant General', pill: 'info', side: 'ag', step: 1,
    dept: 'Received by the Pension Wing, Office of the Accountant General; awaiting verification.', ag: 'Newly received. Verify the case with AI: it is returned for missing documents or brought to you for a decision.' },
  UNDER_REVIEW: { label: 'Under review at Accountant General', pill: 'info', side: 'ag', step: 2,
    dept: 'The Pension Wing is reviewing the case.', ag: 'Verified: the case awaits your decision. Clear each finding, then approve, return or reject the case with a remark. Nothing is approved automatically.' },
  APPROVED: { label: 'Approved', pill: 'low', side: 'closed', step: 3,
    dept: 'The Accountant General has approved the case. No further action is required.', ag: 'Approved. The decision is on record.' },
  REJECTED: { label: 'Rejected', pill: 'high', side: 'closed', step: 3,
    dept: 'The Accountant General has rejected the case. The reason is in the remarks.', ag: 'Rejected. The decision is on record.' },
  RETURNED: { label: 'Returned for correction', pill: 'medium', side: 'department', step: 3,
    dept: 'Attach the documents listed below, then resubmit the case to the Accountant General.', ag: 'Returned to the department for correction.' },
  DOCS_REQUESTED: { label: 'Additional documents requested', pill: 'medium', side: 'department', step: 3,
    dept: 'Attach the documents requested, then resubmit the case to the Accountant General.', ag: 'Awaiting additional documents from the department.' },
}

export const PROGRESS_STEPS = ['Documents filed', 'Accountant General', 'Verification', 'Decision']

export const ACTION_META: Record<CaseAction, { label: string; tone: 'primary' | 'gold' | 'danger' | 'plain'; needsRemark: 'always' | 'issues' | 'never'; prompt: string; done: string }> = {
  ADD_DOCS: { label: 'Attach documents', tone: 'plain', needsRemark: 'never', prompt: '', done: 'Documents attached to the case.' },
  RUN_CHECK: { label: 'Verify case with AI', tone: 'primary', needsRemark: 'never', prompt: '', done: 'Verification started. It takes 10 to 20 minutes; the outcome brings the case to you for a decision.' },
  FORWARD: { label: 'Submit to Accountant General', tone: 'gold', needsRemark: 'never',
             prompt: 'Your remarks accompany the case and are read by the Pension Wing: say what was corrected or attached.',
             done: 'Case submitted to the Office of the Accountant General.' },
  TAKE_UP: { label: 'Take up for review', tone: 'primary', needsRemark: 'never', prompt: '', done: 'Case taken up for review.' },
  APPROVE: { label: 'Approve', tone: 'primary', needsRemark: 'always',
             prompt: 'Your remarks are recorded with the decision and communicated to the department. Where findings are not cleared, or the case was not verified, state why approval is nonetheless in order (at least 15 characters).',
             done: 'Case approved and recorded.' },
  REJECT: { label: 'Reject', tone: 'danger', needsRemark: 'always', prompt: 'State the grounds for rejection. They are communicated to the department.', done: 'Case rejected and recorded.' },
  RETURN: { label: 'Return to department', tone: 'danger', needsRemark: 'always',
            prompt: 'State the corrections required. The department will correct and resubmit the case.', done: 'Case returned to the department.' },
  REQUEST_DOCS: { label: 'Request additional documents', tone: 'plain', needsRemark: 'always',
                  prompt: 'Name the documents required. The department will attach them and resubmit the case.', done: 'Request for documents recorded and communicated.' },
  OVERRIDE: { label: 'Override decision', tone: 'danger', needsRemark: 'always',
              prompt: "The Deputy Accountant General's override. The reason is entered in the audit log.", done: 'Decision overridden and entered in the audit log.' },
}

/** The one thing to do next on a case, for the big button. */
export function nextStep(c: { status: CaseStatus; allowed_actions: CaseAction[] }, role: string): { action: CaseAction | null; title: string; text: string } {
  // The register has no allowed_actions per row; there, assume the role's usual powers.
  const a = new Set<CaseAction>(c.allowed_actions.length ? c.allowed_actions
    : (role === 'AG_REVIEWER' || role === 'AG_DAG' ? ['RUN_CHECK', 'APPROVE', 'REJECT', 'RETURN', 'REQUEST_DOCS'] : role === 'ADMIN' ? [] : ['ADD_DOCS', 'FORWARD']))
  const m = STATUS_META[c.status]
  const dept = role === 'DEPT_OFFICER'
  if (dept) {
    if ((c.status === 'DRAFT' || c.status === 'AI_CHECKED') && a.has('FORWARD')) return { action: 'FORWARD', title: 'Not yet submitted', text: 'The documents are attached. Submit the case to the Accountant General, where it is verified with AI.' }
    if ((c.status === 'RETURNED' || c.status === 'DOCS_REQUESTED') && a.has('ADD_DOCS')) return { action: 'ADD_DOCS', title: m.label, text: m.dept }
    return { action: null, title: m.label, text: m.dept }
  }
  if (c.status === 'FORWARDED' && a.has('RUN_CHECK')) return { action: 'RUN_CHECK', title: 'Received: verify the case with AI', text: 'The verification reads every document. Missing documents send the case back to the department with the list; a clean case is approved; findings come to you to clear.' }
  if (c.status === 'AI_FAILED' && a.has('RUN_CHECK')) return { action: 'RUN_CHECK', title: m.label, text: m.ag }
  if (c.status === 'UNDER_REVIEW' && a.has('APPROVE')) return { action: null, title: 'Findings await your decision', text: m.ag }
  return { action: null, title: m.label, text: m.ag }
}

/* -- statistics for the dashboards (GET /api/v2/stats) ---------------------------------------- */

export interface Stats {
  scope: { role: string; department: string | null }
  total: number
  by_status: Record<CaseStatus, number>
  weeks: { week: string; filed: number; decided: number }[]
  by_department: { code: string; name: string; total: number; awaiting: number; approved: number; rejected?: number; sent_back: number }[]
  verdicts?: { FORWARD: number; RETURN_FOR_CORRECTION: number; HOLD: number; NONE: number }   // AG and admin only
  high_flags?: { '0': number; '1': number; '2': number; '3+': number }   // AG and admin only
  checks_total: number
  avg_verification_minutes: number | null
  avg_days_to_decision: number | null
  decided_total: number
  /** The office's filing-to-decision target, and how many decided cases met it (optional until the API restarts). */
  decision_target_days?: number
  decided_within_target?: number
  users_by_role?: Record<string, number>
  audit_by_day?: { day: string; n: number }[]
  /** Pending cases by days at their present stage (optional until the API restarts). */
  ageing?: { with_department: Ageing; with_ag: Ageing }
  /** Checklist items most often missing or defective on the latest verification of each case. */
  deficiencies?: { verified_cases: number; items: { id: string; requirement: string; missing: number; defective: number }[] }
}

export interface Ageing {
  buckets: { '0-3': number; '4-7': number; '8-14': number; '15+': number }
  total: number
  oldest_days: number
  oldest_case: string | null
}

export const fetchStats = (department?: string | null, product?: Product, pensionSection?: string | null) => {
  const p = new URLSearchParams()
  if (department) p.set('department', department)
  if (pensionSection) p.set('pension_section', pensionSection)
  if (product) p.set('product', product)
  const qs = p.toString()
  return get<Stats>('/api/v2/stats' + (qs ? `?${qs}` : ''))
}
