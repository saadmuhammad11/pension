/** The run-level API the shared screens were written against, now under /api/v2.
 *
 *  Same function names and shapes as the old portal's `api.ts`, so the copied screens (the
 *  live analysis, the findings, the page viewer, the checklist) import this and work. What
 *  changed underneath: every call carries the portal's token, the server decides who the
 *  officer is from that token (so `officer` and `role` in bodies are ignored), and images and
 *  the event stream carry the token on the URL because the browser cannot add a header there.
 */
import type { CaseReport } from './types'
import { get, post } from './api/client'
import { recheckSession, withToken } from './auth/session'

export interface RunEvent {
  seq: number
  at: string
  /** The full moment (ISO), from 30 Sep 2026; `at` is the time of day only. */
  ts?: string
  stage: string
  message: string
  level?: 'warn' | 'error'
  state?: string
}

/** Kept as a string so the copied components compile; the server reads the role off the token. */
export type Role = string

/** Subscribe to a run's stage events. Returns an unsubscribe function. */
export function subscribe(
  runId: string,
  onEvent: (e: RunEvent) => void,
  onEnd: (state: string) => void,
): () => void {
  // The stream replays the run from its first event on every (re)connection, and the caller
  // drops what it already has by `seq`. So a dropped connection is simply opened again: the
  // screen carries on from the latest state, with no reset and no "failed" for a hiccup. Only
  // the run itself saying it has ended -- in the stream, or in its status -- ends the watch.
  let src: EventSource | null = null
  let stopped = false, ended = false, delay = 1000
  let timer: ReturnType<typeof setTimeout> | null = null
  const end = (state: string) => { if (ended) return; ended = true; stopped = true; src?.close(); onEnd(state) }
  const open = () => {
    if (stopped) return
    src = new EventSource(withToken(`/api/v2/runs/${runId}/events`))
    src.onopen = () => { delay = 1000 }
    src.onmessage = ev => {
      const e: RunEvent = JSON.parse(ev.data)
      onEvent(e)
      if (e.stage === 'end') end(e.state ?? 'done')
    }
    src.onerror = () => {
      recheckSession()                                   // a 401 ends the session
      src?.close()
      if (stopped) return
      // Before trying again, ask whether the run has finished while the stream was down.
      get<{ state: string }>(`/api/v2/runs/${runId}/status`)
        .then(st => { if (st.state === 'done' || st.state === 'failed') end(st.state) })
        .catch(() => { /* the server is unreachable: keep trying */ })
      timer = setTimeout(open, delay)
      delay = Math.min(delay * 2, 15000)
    }
  }
  open()
  return () => { stopped = true; if (timer) clearTimeout(timer); src?.close() }
}

/** Where a run stands, from the server: its real start, for a screen opened mid-run. */
export const runStatus = (runId: string) =>
  get<{ run_id: string; state: string; started_at: string; finished_at: string; events: number }>(`/api/v2/runs/${runId}/status`)

export const fetchReport = (runId: string) => get<CaseReport>(`/api/v2/runs/${runId}/report`)

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

export const fetchDispositions = (runId: string) => get<Dispositions>(`/api/v2/runs/${runId}/dispositions`)

export const postDisposition = (
  runId: string,
  body: { flag_id: string; action: Disposition['action']; ground?: string; officer?: string; role?: Role },
) => post<Disposition & { gate: CalculationGate; current: Record<string, Disposition> }>(
  `/api/v2/runs/${runId}/dispositions`, body)

export const postChecklistAction = (
  runId: string,
  body: { action: 'IDENTIFY' | 'NAME' | 'WAIVE' | 'CLEAR'; officer?: string; role?: Role
          item_id?: string; pages?: number[]; document_name?: string; ground?: string; name_id?: string },
) => post<{ report: CaseReport; gate: CalculationGate }>(`/api/v2/runs/${runId}/checklist-actions`, body)

export const pageImageUrl = (runId: string, page: number) =>
  withToken(`/api/v2/runs/${runId}/pages/${page}`)

/** The specimen register is reference data, open to every desk; the cut signature is a run artefact. */
export const specimenImageUrl = (specimenId: string, name: string) =>
  `/api/specimens/${encodeURIComponent(specimenId)}/images/${encodeURIComponent(name)}`
export const signatureImageUrl = (runId: string, name: string) =>
  withToken(`/api/v2/runs/${runId}/signatures/${encodeURIComponent(name)}`)
