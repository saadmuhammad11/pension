/** The hands-on demo: the real portal screens with a built-in stand-in for the backend, and
 *  nothing scripted -- you pick a portal, sign in (any account, password 1234), file a case,
 *  watch the verification, submit, sign out and sign in as the reviewer or the administrator. */
import { createRoot, type Root } from 'react-dom/client'
import '../shared/styles/base.css'
import '../shared/styles/portals.css'
import '../shared/charts/charts.css'
import './demo.css'
import { applyTheme } from '../shared/theme/apply'
import { setPortalForDemo, type PortalConfig } from '../shared/portal'
import { PortalApp } from '../shared/PortalShell'
import { installMock } from './mock'
import { PortalWall, tiles } from './PortalWall'
import portals from './data/portals.json'

type P = { ag: PortalConfig; departments: PortalConfig[] }
const ALL = portals as unknown as P
const AG: PortalConfig = { ...ALL.ag, kind: 'ag' }
const configFor = (slug: string): PortalConfig => {
  if (slug === 'ag' || slug === 'admin') return AG
  const d = ALL.departments.find(x => x.slug === slug)!
  return { ...d, kind: 'department' }
}

installMock()
document.body.classList.add('demo-manual')

const appHost = document.getElementById('root')!
const wallHost = document.createElement('div'); wallHost.id = 'wall'; document.body.appendChild(wallHost)
const appRoot: Root = createRoot(appHost)
const wallRoot: Root = createRoot(wallHost)
let appKey = 0

function openPortal(slug: string): void {
  const cfg = configFor(slug)
  try { sessionStorage.clear(); localStorage.clear() } catch { /* ignore */ }
  window.location.hash = '#/'
  setPortalForDemo(cfg)
  applyTheme(cfg.theme)
  appRoot.render(<PortalApp key={++appKey} />)
  appHost.classList.remove('is-hidden')
  wallHost.classList.add('is-hidden')
  back.hidden = false
}

function showWall(): void {
  wallHost.classList.remove('is-hidden')
  appHost.classList.add('is-hidden')
  back.hidden = true
}

// A quiet way back to the wall of portals, for choosing another department.
const back = document.createElement('button')
back.className = 'demo-back'; back.textContent = 'All portals'; back.hidden = true
back.onclick = showWall
document.body.appendChild(back)
window.addEventListener('keydown', e => {
  if (e.key === 'Escape') showWall()
  else if (e.key === 'f' || e.key === 'F') { if (document.fullscreenElement) document.exitFullscreen().catch(() => {}); else document.documentElement.requestFullscreen().catch(() => {}) }
})

const WALL = tiles()
wallRoot.render(<PortalWall list={WALL} stepMs={40} focus={null} onPick={openPortal} />)
