/** Administration: users and the audit log (/api/v2/admin). */
import { get, post } from './client'

export interface AdminUser {
  id: string
  username: string
  display_name: string
  role: 'DEPT_OFFICER' | 'AG_SENIOR_AUDITOR' | 'AG_ASSISTANT_AO' | 'AG_AO' | 'AG_DAG' | 'ADMIN' | 'AG_REVIEWER'
  department_code: string | null
  /** The pension wing of a tier officer (C3); null for everyone else. */
  pension_wing: string | null
  active: boolean
  token_version: number
  created_at: string
  updated_at: string
  portal: string | null
}

export interface AuditEntry {
  id: string
  at: string
  actor_id: string | null
  actor_name: string | null
  actor_role: string | null
  action: string
  entity_type: string
  entity_id: string
  before: unknown
  after: unknown
  reason: string
  ip: string | null
}

export const listUsers = (q: { role?: string; pension_wing?: string } = {}) => {
  const p = new URLSearchParams()
  if (q.role) p.set('role', q.role)
  if (q.pension_wing) p.set('pension_wing', q.pension_wing)
  const qs = p.toString()
  return get<AdminUser[]>('/api/v2/admin/users' + (qs ? `?${qs}` : ''))
}
export const createUser = (body: { username: string; display_name: string; role: string; department_code?: string; pension_wing?: string; password: string }) =>
  post<AdminUser>('/api/v2/admin/users', body)
/** Give an AG account its tier and wing (C4): how a legacy reviewer becomes a tier officer. */
export const setUserRole = (id: string, body: { role: string; pension_wing?: string; reason: string }) =>
  post<AdminUser>(`/api/v2/admin/users/${id}/role`, body)
export interface WingCoverage {
  wings: { wing: string; tiers: Record<string, number>; gaps: string[] }[]
  tier_labels: Record<string, string>
  gaps: { wing: string; tier: string }[]
  deputy_ag: number
}
export const wingCoverage = () => get<WingCoverage>('/api/v2/admin/wing-coverage')
/** Rename an account. The word the officer signs in with changes and nothing else: every case
 *  event, audit entry and signature names the account by its id. Ends the account's sessions. */
export const setUsername = (id: string, username: string, reason: string) =>
  post<AdminUser>(`/api/v2/admin/users/${id}/username`, { username, reason })
export const disableUser = (id: string, reason: string) => post<AdminUser>(`/api/v2/admin/users/${id}/disable`, { reason })
export const enableUser = (id: string) => post<AdminUser>(`/api/v2/admin/users/${id}/enable`)
export const resetPassword = (id: string, password: string, reason: string) => post<{ ok: boolean }>(`/api/v2/admin/users/${id}/reset-password`, { password, reason })
export const auditLog = (q: { since?: string; actor?: string } = {}) => {
  const p = new URLSearchParams()
  if (q.since) p.set('since', q.since)
  if (q.actor) p.set('actor', q.actor)
  const qs = p.toString()
  return get<AuditEntry[]>('/api/v2/admin/audit-log' + (qs ? `?${qs}` : ''))
}
export const overview = () => get<{ cases: number; by_status: Record<string, number>; users: number; departments: number; audit_entries: number }>('/api/v2/admin/overview')
