/** A stand-in for the whole backend, in memory: every route the screens call, answered from
 *  hardcoded data (one real case, its real report and page images), so the real components run
 *  unchanged with no server. Installed by replacing window.fetch and window.EventSource. */
import portals from './data/portals.json'
import report from './data/report.json'
import pagesData from './data/pages.json'
import { buildEvents, type DemoEvent } from './events'

type Role = 'DEPT_OFFICER' | 'AG_REVIEWER' | 'ADMIN'
interface User { id: string; username: string; display_name: string; role: Role; department_code: string | null; department_name: string | null; active: boolean; portal: string | null }
interface Ev { id: string; seq: number; action: string; from_status: string | null; to_status: string; actor_id: string | null; actor_name: string | null; actor_role: string | null; actor_department: string | null; remark: string; payload: Record<string, unknown>; run_id: string | null; at: string }
interface Run { id: string; case_id: string; run_id: string; submission_no: number; started_by: string; started_at: string; finished_at: string | null; state: 'queued' | 'running' | 'done' | 'failed'; verdict: string | null; high_flags: number | null; blocking_flags: string[]; checklist_result: string | null; error: string | null; auto_forward: number }
interface Doc { id: string; submission_no: number; seq: number; filename: string; sha256: string; bytes: number; uploaded_by: string; uploaded_at: string }
interface Case { id: string; case_no: string; department_code: string; department_name: string; created_via: 'DEPARTMENT'; created_by: string; status: string; claimant_name: string | null; variant: string | null; intake: Record<string, unknown>; submission_no: number; current_run_id: string | null; created_at: string; updated_at: string; documents: Doc[]; runs: Run[]; events: Ev[]; officer_remark: string | null }

const DEPTS = (portals as { departments: { code: string; name: string; slug: string }[] }).departments
const DEPT_NAME: Record<string, string> = Object.fromEntries(DEPTS.map(d => [d.code, d.name]))

const STATUS_LABEL: Record<string, string> = {
  DRAFT: 'Awaiting AI verification', AI_CHECKING: 'AI verification in progress', AI_FAILED: 'AI verification incomplete',
  AI_CHECKED: 'Verified, ready for submission', FORWARDED: 'Submitted to Accountant General', UNDER_REVIEW: 'Under review at Accountant General',
  APPROVED: 'Approved', REJECTED: 'Rejected', RETURNED: 'Returned for correction', DOCS_REQUESTED: 'Additional documents requested',
}

export const DEMO_RUN_ID = '94fe91578dec'
export const DEMO_DEPT = 'PUNJAB_POLICE'

let clock = Date.now()
const now = () => new Date(clock).toISOString().slice(0, 19)
const tick = (ms = 1000) => { clock += ms; return now() }
let ids = 0
const newId = () => (Date.now().toString(16) + (ids++).toString(16).padStart(4, '0')).padEnd(32, '0').slice(0, 32)

function makeUsers(): User[] {
  const u: User[] = [
    { id: 'u-admin', username: 'admin', display_name: 'System Administrator', role: 'ADMIN', department_code: null, department_name: null, active: true, portal: 'ag' },
    { id: 'u-rev', username: 'syed.haider', display_name: 'Syed Haider (AG Punjab, Pension Wing)', role: 'AG_REVIEWER', department_code: null, department_name: null, active: true, portal: 'ag' },
  ]
  for (const d of DEPTS) u.push({ id: 'u-' + d.slug, username: d.slug, display_name: `${d.name} — DDO`, role: 'DEPT_OFFICER', department_code: d.code, department_name: d.name, active: true, portal: 'ag' })
  return u
}

const capabilities = (u: User) => {
  const dept = u.role === 'DEPT_OFFICER' || u.role === 'ADMIN', ag = u.role === 'AG_REVIEWER' || u.role === 'ADMIN'
  return { create_case: dept, add_documents: dept, run_check: dept, forward: dept, pick_department: u.role === 'ADMIN', intake_choices: ag, correct_case_type: ag,
           review: ag, dispose: ag, override: u.role === 'ADMIN', manage_users: u.role === 'ADMIN', audit_log: u.role === 'ADMIN', all_departments: ag }
}

/** The register before the demo starts: a handful of cases across departments, some decided. */
function seedCases(users: User[]): Case[] {
  const day = 86_400_000
  const mk = (n: number, dept: string, status: string, claimant: string, daysAgo: number, verdict: string | null, high: number, decidedRemark?: string): Case => {
    const at = new Date(Date.now() - daysAgo * day).toISOString().slice(0, 19)
    const officer = users.find(u => u.department_code === dept)!
    const runId = `r${n.toString(16).padStart(11, '0')}`
    const hasRun = status !== 'DRAFT'
    const events: Ev[] = [{ id: newId(), seq: 1, action: 'CREATE', from_status: null, to_status: 'DRAFT', actor_id: officer.id, actor_name: officer.display_name, actor_role: 'DEPT_OFFICER', actor_department: dept, remark: '', payload: {}, run_id: null, at }]
    if (hasRun) {
      events.push({ id: newId(), seq: 2, action: 'RUN_CHECK', from_status: 'DRAFT', to_status: 'AI_CHECKING', actor_id: officer.id, actor_name: officer.display_name, actor_role: 'DEPT_OFFICER', actor_department: dept, remark: '', payload: {}, run_id: runId, at })
      events.push({ id: newId(), seq: 3, action: 'CHECK_DONE', from_status: 'AI_CHECKING', to_status: 'AI_CHECKED', actor_id: null, actor_name: 'AI verification', actor_role: 'SYSTEM', actor_department: null, remark: high ? `AI check complete: ${high} HIGH finding(s).` : 'AI check complete: no issues found.', payload: {}, run_id: runId, at })
    }
    if (['FORWARDED', 'UNDER_REVIEW', 'APPROVED', 'REJECTED', 'RETURNED'].includes(status)) {
      events.push({ id: newId(), seq: 4, action: 'FORWARD', from_status: 'AI_CHECKED', to_status: 'FORWARDED', actor_id: officer.id, actor_name: officer.display_name, actor_role: 'DEPT_OFFICER', actor_department: dept, remark: 'Submitted for sanction.', payload: {}, run_id: runId, at })
    }
    if (['UNDER_REVIEW', 'APPROVED', 'REJECTED', 'RETURNED'].includes(status)) {
      events.push({ id: newId(), seq: 5, action: 'TAKE_UP', from_status: 'FORWARDED', to_status: 'UNDER_REVIEW', actor_id: 'u-rev', actor_name: 'Syed Haider (AG Punjab, Pension Wing)', actor_role: 'AG_REVIEWER', actor_department: null, remark: '', payload: {}, run_id: null, at })
    }
    if (['APPROVED', 'REJECTED', 'RETURNED'].includes(status)) {
      events.push({ id: newId(), seq: 6, action: status === 'APPROVED' ? 'APPROVE' : status === 'REJECTED' ? 'REJECT' : 'RETURN', from_status: 'UNDER_REVIEW', to_status: status, actor_id: 'u-rev', actor_name: 'Syed Haider (AG Punjab, Pension Wing)', actor_role: 'AG_REVIEWER', actor_department: null, remark: decidedRemark ?? '', payload: {}, run_id: null, at })
    }
    const run: Run | null = hasRun ? { id: newId(), case_id: '', run_id: runId, submission_no: 1, started_by: officer.id, started_at: at, finished_at: at, state: 'done', verdict, high_flags: high, blocking_flags: [], checklist_result: high ? 'INCOMPLETE' : 'COMPLETE', error: null, auto_forward: 0 } : null
    const c: Case = { id: newId(), case_no: `PC-2026-${String(n).padStart(6, '0')}`, department_code: dept, department_name: DEPT_NAME[dept], created_via: 'DEPARTMENT', created_by: officer.id, status, claimant_name: claimant, variant: null, intake: {}, submission_no: 1, current_run_id: runId, created_at: at, updated_at: at,
      documents: [{ id: newId(), submission_no: 1, seq: 1, filename: 'pension-case.pdf', sha256: runId.repeat(5).slice(0, 64), bytes: 4_200_000 + n * 1000, uploaded_by: officer.id, uploaded_at: at }],
      runs: run ? [run] : [], events, officer_remark: null }
    if (run) run.case_id = c.id
    return c
  }
  return [
    mk(101, 'SCHOOL_EDUCATION', 'APPROVED', 'Mst. Shabnam Akhtar', 21, 'FORWARD', 0, 'Sanctioned; all documents in order.'),
    mk(102, 'SCHOOL_EDUCATION', 'RETURNED', 'Muhammad Saleem', 14, 'RETURN_FOR_CORRECTION', 1, 'NADRA family certificate older than six months; obtain a fresh one and resubmit.'),
    mk(103, 'AGRICULTURE', 'APPROVED', 'Rana Muhammad Yaqoob', 19, 'FORWARD', 0, 'Approved.'),
    mk(104, 'AGRICULTURE', 'UNDER_REVIEW', 'Mst. Shamim Bibi', 3, 'FORWARD', 0),
    mk(105, 'IRRIGATION', 'FORWARDED', 'Abdul Ghafoor', 2, 'FORWARD', 0),
    mk(106, 'MAYO_HOSPITAL', 'APPROVED', 'Dr. Saima Rasheed', 9, 'FORWARD', 0, 'Approved with the service record as filed.'),
    mk(107, 'BOARD_OF_REVENUE', 'REJECTED', 'Khalid Mehmood', 11, 'RETURN_FOR_CORRECTION', 2, 'Qualifying service short of the minimum; no entitlement.'),
    mk(108, 'PUNJAB_POLICE', 'APPROVED', 'Mst. Khalida Bibi', 30, 'FORWARD', 0, 'Approved.'),
    mk(109, 'PUNJAB_POLICE', 'AI_CHECKED', 'Constable Sajjad Ali', 1, 'FORWARD', 0),
    mk(110, 'HIGHER_EDUCATION', 'DRAFT', 'Prof. Kamal Ahmad', 0, null, 0),
    mk(111, 'LIVESTOCK_DAIRY', 'APPROVED', 'Muhammad Ramzan', 25, 'FORWARD', 0, 'Approved.'),
    mk(112, 'PUNJAB_POLICE', 'RETURNED', 'Head Constable Naveed', 6, 'RETURN_FOR_CORRECTION', 1, 'Attach the bank option form verified by the bank.'),
  ]
}

export interface DemoState {
  users: User[]; cases: Case[]; tokens: Record<string, string>; audit: Record<string, unknown>[]
  liveRun: { caseId: string; events: DemoEvent[]; index: number; finished: boolean } | null
  speed: number
}

export let state: DemoState = fresh()

export function fresh(): DemoState {
  ids = 0; clock = Date.now()
  const users = makeUsers()
  const cases = seedCases(users)
  const audit = [
    { id: newId(), at: new Date(Date.now() - 12 * 86_400_000).toISOString().slice(0, 19), actor_id: 'u-admin', actor_name: 'System Administrator', actor_role: 'ADMIN', action: 'CASE_OVERRIDE', entity_type: 'case', entity_id: cases[6].id, before: { status: 'APPROVED' }, after: { status: 'REJECTED' }, reason: 'Approval recorded on the wrong file; corrected on the DAO\'s note.', ip: '10.170.1.20' },
    { id: newId(), at: new Date(Date.now() - 5 * 86_400_000).toISOString().slice(0, 19), actor_id: 'u-admin', actor_name: 'System Administrator', actor_role: 'ADMIN', action: 'USER_CREATE', entity_type: 'user', entity_id: 'u-higher-education', before: null, after: { username: 'higher-education', role: 'DEPT_OFFICER', department_code: 'HIGHER_EDUCATION' }, reason: '', ip: '10.170.1.20' },
    { id: newId(), at: new Date(Date.now() - 2 * 86_400_000).toISOString().slice(0, 19), actor_id: 'u-admin', actor_name: 'System Administrator', actor_role: 'ADMIN', action: 'USER_RESET_PASSWORD', entity_type: 'user', entity_id: 'u-irrigation', before: null, after: null, reason: 'Officer transferred; new incumbent.', ip: '10.170.1.20' },
  ]
  return { users, cases, tokens: {}, audit, liveRun: null, speed: 1 }
}

export function reset(): void { state = fresh() }

// -- helpers -----------------------------------------------------------------------------------

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } })
const fail = (status: number, detail: string) => json({ detail }, status)

function userFor(req: Request, url: URL): User | null {
  const h = req.headers.get('authorization') || ''
  const t = h.startsWith('Bearer ') ? h.slice(7) : url.searchParams.get('token')
  if (!t) return null
  const username = state.tokens[t]
  return state.users.find(u => u.username === username) ?? null
}

const AG_HOLDS = ['FORWARDED', 'UNDER_REVIEW']
function allowed(c: Case, u: User): string[] {
  const out: string[] = []
  const deptSide = u.role === 'DEPT_OFFICER' || u.role === 'ADMIN'
  const agSide = u.role === 'AG_REVIEWER' || u.role === 'ADMIN'
  if (deptSide) {
    if (['DRAFT', 'AI_FAILED', 'AI_CHECKED', 'RETURNED', 'DOCS_REQUESTED'].includes(c.status)) out.push('ADD_DOCS')
    if (['DRAFT', 'AI_FAILED', 'AI_CHECKED'].includes(c.status)) out.push('RUN_CHECK')
    if (c.status === 'AI_CHECKED') out.push('FORWARD')
  }
  if (agSide) {
    if (c.status === 'FORWARDED') out.push('TAKE_UP')
    if (AG_HOLDS.includes(c.status)) out.push('APPROVE', 'REJECT', 'RETURN', 'REQUEST_DOCS')
  }
  if (u.role === 'ADMIN') out.push('OVERRIDE')
  return out
}

const latestRun = (c: Case) => c.runs.length ? c.runs[c.runs.length - 1] : null

function openIssues(c: Case) {
  const r = latestRun(c)
  if (!r || r.state !== 'done') return null
  const rep = report as { flags: { id: string; title: string; class: string; severity: string }[]; checklist: { items: { id: string; requirement: string; status: string }[] } }
  const high = c.current_run_id === DEMO_RUN_ID ? rep.flags.filter(f => f.severity === 'HIGH').map(f => ({ id: f.id, title: f.title, class: f.class })) : []
  const missing = c.current_run_id === DEMO_RUN_ID ? rep.checklist.items.filter(i => i.status === 'MISSING' || i.status === 'DEFECTIVE').map(i => ({ id: i.id, requirement: i.requirement, status: i.status })) : []
  return { verdict: r.verdict, blocking_flags: r.blocking_flags, high_flags: high, missing_checklist: missing, checklist_result: r.checklist_result, claimant_name: c.claimant_name, has_issues: r.verdict !== 'FORWARD' || high.length > 0 || missing.length > 0 }
}

function summary(c: Case) {
  const last = c.events[c.events.length - 1]
  return { id: c.id, case_no: c.case_no, department_code: c.department_code, department_name: c.department_name, created_via: c.created_via, created_by: c.created_by,
           status: c.status, status_label: STATUS_LABEL[c.status], claimant_name: c.claimant_name, variant: c.variant, intake: c.intake, submission_no: c.submission_no,
           current_run_id: c.current_run_id, created_at: c.created_at, updated_at: c.updated_at, latest_run: latestRun(c), documents: c.documents.length,
           last_event: last ? { action: last.action, remark: last.remark, actor_name: last.actor_name, actor_role: last.actor_role, at: last.at } : null }
}

function full(c: Case, u: User) {
  return { ...summary(c), documents: c.documents, runs: c.runs, events: c.events, forwarded_with: AG_HOLDS.includes(c.status) || ['APPROVED', 'REJECTED', 'RETURNED'].includes(c.status) ? openIssues(c) : null,
           officer_remark: c.officer_remark, allowed_actions: allowed(c, u) }
}

function visible(u: User): Case[] {
  return u.role === 'DEPT_OFFICER' ? state.cases.filter(c => c.department_code === u.department_code) : state.cases
}

function event(c: Case, action: string, from: string | null, to: string, actor: User | null, remark = '', payload: Record<string, unknown> = {}, runId: string | null = null): Ev {
  const e: Ev = { id: newId(), seq: c.events.length + 1, action, from_status: from, to_status: to, actor_id: actor?.id ?? null,
    actor_name: actor?.display_name ?? 'AI verification', actor_role: actor?.role ?? 'SYSTEM', actor_department: actor?.department_code ?? null, remark, payload, run_id: runId, at: tick(1500) }
  c.events.push(e); c.status = to; c.updated_at = e.at
  return e
}

function stats(u: User, department: string | null) {
  let cs = visible(u)
  if (department && u.role !== 'DEPT_OFFICER') cs = cs.filter(c => c.department_code === department)
  const by_status: Record<string, number> = Object.fromEntries(Object.keys(STATUS_LABEL).map(k => [k, 0]))
  cs.forEach(c => { by_status[c.status] = (by_status[c.status] ?? 0) + 1 })
  const monday = new Date(); monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7)); monday.setHours(0, 0, 0, 0)
  const weeks = Array.from({ length: 12 }, (_, i) => { const d = new Date(monday); d.setDate(d.getDate() - 7 * (11 - i)); return d })
  const wk = (iso: string) => { const d = new Date(iso); const k = weeks.findIndex((w, i) => d >= w && (i === 11 || d < weeks[i + 1])); return k }
  const filed = weeks.map(() => 0), decided = weeks.map(() => 0)
  cs.forEach(c => { const k = wk(c.created_at); if (k >= 0) filed[k] += 1; if (['APPROVED', 'REJECTED'].includes(c.status)) { const e = c.events[c.events.length - 1]; const j = wk(e.at); if (j >= 0) decided[j] += 1 } })
  const deptMap: Record<string, { code: string; name: string; total: number; awaiting: number; approved: number; rejected: number; sent_back: number }> = {}
  cs.forEach(c => { const d = deptMap[c.department_code] ??= { code: c.department_code, name: c.department_name, total: 0, awaiting: 0, approved: 0, rejected: 0, sent_back: 0 }
    d.total++; if (AG_HOLDS.includes(c.status)) d.awaiting++; if (c.status === 'APPROVED') d.approved++; if (c.status === 'REJECTED') d.rejected++; if (['RETURNED', 'DOCS_REQUESTED', 'REJECTED'].includes(c.status)) d.sent_back++ })
  const verdicts = { FORWARD: 0, RETURN_FOR_CORRECTION: 0, HOLD: 0, NONE: 0 }
  const high_flags = { '0': 0, '1': 0, '2': 0, '3+': 0 }
  const defs: Record<string, { id: string; requirement: string; missing: number; defective: number }> = {}
  let verified = 0
  cs.forEach(c => { const r = latestRun(c); if (r && r.state === 'done') { verified++; verdicts[(r.verdict as keyof typeof verdicts) ?? 'NONE'] = (verdicts[(r.verdict as keyof typeof verdicts) ?? 'NONE'] ?? 0) + 1; const h = r.high_flags ?? 0; high_flags[h >= 3 ? '3+' : (String(h) as '0' | '1' | '2')]++
    if (r.checklist_result === 'INCOMPLETE') { const id = c.department_code === 'SCHOOL_EDUCATION' ? 'AG-06' : 'AG-11'; const req = id === 'AG-06' ? 'NADRA Family Registration Certificate/s, attested by the DDO' : 'Bank option form verified by the bank, with indemnity bond'; const d = defs[id] ??= { id, requirement: req, missing: 0, defective: 0 }; d.missing++ } } })
  const ageing = (statuses: string[]) => { const b = { '0-3': 0, '4-7': 0, '8-14': 0, '15+': 0 }; let oldest = 0, oc: string | null = null
    cs.filter(c => statuses.includes(c.status)).forEach(c => { const days = (Date.now() - Date.parse(c.updated_at)) / 86_400_000; b[days <= 3 ? '0-3' : days <= 7 ? '4-7' : days <= 14 ? '8-14' : '15+']++; if (days > oldest) { oldest = days; oc = c.case_no } })
    return { buckets: b, total: Object.values(b).reduce((a, x) => a + x, 0), oldest_days: Math.round(oldest * 10) / 10, oldest_case: oc } }
  const decidedCases = cs.filter(c => ['APPROVED', 'REJECTED'].includes(c.status))
  return { scope: { role: u.role, department: u.role === 'DEPT_OFFICER' ? u.department_code : department }, total: cs.length, by_status,
    weeks: weeks.map((w, i) => ({ week: w.toISOString().slice(0, 10), filed: filed[i], decided: decided[i] })),
    by_department: Object.values(deptMap).sort((a, b) => b.total - a.total), verdicts, high_flags, checks_total: cs.filter(c => c.runs.length).length,
    avg_verification_minutes: 9.4, avg_days_to_decision: decidedCases.length ? 2.6 : null, decided_total: decidedCases.length,
    ageing: { with_department: ageing(['DRAFT', 'AI_CHECKING', 'AI_FAILED', 'AI_CHECKED', 'RETURNED', 'DOCS_REQUESTED']), with_ag: ageing(AG_HOLDS) },
    deficiencies: { verified_cases: verified, items: Object.values(defs) },
    ...(u.role === 'ADMIN' ? { users_by_role: { DEPT_OFFICER: 86, AG_REVIEWER: 1, ADMIN: 1 }, audit_by_day: [] } : {}) }
}

// -- the run ------------------------------------------------------------------------------------

class FakeEventSource extends EventTarget {
  static readonly CONNECTING = 0; static readonly OPEN = 1; static readonly CLOSED = 2
  readonly CONNECTING = 0; readonly OPEN = 1; readonly CLOSED = 2
  readyState = 1; url: string; withCredentials = false
  onmessage: ((ev: MessageEvent) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  onopen: ((ev: Event) => void) | null = null
  private timer: number | null = null
  constructor(url: string) {
    super(); this.url = url
    const live = state.liveRun
    if (!live) { this.readyState = 2; setTimeout(() => this.onerror?.(new Event('error')), 10); return }
    const step = () => {
      const l = state.liveRun
      if (!l || this.readyState === 2) return
      if (l.index >= l.events.length) return
      const e = l.events[l.index++]
      const payload = { seq: e.seq, at: new Date().toISOString().slice(0, 19), stage: e.stage, message: e.message, level: e.level, state: e.state }
      this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(payload) }))
      if (e.stage === 'end') { l.finished = true; finishRun(); return }
      const next = l.events[l.index]
      this.timer = window.setTimeout(step, (next ? next.delay : 500) / state.speed)
    }
    this.timer = window.setTimeout(step, 300)
  }
  close() { this.readyState = 2; if (this.timer) clearTimeout(this.timer) }
}

function finishRun() {
  const l = state.liveRun; if (!l) return
  const c = state.cases.find(x => x.id === l.caseId); if (!c) return
  const r = latestRun(c)!
  r.state = 'done'; r.finished_at = now(); r.verdict = 'HOLD'; r.high_flags = 0; r.checklist_result = 'COMPLETE'
  if (c.status === 'AI_CHECKING') event(c, 'CHECK_DONE', 'AI_CHECKING', 'AI_CHECKED', null, 'AI check complete: engine verdict hold, no issues found.', { verdict: 'HOLD' }, r.run_id)
}

function startRun(c: Case, u: User) {
  const r: Run = { id: newId(), case_id: c.id, run_id: DEMO_RUN_ID, submission_no: c.submission_no, started_by: u.id, started_at: now(), finished_at: null, state: 'running', verdict: null, high_flags: null, blocking_flags: [], checklist_result: null, error: null, auto_forward: 0 }
  c.runs.push(r); c.current_run_id = DEMO_RUN_ID
  event(c, 'RUN_CHECK', c.status, 'AI_CHECKING', u, '', { documents: c.documents.length }, DEMO_RUN_ID)
  state.liveRun = { caseId: c.id, events: buildEvents(), index: 0, finished: false }
  return r
}

function pageBlob(n: number): Response | null {
  const data = (pagesData as Record<string, string>)[String(n)]
  if (!data) return null
  const b64 = data.split(',')[1]
  const bin = atob(b64); const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new Response(bytes, { status: 200, headers: { 'Content-Type': 'image/jpeg', 'Cache-Control': 'no-store' } })
}

// -- the router --------------------------------------------------------------------------------

async function handle(req: Request): Promise<Response> {
  const url = new URL(req.url, window.location.href)
  const p = url.pathname
  const m = req.method.toUpperCase()
  if (p === '/api/health') return json({ ok: true, runs: state.liveRun && !state.liveRun.finished ? 1 : 0 })
  if (p === '/api/variants') return json({ families: [] })
  if (p === '/api/v2/portals') return json({ single_portal: true, ...(portals as object) })
  if (p === '/api/v2/auth/login' && m === 'POST') {
    const body = await req.json().catch(() => ({})) as { username?: string; password?: string }
    const u = state.users.find(x => x.username === (body.username || '').trim())
    if (!u || body.password !== '1234') return fail(401, 'wrong username or password')
    const token = 'demo.' + u.username + '.' + Math.random().toString(36).slice(2)
    state.tokens[token] = u.username
    return json({ token, user: u, capabilities: capabilities(u) })
  }
  const u = userFor(req, url)
  if (!u) return fail(401, 'sign in first')
  if (p === '/api/v2/auth/me') return json({ user: u, capabilities: capabilities(u) })
  if (p === '/api/v2/departments') return json(DEPTS.map(d => ({ code: d.code, name: d.name, digital: 1, slug: d.slug })))
  if (p === '/api/v2/departments/counts') {
    return json(DEPTS.map(d => { const cs = state.cases.filter(c => c.department_code === d.code); const by: Record<string, number> = {}; cs.forEach(c => { by[c.status] = (by[c.status] ?? 0) + 1 })
      return { code: d.code, name: d.name, digital: true, total: cs.length, awaiting_review: cs.filter(c => AG_HOLDS.includes(c.status)).length, by_status: by } }))
  }
  if (p === '/api/v2/stats') return json(stats(u, url.searchParams.get('department')))
  if (p === '/api/v2/cases' && m === 'GET') {
    let cs = visible(u); const d = url.searchParams.get('department'); if (d && u.role !== 'DEPT_OFFICER') cs = cs.filter(c => c.department_code === d)
    return json([...cs].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).map(summary))
  }
  if (p === '/api/v2/cases' && m === 'POST') {
    const form = await req.formData()
    const files = form.getAll('files').filter((f): f is File => f instanceof File)
    const at = now()
    const n = 100 + state.cases.length + 1
    const c: Case = { id: newId(), case_no: `PC-2026-${String(n).padStart(6, '0')}`, department_code: u.department_code ?? DEMO_DEPT, department_name: DEPT_NAME[u.department_code ?? DEMO_DEPT], created_via: 'DEPARTMENT', created_by: u.id, status: 'DRAFT',
      claimant_name: (String(form.get('claimant_name') ?? '').trim() || null), variant: null, intake: {}, submission_no: 1, current_run_id: null, created_at: at, updated_at: at,
      documents: files.map((f, i) => ({ id: newId(), submission_no: 1, seq: i + 1, filename: f.name, sha256: DEMO_RUN_ID.repeat(6).slice(0, 64), bytes: 15_483_212, uploaded_by: u.id, uploaded_at: at })), runs: [], events: [], officer_remark: null }
    c.events.push({ id: newId(), seq: 1, action: 'CREATE', from_status: null, to_status: 'DRAFT', actor_id: u.id, actor_name: u.display_name, actor_role: u.role, actor_department: u.department_code, remark: '', payload: { documents: files.map(f => f.name) }, run_id: null, at })
    state.cases.push(c)
    const run = startRun(c, u)
    return json({ case: full(c, u), check: { run_id: run.run_id, resumed: false, documents: files.length } }, 201)
  }
  let mm = p.match(/^\/api\/v2\/cases\/([^/]+)(?:\/(.*))?$/)
  if (mm) {
    const c = state.cases.find(x => x.id === mm![1]); if (!c) return fail(404, 'no such case')
    if (u.role === 'DEPT_OFFICER' && c.department_code !== u.department_code) return fail(403, 'not your department\'s case')
    const rest = mm[2] ?? ''
    if (!rest) return json(full(c, u))
    if (rest === 'check') { startRun(c, u); return json({ run_id: DEMO_RUN_ID, resumed: false, documents: c.documents.length }, 202) }
    if (rest === 'documents' && m === 'POST') { const form = await req.formData(); const files = form.getAll('files').filter((f): f is File => f instanceof File); const at = now()
      files.forEach((f, i) => c.documents.push({ id: newId(), submission_no: c.submission_no, seq: c.documents.length + i + 1, filename: f.name, sha256: '', bytes: f.size, uploaded_by: u.id, uploaded_at: at })); event(c, 'ADD_DOCS', c.status, 'DRAFT', u, '', { documents: files.map(f => f.name) }); return json(full(c, u), 201) }
    if (rest.startsWith('documents/')) return new Response(new Uint8Array([0x25, 0x50, 0x44, 0x46]), { status: 200, headers: { 'Content-Type': 'application/pdf' } })
    const body = m === 'POST' ? await req.json().catch(() => ({})) as { remark?: string; reason?: string; to_status?: string } : {}
    const remark = (body.remark ?? body.reason ?? '').trim()
    const act = (action: string, to: string) => { const e = event(c, action, c.status, to, u, remark); return json({ event: e, case: full(c, u) }) }
    if (rest === 'forward') { if (c.status !== 'AI_CHECKED') return fail(409, 'run the AI verification on the current documents before submitting'); c.officer_remark = remark || null; return act('FORWARD', 'FORWARDED') }
    if (rest === 'take-up') { if (c.status !== 'FORWARDED') return fail(409, 'the case is not awaiting take-up'); return act('TAKE_UP', 'UNDER_REVIEW') }
    if (['approve', 'reject', 'return', 'request-docs'].includes(rest)) {
      if (!remark) return fail(422, 'a remark is required')
      if (c.status === 'FORWARDED') event(c, 'TAKE_UP', 'FORWARDED', 'UNDER_REVIEW', u)
      if (c.status !== 'UNDER_REVIEW') return fail(409, 'the case is not under review')
      const to = { approve: 'APPROVED', reject: 'REJECTED', return: 'RETURNED', 'request-docs': 'DOCS_REQUESTED' }[rest]!
      return act(rest.toUpperCase().replace('-', '_') === 'REQUEST_DOCS' ? 'REQUEST_DOCS' : rest.toUpperCase(), to)
    }
    if (rest === 'override') { if (!remark) return fail(422, 'a reason is required'); const to = body.to_status ?? c.status; state.audit.unshift({ id: newId(), at: now(), actor_id: u.id, actor_name: u.display_name, actor_role: u.role, action: 'CASE_OVERRIDE', entity_type: 'case', entity_id: c.id, before: { status: c.status }, after: { status: to }, reason: remark, ip: '10.170.1.20' }); return act('OVERRIDE', to) }
    mm = rest.match(/^runs\/([^/]+)\/(.*)$/)
    if (mm) return runRoute(mm[1], mm[2])
    return fail(404, 'no such route')
  }
  mm = p.match(/^\/api\/v2\/runs\/([^/]+)\/(.*)$/)
  if (mm) return runRoute(mm[1], mm[2])
  if (p === '/api/v2/admin/users') return json(state.users.map(x => ({ ...x, token_version: 1, created_at: '2026-09-25T10:00:00', updated_at: '2026-09-25T10:00:00' })))
  if (p === '/api/v2/admin/audit-log') { const actor = (url.searchParams.get('actor') || '').toLowerCase(); return json(state.audit.filter(a => !actor || String(a.actor_name).toLowerCase().includes(actor))) }
  if (p === '/api/v2/admin/overview') { const by: Record<string, number> = {}; state.cases.forEach(c => { by[c.status] = (by[c.status] ?? 0) + 1 }); return json({ cases: state.cases.length, by_status: by, users: state.users.length, departments: DEPTS.length, audit_entries: state.audit.length }) }
  return fail(404, `no such route: ${p}`)

  function runRoute(runId: string, tail: string): Response {
    if (runId !== DEMO_RUN_ID) return fail(404, 'no such run')
    const live = state.liveRun
    if (tail === 'status') return json({ run_id: runId, state: live && !live.finished ? 'running' : 'done', error: null })
    if (tail === 'report') return json(report)
    const pg = tail.match(/^pages\/(\d+)$/)
    if (pg) return pageBlob(Number(pg[1])) ?? fail(404, 'no such page')
    if (tail === 'events') return fail(404, 'use EventSource')
    const gate = { ok: true, computable: true, blocked: false, blocking: [], blocking_flags: [], open: [], reason: null, message: null }
    if (tail === 'dispositions' && m === 'GET') return json({ run_id: runId, current: {}, history: [], gate })
    if (tail === 'dispositions') return json({ flag_id: 'F-1', action: 'UPHOLD', officer: u?.display_name ?? '', role: u?.role ?? '', at: now(), ground: '', gate, current: {} })
    if (tail === 'checklist-actions') return json({ report, gate })
    if (tail === 'bundle') return new Response(new Uint8Array([0x25, 0x50, 0x44, 0x46]), { status: 200, headers: { 'Content-Type': 'application/pdf' } })
    return fail(404, 'no such run route')
  }
}

/** Images are not fetched through window.fetch, so an <img src="/api/v2/runs/…/pages/N"> is
 *  pointed at the embedded page instead, the moment it appears or its src changes. */
function watchImages(): void {
  const fix = (img: HTMLImageElement) => {
    const src = img.getAttribute('src') || ''
    const m = src.match(/\/api\/v2\/(?:cases\/[^/]+\/)?runs\/[^/]+\/pages\/(\d+)/)
    if (!m) return
    const data = (pagesData as Record<string, string>)[m[1]]
    if (data && img.src !== data) img.src = data
  }
  const scan = (root: ParentNode) => root.querySelectorAll?.('img').forEach(i => fix(i as HTMLImageElement))
  new MutationObserver(muts => {
    for (const mu of muts) {
      if (mu.type === 'attributes' && mu.target instanceof HTMLImageElement) fix(mu.target)
      mu.addedNodes.forEach(n => { if (n instanceof HTMLImageElement) fix(n); else if (n instanceof Element) scan(n) })
    }
  }).observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ['src'] })
  scan(document)
}

export function installMock(): void {
  watchImages()
  const realFetch = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(typeof input === 'string' ? input : input.toString(), init)
    const url = new URL(req.url, window.location.href)
    if (!url.pathname.startsWith('/api/')) return realFetch(input, init)
    await new Promise(r => setTimeout(r, 120 + Math.random() * 180))      // a real server's latency
    return handle(req)
  }
  ;(window as unknown as { EventSource: unknown }).EventSource = FakeEventSource
}

export const demoCase = () => state.cases.find(c => c.current_run_id === DEMO_RUN_ID && c.claimant_name === 'Mst. Ghulam Zainab') ?? null
