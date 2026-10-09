/** Signing authorities and their specimen signatures: the master store both products read
 *  (/api/v2/signatories; scope change C1, 9 Oct 2026). Administrators maintain it; the AG's side
 *  sees the specimens where a signature is checked. A DDO never receives a specimen. */
import { get, post, upload } from './client'

export type ProductScope = 'PENSION' | 'GPF' | 'BOTH'

export interface SpecimenRef { id: string; name: string; uploaded_at: string; uploaded_by: string | null; note: string | null }

export interface Authority {
  id: string
  product_scope: ProductScope
  department_code: string | null
  department_name: string
  department_aliases: string[]
  post: string
  post_aliases: string[]
  officer_name: string | null
  scope: string | null
  effective_from: string
  effective_to: string | null
  letter_no: string | null
  letter_date: string | null
  has_letter: boolean
  provisional: boolean
  source: 'PENSION_REGISTER' | 'GPF_PROVISIONAL' | 'ADMIN'
  may_sign_for: boolean
  stamp_text: string | null
  created_at: string
  updated_at: string
  closed_at: string | null
  closed: boolean
  specimens: SpecimenRef[]
}

export interface AuthorityInput {
  department_name: string
  department_code?: string | null
  department_aliases?: string[]
  post: string
  post_aliases?: string[]
  officer_name?: string
  scope?: string
  effective_from: string
  effective_to?: string | null
  letter_no?: string
  letter_date?: string | null
  product_scope: ProductScope
  may_sign_for?: boolean
  stamp_text?: string
}

export const listAuthorities = (q: { department?: string; post?: string; product?: ProductScope; includeClosed?: boolean } = {}) => {
  const p = new URLSearchParams()
  if (q.department) p.set('department', q.department)
  if (q.post) p.set('post', q.post)
  if (q.product) p.set('product', q.product)
  if (q.includeClosed === false) p.set('include_closed', 'false')
  const qs = p.toString()
  return get<{ authorities: Authority[] }>('/api/v2/signatories' + (qs ? `?${qs}` : '')).then(r => r.authorities)
}
export const createAuthority = (body: AuthorityInput) => post<Authority>('/api/v2/signatories', body)
export const updateAuthority = (id: string, body: Partial<AuthorityInput> & { reason?: string }) =>
  post<Authority>(`/api/v2/signatories/${encodeURIComponent(id)}`, body)
export const closeAuthority = (id: string, effectiveTo: string | null, reason: string) =>
  post<Authority>(`/api/v2/signatories/${encodeURIComponent(id)}/close`, { effective_to: effectiveTo, reason })
export const finalizeGpfRegister = () => post<{ ok: boolean; rows_made_final: number }>('/api/v2/signatories/gpf-register/finalize')
export const addSpecimen = (id: string, file: File, note = '') => {
  const fd = new FormData()
  fd.append('file', file, file.name)
  fd.append('note', note)
  return upload<Authority>(`/api/v2/signatories/${encodeURIComponent(id)}/specimens`, fd)
}
export const addLetter = (id: string, file: File) => {
  const fd = new FormData()
  fd.append('file', file, file.name)
  return upload<Authority>(`/api/v2/signatories/${encodeURIComponent(id)}/letter`, fd)
}

/** A list filter in one place, so the screen and its test agree: the department box matches the
 *  name, code or any alias; the post box the post or any alias; closed entries hidden on request. */
export function filterAuthorities(rows: Authority[], q: { department?: string; post?: string; showClosed?: boolean }): Authority[] {
  const dept = (q.department ?? '').trim().toLowerCase()
  const post = (q.post ?? '').trim().toLowerCase()
  return rows.filter(a => (q.showClosed || !a.closed)
    && (!dept || [a.department_name, a.department_code ?? '', ...a.department_aliases].some(v => v.toLowerCase().includes(dept)))
    && (!post || [a.post, ...a.post_aliases].some(v => v.toLowerCase().includes(post))))
}

/** "In force from 09 Sep 2025", "… to 31 Mar 2026", "Closed 9 Oct 2026". */
export function inForceWords(a: Pick<Authority, 'effective_from' | 'effective_to' | 'closed_at'>): string {
  const d = (iso: string) => {
    const t = new Date(iso + (iso.length === 10 ? 'T00:00:00' : ''))
    return isNaN(t.getTime()) ? iso : t.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  }
  if (a.closed_at) return `Closed; in force ${d(a.effective_from)} to ${d(a.effective_to ?? a.closed_at)}`
  return a.effective_to ? `In force ${d(a.effective_from)} to ${d(a.effective_to)}` : `In force from ${d(a.effective_from)}`
}
