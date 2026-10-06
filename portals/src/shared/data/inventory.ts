/** The case inventory, shared by every view in the tab. 30 Sep 2026.
 *
 *  One source of truth per product (GET /api/v2/inventory, api/inventory.py): the rows AND every
 *  count computed from them on the server. Every view of a product -- a department's register,
 *  AG Review's list and sidebar, the Admin register, the dashboards -- reads through here, so no
 *  view keeps a list of its own and no count is worked out in the browser.
 *
 *  Staying current, without a refresh:
 *  *   A change made in this tab (any POST through the API client) refetches at once, and is
 *      broadcast to the other tabs of this browser, which refetch at once too.
 *  *   A change made anywhere else (another officer, the verification finishing) moves the
 *      server's version token, polled every 3 s while the tab is visible and at once when it
 *      comes back into view. A moved token refetches every open view together.
 */
import { useEffect, useState } from 'react'
import { dataChanged, get } from '../api/client'
import type { CaseStatus, CaseSummary, Product } from '../api/cases'

export interface DeptCount {
  code: string; name: string; digital: boolean; pension_section: string
  total: number; awaiting_review: number; by_status: Partial<Record<CaseStatus, number>>
}
export interface InventoryCounts { total: number; by_status: Record<CaseStatus, number>; awaiting_review: number; by_section: Record<string, number> }
export interface Inventory {
  version: string
  rows: CaseSummary[]
  counts: InventoryCounts
  sidebar?: { total: number; by_department: DeptCount[]; by_section: Record<string, number> }
}
export interface InventoryQuery { product: Product; department?: string | null; section?: string | null }

const keyOf = (q: InventoryQuery) => `${q.product}|${q.department ?? ''}|${q.section ?? ''}`
const urlOf = (q: InventoryQuery) => {
  const p = new URLSearchParams({ product: q.product })
  if (q.department) p.set('department', q.department)
  if (q.section) p.set('pension_section', q.section)
  return `/api/v2/inventory?${p}`
}

type Entry = { q: InventoryQuery; data: Inventory | null; error: string | null; listeners: Set<() => void>; inflight: boolean; again: boolean }
const cache = new Map<string, Entry>()
const versionListeners = new Set<() => void>()
let version = ''
let tick = 0

function notify(e: Entry) { e.listeners.forEach(l => l()) }

async function fetchEntry(e: Entry) {
  // A change that lands while a fetch is out is fetched again right after, never dropped.
  if (e.inflight) { e.again = true; return }
  e.inflight = true; e.again = false
  try {
    e.data = await get<Inventory>(urlOf(e.q)); e.error = null
    if (e.data.version) version = e.data.version
  } catch (err) {
    e.error = err instanceof Error ? err.message : String(err)
  } finally {
    e.inflight = false
    notify(e)
    if (e.again) fetchEntry(e)
  }
}

/** Refetch every open view now. `broadcast` also tells the other tabs of this browser. */
export function refreshAll(broadcast = false) {
  tick += 1
  cache.forEach(e => { if (e.listeners.size) fetchEntry(e) })
  versionListeners.forEach(l => l())
  if (broadcast) channel?.postMessage('changed')
}

const channel: BroadcastChannel | null = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('case-inventory') : null
if (channel) channel.onmessage = () => refreshAll(false)
dataChanged.addEventListener('change', () => refreshAll(true))

let polling: ReturnType<typeof setInterval> | null = null
async function checkVersion() {
  if (document.visibilityState !== 'visible') return
  try {
    const { version: v } = await get<{ version: string }>('/api/v2/inventory/version')
    if (v && v !== version) { version = v; refreshAll(false) }
  } catch { /* offline: try again on the next tick */ }
}
function ensurePolling() {
  if (polling) return
  polling = setInterval(checkVersion, 3000)
  document.addEventListener('visibilitychange', checkVersion)
  window.addEventListener('focus', checkVersion)
}

/** The inventory for one query, kept current. Same query in two views = the same object. */
export function useInventory(q: InventoryQuery): { data: Inventory | null; error: string | null; loading: boolean } {
  const key = keyOf(q)
  const [, force] = useState(0)
  useEffect(() => {
    ensurePolling()
    let e = cache.get(key)
    if (!e) { e = { q, data: null, error: null, listeners: new Set(), inflight: false, again: false }; cache.set(key, e) }
    const l = () => force(n => n + 1)
    e.listeners.add(l)
    fetchEntry(e)
    return () => { e!.listeners.delete(l) }
  }, [key])   // eslint-disable-line react-hooks/exhaustive-deps
  const e = cache.get(key)
  return { data: e?.data ?? null, error: e?.error ?? null, loading: !e?.data && !e?.error }
}

/** A number that moves whenever the inventory does: for data that is not the inventory itself
 *  (the dashboards' charts) to refetch in step with it. */
export function useInventoryTick(): number {
  const [t, setT] = useState(tick)
  useEffect(() => {
    ensurePolling()
    const l = () => setT(tick)
    versionListeners.add(l)
    return () => { versionListeners.delete(l) }
  }, [])
  return t
}
