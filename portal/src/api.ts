/** Client for the pilot API. BUILD §4.
 *
 * Every figure the portal shows comes from here or from the case report this returns. The
 * portal computes nothing: §15 rule 1 says a rupee figure with anything but the rules engine
 * in its causal chain is a design error, and a TypeScript file quietly totalling a column
 * would be exactly that.
 */
import type { CaseReport } from './types'

export interface RunEvent {
  seq: number
  at: string
  stage: string
  message: string
  level?: 'warn' | 'error'
  state?: string
}

export interface Gpu {
  gpu_util_pct: number | null
  gpu_name: string | null
  mem_used_gb: number | null
  mem_total_gb: number | null
  at: string
}

export async function apiAvailable(): Promise<boolean> {
  try {
    const r = await fetch('/api/health', { signal: AbortSignal.timeout(3000) })
    return r.ok
  } catch {
    return false
  }
}

export type VariantFamily = {
  id: string
  label: string
  variants: { id: string; label: string; documents: number }[]
}

/** The AG office checklist columns, grouped by case family. */
export async function fetchVariants(): Promise<VariantFamily[]> {
  const r = await fetch('/api/variants')
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()).families
}

export async function startRun(
  file: File,
  variant?: string,
  annualPay?: Record<string, string>,
  commutationPercent?: string,
  role?: Role,
): Promise<{ run_id: string; resumed: boolean }> {
  const form = new FormData()
  form.append('file', file)
  // The pensioner's commutation election, up to the 25% the December 2024 amendment allows.
  // Left empty when no option is on the file -- which is not the same as electing zero, and
  // the engine treats it differently: the ceiling is shown, no lump sum is computed.
  if (commutationPercent && commutationPercent.trim()) {
    form.append('commutation_percent', commutationPercent.trim())
  }
  // Basic pay including personal pay as at 1 July, for each of the three years before
  // retirement. Rule 4.4(4) as amended needs an average of three; a bundle carries one
  // pay slip, so the officer reads these off the service book.
  if (annualPay && Object.keys(annualPay).length) {
    form.append('annual_pay', JSON.stringify(annualPay))
  }
  // Which column of the office checklist applies is the officer's call, not the model's:
  // a widow's case and a parent's case need different documents, and nothing on the pages
  // says which one this is.
  if (variant) form.append('variant', variant)
  // Who is submitting. Every state-changing call names a desk and the server checks it
  // against SOP §4 -- intake belongs to the department, the Facilitation Centre and the
  // Auditor -- so a submission that states no desk is refused, which is what "Submit a new
  // case" did until now. The role the header shows is the claim, exactly as it is on a
  // decision; nothing verifies it until Keycloak arrives (BUILD §11.1).
  const r = await fetch('/api/runs', {
    method: 'POST', body: form, headers: role ? { 'X-Desk': role } : {},
  })
  if (!r.ok) throw new Error(`upload failed: HTTP ${r.status} ${await r.text()}`)
  return r.json()
}

/** Subscribe to stage events. Returns an unsubscribe function. */
export function subscribe(
  runId: string,
  onEvent: (e: RunEvent) => void,
  onEnd: (state: string) => void,
): () => void {
  const src = new EventSource(`/api/runs/${runId}/events`)
  src.onmessage = ev => {
    const e: RunEvent = JSON.parse(ev.data)
    onEvent(e)
    if (e.stage === 'end') { src.close(); onEnd(e.state ?? 'done') }
  }
  src.onerror = () => { /* EventSource retries on its own; a closed run ends via 'end' */ }
  return () => src.close()
}

export async function fetchReport(runId: string): Promise<CaseReport> {
  const r = await fetch(`/api/runs/${runId}/report`)
  if (!r.ok) throw new Error(`report not ready (HTTP ${r.status})`)
  return r.json()
}

export async function fetchGpu(): Promise<Gpu | null> {
  try {
    const r = await fetch('/api/gpu', { signal: AbortSignal.timeout(4000) })
    return r.ok ? r.json() : null
  } catch { return null }
}

/** SOP §4: the two parties, and what each may do. */
export type Role = 'ADMIN_DEPARTMENT' | 'ACCOUNTS_OFFICE'

export type RoleInfo = { id: Role; label: string; permissions: string[] }

export async function fetchRoles(): Promise<RoleInfo[]> {
  const r = await fetch('/api/roles')
  if (!r.ok) return []
  return r.json()
}

/** One row of the case register. Read from disk, so it survives a restart. */
export type CaseRow = {
  run_id: string
  status: 'RUNNING' | 'FAILED' | 'AWAITING_REVIEW' | 'APPROVED' | 'RETURNED' | 'ON_HOLD'
  file: string
  pages: number | null
  claimant: string | null
  case_type: string | null
  case_variant: string | null
  checklist_result: string | null
  checklist_satisfied: number | null
  checklist_required: number | null
  flags: number
  blocking_flags: number
  recommended_verdict: string | null
  decision: string | null
  decided_by: string | null
  decided_role: string | null
  decided_at: string | null
  decisions: number
  started_at: string
  updated_at: number
  error: string | null
}

/** Every case the office has seen, newest first. SOP §4.2 monitoring. */
export async function fetchCases(): Promise<CaseRow[]> {
  const r = await fetch('/api/cases')
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export type DecisionEntry = {
  run_id: string
  action: string
  officer: string
  role?: string
  justification: string
  at: string
  overrides_recommendation: boolean
  override_grounds: string
  recommended_verdict: string | null
  blocking_flags: string[]
  checklist_result: string | null
  checklist_satisfied: number | null
  checklist_required: number | null
  case_variant: string | null
}

/** Record the officer's decision. The server enforces the override rule, not the UI. */
export async function postDecision(
  runId: string,
  body: { action: string; officer: string; role: Role; justification?: string },
): Promise<DecisionEntry> {
  const r = await fetch(`/api/runs/${runId}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const text = await r.text()
  if (!r.ok) {
    // 422 carries the reason the decision was refused, and the officer needs to read it.
    let detail = text
    try { detail = JSON.parse(text).detail ?? text } catch { /* plain text */ }
    throw new Error(detail)
  }
  return JSON.parse(text)
}

export async function fetchDecisions(runId: string): Promise<DecisionEntry[]> {
  const r = await fetch(`/api/runs/${runId}/decision`)
  if (!r.ok) return []
  return (await r.json()).history ?? []
}

async function postJson(url: string, body: unknown, role?: Role): Promise<unknown> {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(role ? { 'X-Desk': role } : {}) },
    body: JSON.stringify(body),
  })
  const text = await r.text()
  if (!r.ok) {
    let detail = text
    try { detail = JSON.parse(text).detail ?? text } catch { /* plain text */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return text ? JSON.parse(text) : null
}

/** The register's "×": take a case off the lists. Its files stay on disk. */
export const removeCase = (runId: string, role: Role, reason = '') =>
  postJson(`/api/runs/${encodeURIComponent(runId)}/remove`, { role, reason }, role)

/* ═══════ findings: disposition, and the gate it opens ═══════ */

export type Disposition = {
  run_id: string
  flag_id: string
  action: 'UPHOLD' | 'WAIVE' | 'HOLD'
  officer: string
  role: string
  ground: string
  at: string
  flag_severity?: string
  flag_title?: string
}

export type CalculationGate = {
  /** True when the pension may be computed: every finding cleared, nothing missing. */
  open: boolean
  flags_total: number
  flags_cleared: number
  open_flags: { id: string; severity: string; title: string; disposition: string | null }[]
  checklist_missing: number
  reason: string | null
}

export type Dispositions = {
  run_id: string
  current: Record<string, Disposition>
  history: Disposition[]
  gate: CalculationGate
}

export async function fetchDispositions(runId: string): Promise<Dispositions> {
  const r = await fetch(`/api/runs/${runId}/dispositions`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export async function postDisposition(
  runId: string,
  body: { flag_id: string; action: Disposition['action']; officer: string
          role: Role; ground?: string },
): Promise<Disposition & { gate: CalculationGate; current: Record<string, Disposition> }> {
  const r = await fetch(`/api/runs/${runId}/dispositions`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  const text = await r.text()
  if (!r.ok) {
    let detail = text
    try { detail = JSON.parse(text).detail ?? text } catch { /* plain text */ }
    throw new Error(detail)
  }
  return JSON.parse(text)
}

/** An officer's action on one checklist item, or on pages the checklist does not ask for. */
export async function postChecklistAction(
  runId: string,
  body: { action: 'IDENTIFY' | 'NAME' | 'WAIVE' | 'CLEAR'; officer: string; role: Role
          item_id?: string; pages?: number[]; document_name?: string; ground?: string
          name_id?: string },
): Promise<{ report: CaseReport; gate: CalculationGate }> {
  const r = await fetch(`/api/runs/${runId}/checklist-actions`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  const text = await r.text()
  if (!r.ok) {
    let detail = text
    try { detail = JSON.parse(text).detail ?? text } catch { /* plain text */ }
    throw new Error(detail)
  }
  return JSON.parse(text)
}

/** The rendered image of one page, so a finding can be checked against the paper. */
export const pageImageUrl = (runId: string, page: number) =>
  `/api/runs/${runId}/pages/${page}`

/** A specimen signature from the register (rules/specimens), and one cut from a case's form. */
export const specimenImageUrl = (specimenId: string, name: string) =>
  `/api/specimens/${encodeURIComponent(specimenId)}/images/${encodeURIComponent(name)}`
export const signatureImageUrl = (runId: string, name: string) =>
  `/api/runs/${runId}/signatures/${encodeURIComponent(name)}`
