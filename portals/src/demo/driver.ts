/** The scripted user: a pointer that moves, clicks and types on the real screens; pauses,
 *  restarts and loops. Space pauses, R restarts, F toggles full screen. */

export class RestartSignal extends Error {}

let paused = false
let restartRequested = false
export let SPEED = 1

const cursor = document.createElement('div')
cursor.className = 'demo-cursor'
cursor.innerHTML = '<svg width="26" height="32" viewBox="0 0 26 32"><path d="M2 2 L2 24 L8.5 18.5 L13 29 L17.5 27 L13 16.5 L22 16.5 Z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>'
let cx = window.innerWidth / 2, cy = window.innerHeight / 2

export function installControls(onRestart: () => void): void {
  document.body.appendChild(cursor)
  cursor.style.left = cx + 'px'; cursor.style.top = cy + 'px'
  window.addEventListener('keydown', e => {
    if (e.code === 'Space') { e.preventDefault(); paused = !paused; document.body.classList.toggle('demo-paused', paused) }
    else if (e.key === 'r' || e.key === 'R') { restartRequested = true; paused = false; document.body.classList.remove('demo-paused'); onRestart() }
    else if (e.key === 'f' || e.key === 'F') { if (document.fullscreenElement) document.exitFullscreen().catch(() => {}); else document.documentElement.requestFullscreen().catch(() => {}) }
  })
}

export function takeRestart(): boolean { const r = restartRequested; restartRequested = false; return r }

const raf = () => new Promise<void>(r => requestAnimationFrame(() => r()))

/** Sleep in small steps so a pause or restart takes effect at once. */
export async function sleep(ms: number): Promise<void> {
  const end = performance.now() + ms / SPEED
  while (performance.now() < end || paused) {
    if (restartRequested) throw new RestartSignal()
    await new Promise(r => setTimeout(r, 40))
  }
}

export async function waitFor<T>(fn: () => T | null | undefined | false, timeout = 15000, every = 100): Promise<T> {
  const end = performance.now() + timeout
  while (performance.now() < end) {
    if (restartRequested) throw new RestartSignal()
    if (!paused) { const v = fn(); if (v) return v as T }
    await new Promise(r => setTimeout(r, every))
  }
  throw new Error('waitFor timed out')
}

const ease = (t: number) => t < .5 ? 2 * t * t : -1 + (4 - 2 * t) * t

export async function moveTo(x: number, y: number, ms = 650): Promise<void> {
  const sx = cx, sy = cy, start = performance.now(), dur = ms / SPEED
  while (true) {
    if (restartRequested) throw new RestartSignal()
    if (paused) { await new Promise(r => setTimeout(r, 40)); continue }
    const t = Math.min(1, (performance.now() - start) / dur), k = ease(t)
    // a slight arc, so the pointer does not travel like a machine
    const arc = Math.sin(t * Math.PI) * Math.min(40, Math.hypot(x - sx, y - sy) * 0.08)
    cx = sx + (x - sx) * k; cy = sy + (y - sy) * k - arc
    cursor.style.left = cx + 'px'; cursor.style.top = cy + 'px'
    if (t >= 1) break
    await raf()
  }
}

function centre(el: Element): { x: number; y: number } {
  const r = el.getBoundingClientRect()
  return { x: r.left + Math.min(r.width * 0.5, 160), y: r.top + r.height / 2 }
}

export async function scrollIntoView(el: Element): Promise<void> {
  const r = el.getBoundingClientRect()
  if (r.top < 90 || r.bottom > window.innerHeight - 40) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    await sleep(650)
  }
}

let hovered: Element | null = null
export async function hover(el: Element): Promise<void> {
  await scrollIntoView(el)
  const { x, y } = centre(el)
  await moveTo(x, y)
  hovered?.classList.remove('demo-hover'); hovered = el; el.classList.add('demo-hover')
  el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true })); el.dispatchEvent(new MouseEvent('mouseenter'))
}

export async function click(el: Element, settle = 500): Promise<void> {
  await hover(el)
  await sleep(220)
  cursor.classList.add('is-down')
  const ripple = document.createElement('div'); ripple.className = 'demo-ripple'
  ripple.style.left = cx + 'px'; ripple.style.top = cy + 'px'; document.body.appendChild(ripple)
  setTimeout(() => ripple.remove(), 700)
  ;(el as HTMLElement).focus?.()
  ;(el as HTMLElement).click()
  await sleep(120)
  cursor.classList.remove('is-down')
  hovered?.classList.remove('demo-hover'); hovered = null
  await sleep(settle)
}

/** Type into a React-controlled input: the native setter plus an input event per character. */
export async function type(el: HTMLInputElement | HTMLTextAreaElement, text: string, perChar = 55): Promise<void> {
  await click(el, 150)
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')!.set!
  let value = ''
  for (const ch of text) {
    value += ch
    setter.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
    await sleep(perChar + Math.random() * perChar * 0.8 + (ch === ' ' ? 40 : 0))
  }
  await sleep(300)
}

export async function pickFiles(input: HTMLInputElement, files: File[]): Promise<void> {
  const dt = new DataTransfer()
  files.forEach(f => dt.items.add(f))
  input.files = dt.files
  input.dispatchEvent(new Event('change', { bubbles: true }))
  await sleep(600)
}

/** Find a visible element by tag and the start of its text. */
export function byText(selector: string, text: string, root: ParentNode = document): HTMLElement | null {
  const want = text.toLowerCase()
  const all = Array.from(root.querySelectorAll<HTMLElement>(selector)).filter(el => el.offsetParent !== null)
  const texts = all.map(el => (el.textContent || '').trim().toLowerCase())
  let i = texts.findIndex(t => t === want || t.startsWith(want))
  if (i < 0) i = texts.findIndex(t => t.includes(want))          // a tile begins with its number
  return i >= 0 ? all[i] : null
}

export const q = <T extends Element = HTMLElement>(sel: string, root: ParentNode = document) => root.querySelector<T>(sel)
