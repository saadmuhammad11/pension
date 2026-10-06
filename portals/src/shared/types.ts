/** The case-report contract the pipeline emits and the portal renders.
 *
 * Mirrors BRAIN §6 (extraction schema) and the deterministic layer's own `to_dict()`
 * outputs, so the frontend never reshapes a figure -- it displays what the engine computed.
 * BUILD §15 rule 1: if a rupee figure has anything but the rules engine in its causal chain,
 * the design is wrong, and that includes a TypeScript file quietly recomputing a total.
 */

export interface Step {
  rule_id: string
  description: string
  computation_shown: string
  amount: number | null
  unit: string
  exact_before_rounding?: string
  rounding?: string
  note?: string
}

export interface Reading {
  label: string
  amount: number
  computation_shown: string
  basis: string
}

/** An unresolved rule. Carries every reading and no single figure -- BLOCKING-06. */
export interface Ambiguity {
  rule_id: string
  blocking_id: string
  question: string
  difference: string
  resolve_with: string
  readings: Reading[]
}

export interface Determination {
  case_ref: string
  rule_pack_id: string
  effective_date: string
  computed_at: string
  provisional: boolean
  unverified_rules_engaged: string[]
  steps: Step[]
  ambiguities: Ambiguity[]
  caveats: string[]
  inputs: Record<string, string | number>
}

export type Severity = 'HIGH' | 'MEDIUM' | 'LOW'

export interface Flag {
  id: string
  severity: Severity
  class: string
  title: string
  finding: string
  evidence: { asserted: PageRef[]; contradicted_by: PageRef[] }
  affects_determination: boolean
  blocks_ppo: boolean
  required_action: string
  owner: string
  /** A sanction signature and the specimen it is compared with (rules.flags.check_psa_specimen). */
  specimen?: SpecimenSideBySide
  /** One plain sentence, at most 15 words (rules.flag_curation, 30 Sep 2026). */
  summary?: string
}

export interface PageRef { page: number; doc: string }

export interface ChecklistItem {
  id: string
  requirement: string
  status: 'PRESENT' | 'MISSING' | 'DEFECTIVE' | 'NOT_APPLICABLE' | 'NOT_REQUIRED' | 'FOUND_NOT_REQUIRED' | 'WAIVED'
  /** The title the page itself prints, where the paper was accepted under other wording. */
  found_as?: string
  located?: number[]
  reason?: string
  /** What the engine read, where an officer has since settled the item (api.checklist_actions). */
  engine_status?: ChecklistItem['status']
  officer_action?: {
    action: 'IDENTIFY' | 'NAME' | 'WAIVE'
    officer: string; role: string; at: string; ground: string
    pages: number[]; document_name: string
    /** Set where the item was satisfied by naming an unrecognised page. */
    name_id?: string
  }
}

/** Pages an officer has named as a document the checklist does not ask for. */
export interface NamedDocument {
  name_id: string
  name: string
  pages: number[]
  item_id?: string | null
  officer: string
  at: string
}

export interface Checklist {
  checklist_id: string
  items: ChecklistItem[]
  result: 'COMPLETE' | 'INCOMPLETE'
  required: number
  present: number
  missing: number
  defective: number
  not_applicable: number
  satisfied: number
  waived?: number
  result_line: string
}

export interface PayComponent {
  printed_label: string
  component: string
  amount: number
  reckonable: boolean
  page: number | null
}

export interface Emoluments {
  reckonable_total: number
  excluded_total: number
  printed_total: number | null
  reconciled: boolean
  components: PayComponent[]
}

export interface CaseType {
  case_type: string | null
  case_type_confidence: number
  case_type_evidence: string
  prescribed_form: string | null
  prescribed_form_present: boolean
  alternatives: string[]
  contradictions: string[]
  route: string
}

export interface Notification {
  recipient_class: 'DEPARTMENT' | 'CLAIMANT'
  notification_class: string
  channel: string
  subject: string
  body_en: string
  body_ur: string | null
  bilingual: boolean
  requires_recipient_action: boolean
}

export interface Recommendation {
  verdict: 'FORWARD' | 'RETURN_FOR_CORRECTION' | 'HOLD' | 'ROUTE_MANUAL'
  blocking_flags: string[]
  rationale: string
  human_decision_required: boolean
}

export interface IdentifiedPage {
  page: number
  document_type: string
  confidence: number
  evidence: string
  header_title?: string
  quality?: number
  needs_human: boolean
}

export interface CaseReport {
  case_ref: string
  diary_no: string | null
  forwarding_department: string | null
  claimant_name: string | null
  source: { file: string; sha256: string; source_pages: number }
  case_type: CaseType
  documents: { type: string; pages: number[]; present: boolean }[]
  pages: IdentifiedPage[]
  emoluments: Emoluments | null
  /** Pages in the bundle that produced no document. A "not found" line can only be trusted
   *  when this is empty -- the missing paper may simply be on a page we could not read. */
  pages_unaccounted: number[]
  named_documents?: NamedDocument[]
  /** Pages the reader could not identify or could not read -- the only ones an officer may name. */
  nameable_pages?: number[]
  case_variant: string | null
  case_variant_source: string | null
  case_variant_evidence: string | null
  checklist: Checklist | null
  checklist_gap: string | null
  flags: Flag[]
  /** What stage 6 read, per document, with the page it was read on. */
  extracted?: {
    assertions: { field: string; value: string; person?: string | null; role?: string | null
                  page: number; document: string }[]
    annex_a_family: { name: string; relation: string; marital_status: string; page: number }[]
    frc_family: { name: string; relation: string; marital_status: string; page: number }[]
    frc_applicant: { name: string; relation_with_hof: string; cnic?: string | null
                     page: number } | null
    document_dates: { value: string; confidence: number; page: number; document: string }[]
    names: { value: string; confidence: number; page: number; document: string }[]
    issuing_offices: { value: string; confidence: number; page: number; document: string }[]
    recoveries: unknown[]
    unreadable: { page: number; document: string; reason: string }[]
  } | null
  determination: Determination | null
  /** Why no pension was computed. A refusal the officer has to read: the engine declines
   *  rather than guessing, and "Not computed." on its own tells them nothing. */
  self_pension_error: string | null
  recommendation: Recommendation | null
  notifications: Notification[]
  provenance: Record<string, string | number | null>
}

/** The department's specimen for the post that signed, and the signature cut from the form. */
export interface SpecimenSideBySide {
  id: string
  officer: string
  post: string
  department: string
  scope: string
  cite: string
  images: string[]
  page: number | null
  signature_image: string | null
}
