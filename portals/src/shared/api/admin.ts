/** Administration: users and the audit log (/api/v2/admin). */
import { get, post } from './client'

export interface AdminUser {
  id: string
  username: string
  display_name: string
  role: 'DEPT_OFFICER' | 'AG_REVIEWER' | 'ADMIN'
  department_code: string | null
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

export const listUsers = () => get<AdminUser[]>('/api/v2/admin/users')
export const createUser = (body: { username: string; display_name: string; role: string; department_code?: string; password: string }) =>
  post<AdminUser>('/api/v2/admin/users', body)
export const disableUser = (id: string, reason: string) => post<AdminUser>(`/api/v2/admin/users/${id}/disable`, { reason })
export const enableUser = (id: string) => post<AdminUser>(`/api/v2/admin/users/${id}/enable`)
export const resetPassword = (id: string, password: string) => post<{ ok: boolean }>(`/api/v2/admin/users/${id}/reset-password`, { password })
export const auditLog = (q: { since?: string; actor?: string } = {}) => {
  const p = new URLSearchParams()
  if (q.since) p.set('since', q.since)
  if (q.actor) p.set('actor', q.actor)
  const qs = p.toString()
  return get<AuditEntry[]>('/api/v2/admin/audit-log' + (qs ? `?${qs}` : ''))
}
export const overview = () => get<{ cases: number; by_status: Record<string, number>; users: number; departments: number; audit_entries: number }>('/api/v2/admin/overview')
