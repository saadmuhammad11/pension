/** Is the application server there at all? (frontend review F11, 9 Oct 2026)
 *
 *  The portal used to call any non-200 answer from /api/health an outage and gave up after three
 *  3-second probes -- too short for the office Wi-Fi, and since the health route began reporting
 *  a short disk or a model down with a 503, every user saw the outage screen for a degraded
 *  server that was serving cases perfectly well. Now any HTTP answer at all means the server is
 *  up; only when every probe fails at the network level (no answer within 10 s, connection
 *  refused) is the system called unavailable. */

export const PROBE_TIMEOUT_MS = 10_000
export const PROBE_ATTEMPTS = 3
export const PROBE_GAP_MS = 1500

export async function checkApiOnline(
  { attempts = PROBE_ATTEMPTS, timeoutMs = PROBE_TIMEOUT_MS, gapMs = PROBE_GAP_MS, fetchImpl = fetch, isLive = () => true }:
  { attempts?: number; timeoutMs?: number; gapMs?: number; fetchImpl?: typeof fetch; isLive?: () => boolean } = {},
): Promise<boolean | null> {
  for (let i = 0; i < attempts; i++) {
    if (!isLive()) return null
    try {
      await fetchImpl('/api/health', { signal: AbortSignal.timeout(timeoutMs), cache: 'no-store' })
      return true                                 // any status: the server answered
    } catch {
      if (i + 1 < attempts) await new Promise(r => setTimeout(r, gapMs))
    }
  }
  return isLive() ? false : null
}
