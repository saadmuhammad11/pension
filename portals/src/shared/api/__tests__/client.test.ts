/** F7: timeouts and plain-language errors; F8: idempotency keys on uploads; F9: requests counted. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../portal', () => ({ portal: () => ({ slug: 'ag' }) }))

import { ApiError, SLOW_OR_BUSY, friendlyMessage, newIdempotencyKey, onInflightChange, request, requestsInFlight, upload } from '../client'
import { setToken } from '../../auth/session'

const jsonResponse = (status: number, body: unknown, type = 'application/json') =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': type } })

describe('friendlyMessage', () => {
  it('maps network failures and gateway errors to the one plain sentence', () => {
    for (const s of [0, 502, 503, 504]) expect(friendlyMessage(s, '<html><body>502 Bad Gateway</body></html>')).toBe(SLOW_OR_BUSY)
  })
  it("keeps the server's own words from a JSON detail", () => {
    expect(friendlyMessage(422, JSON.stringify({ detail: 'Approve needs a remark' }))).toBe('Approve needs a remark')
    expect(friendlyMessage(422, JSON.stringify({ detail: [{ msg: 'field required' }, { msg: 'too short' }] }))).toBe('field required; too short')
  })
  it('never renders an HTML body and never says "Request failed (401)"', () => {
    const m = friendlyMessage(401, '<html><head><title>401</title></head><body>nginx</body></html>')
    expect(m).not.toContain('<')
    expect(m).toBe('Your session has ended. Please sign in again.')
    expect(friendlyMessage(500, '<html>Internal Server Error</html>')).toBe(SLOW_OR_BUSY)
    expect(friendlyMessage(418, '')).toBe('The request was refused (HTTP 418).')
  })
})

describe('request', () => {
  beforeEach(() => { setToken('t0ken'); vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); setToken(null) })

  it('gives up after the time limit with the plain sentence', async () => {
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    })))
    const p = request('GET', '/api/v2/cases', { timeoutMs: 1000 })
    const failure = p.catch(e => e)
    await vi.advanceTimersByTimeAsync(1100)
    const e = await failure
    expect(e).toBeInstanceOf(ApiError)
    expect((e as ApiError).status).toBe(0)
    expect((e as ApiError).message).toBe(SLOW_OR_BUSY)
  })

  it('turns a failed fetch into the plain sentence, and a JSON detail into its words', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))))
    await expect(request('GET', '/api/v2/x')).rejects.toMatchObject({ status: 0, message: SLOW_OR_BUSY })
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(jsonResponse(409, { detail: 'the case changed while you were working on it' }))))
    await expect(request('POST', '/api/v2/x', { json: {} })).rejects.toMatchObject({ status: 409, message: 'the case changed while you were working on it' })
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('<html>Bad Gateway</html>', { status: 502 }))))
    await expect(request('GET', '/api/v2/x')).rejects.toMatchObject({ status: 502, message: SLOW_OR_BUSY })
  })

  it('counts requests in flight for the idle timer', async () => {
    let resolveFetch: (r: Response) => void = () => {}
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(r => { resolveFetch = r })))
    const seen: number[] = []
    const off = onInflightChange(n => seen.push(n))
    const p = request('GET', '/api/v2/x')
    expect(requestsInFlight()).toBe(1)
    resolveFetch(jsonResponse(200, { ok: true }))
    await p
    expect(requestsInFlight()).toBe(0)
    expect(seen).toEqual([1, 0])
    off()
  })
})

describe('upload', () => {
  class FakeXHR {
    static last: FakeXHR | null = null
    headers: Record<string, string> = {}
    status = 201; responseText = JSON.stringify({ case: { id: 'c1' } })
    upload = { onprogress: null as null | ((e: ProgressEvent) => void) }
    onload: null | (() => void) = null; onerror: null | (() => void) = null; onabort: null | (() => void) = null
    open() { FakeXHR.last = this }
    setRequestHeader(k: string, v: string) { this.headers[k] = v }
    send() {
      this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 } as ProgressEvent)
      setTimeout(() => this.onload?.(), 0)
    }
  }
  beforeEach(() => { setToken('t0ken'); vi.stubGlobal('XMLHttpRequest', FakeXHR) })
  afterEach(() => { vi.unstubAllGlobals(); setToken(null) })

  it('sends the Authorization header, an Idempotency-Key, and reports progress', async () => {
    const progress: number[] = []
    const r = await upload<{ case: { id: string } }>('/api/v2/cases', new FormData(), { onProgress: p => progress.push(p.sent / p.total), idempotencyKey: 'k-1' })
    expect(r.case.id).toBe('c1')
    expect(FakeXHR.last!.headers.Authorization).toBe('Bearer t0ken')
    expect(FakeXHR.last!.headers['Idempotency-Key']).toBe('k-1')
    expect(progress).toEqual([0.5])
  })

  it('makes a fresh key per attempt, in UUID shape', () => {
    const a = newIdempotencyKey(), b = newIdempotencyKey()
    expect(a).not.toBe(b)
    expect(a.length).toBeGreaterThan(20)
  })
})
