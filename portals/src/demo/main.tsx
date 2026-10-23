/** The self-running demo: the real portal screens, a fake backend (mock.ts) and a scripted user
 *  (driver.ts). Opens from a file, no server. Space pauses, R restarts, F full screen. */
import { createRoot, type Root } from 'react-dom/client'
import '../shared/styles/base.css'
import '../shared/styles/portals.css'
import '../shared/charts/charts.css'
import './demo.css'
import { applyTheme } from '../shared/theme/apply'
import { setPortalForDemo, type PortalConfig } from '../shared/portal'
import { PortalApp } from '../shared/PortalShell'
import { installMock, reset, demoCase, state } from './mock'
import * as D from './driver'
import { PortalWall, tiles } from './PortalWall'
import portals from './data/portals.json'

type P = { ag: PortalConfig; departments: PortalConfig[] }
const ALL = portals as unknown as P
const AG: PortalConfig = { ...ALL.ag, kind: 'ag' }
const dept = (slug: string): PortalConfig => {
  const d = ALL.departments.find(x => x.slug === slug) ?? ALL.departments.find(x => x.name.toLowerCase().includes(slug.replace(/-/g, ' ')))!
  return { ...d, kind: 'department' }
}

installMock()

const appHost = document.getElementById('root')!
const wallHost = document.createElement('div'); wallHost.id = 'wall'; document.body.appendChild(wallHost)
const appRoot: Root = createRoot(appHost)
const wallRoot: Root = createRoot(wallHost)
let appKey = 0

function mount(cfg: PortalConfig): void {
  try { sessionStorage.clear(); localStorage.clear() } catch { /* ignore */ }
  window.location.hash = '#/'
  setPortalForDemo(cfg)
  applyTheme(cfg.theme)
  appRoot.render(<PortalApp key={++appKey} />)
}

const WALL = tiles()
function showWall(focus: string | null, step = 85): void {
  wallRoot.render(<PortalWall list={WALL} stepMs={step} focus={focus} />)
}

const setWallHidden = (hidden: boolean) => wallHost.classList.toggle('is-hidden', hidden)

async function zoomWallInto(slug: string): Promise<void> {
  const tile = await D.waitFor(() => wallHost.querySelector<HTMLElement>(`.wall-tile[data-slug="${slug}"]`))
  tile.scrollIntoView({ block: 'center', behavior: 'smooth' })
  await D.sleep(500)
  const r = tile.getBoundingClientRect()
  const x = r.left + r.width / 2, y = r.top + r.height / 2
  await D.moveTo(x, y, 700)
  showWall(slug)
  await D.sleep(350)
  wallHost.style.transformOrigin = `${x}px ${y}px`
  wallHost.style.transform = 'scale(5.2)'
  await D.sleep(950)
}

function unzoomWall(): void {
  wallHost.style.transform = 'none'
}

/** Another portal on the same screen: mounted fresh, and given a moment so the sign-in form
 *  the pointer types into is the new one. */
const switchPortal = async (cfg: PortalConfig) => {
  mount(cfg)
  await D.sleep(700)
  await D.waitFor(() => D.q<HTMLInputElement>('#u'))
  await D.sleep(300)
}

const login = async (username: string) => {
  const u = await D.waitFor(() => D.q<HTMLInputElement>('#u'))
  await D.type(u, username, 70)
  await D.type(D.q<HTMLInputElement>('#p')!, '1234', 110)
  await D.click(D.byText('button', 'Sign in')!, 900)
}

const signOut = async () => {
  const b = await D.waitFor(() => D.byText('button', 'Sign out'))
  await D.click(b, 900)
}

async function scenario(): Promise<void> {
  // 1. The wall of portals, then into a few of them.
  appHost.classList.add('is-hidden')
  wallHost.style.transform = 'none'
  setWallHidden(false)
  showWall(null, 70)
  await D.moveTo(window.innerWidth * 0.5, window.innerHeight * 0.45, 900)
  await D.sleep(WALL.length * 70 + 1500)
  const tour: [string, PortalConfig][] = [
    ['school-education', dept('school-education')],
    ['mayo-hospital', dept('mayo-hospital')],
    ['irrigation', dept('irrigation')],
    ['board-of-revenue', dept('board-of-revenue')],
    ['punjab-police', dept('punjab-police')],
  ]
  for (const [i, [slug, cfg]] of tour.entries()) {
    mount(cfg)
    appHost.classList.remove('is-hidden')
    await zoomWallInto(slug)
    setWallHidden(true)
    await D.moveTo(window.innerWidth * 0.5, window.innerHeight * 0.52, 700)
    const last = i === tour.length - 1
    if (!last) {
      await D.sleep(1900)
      unzoomWall(); setWallHidden(false)
      await D.sleep(800)
    }
  }
  wallRoot.render(null)

  // 2. Sign in at the department portal.
  await D.sleep(700)
  await login('punjab-police')
  await D.waitFor(() => D.byText('h1', 'Pension cases'))
  await D.sleep(2200)

  // 3. File the case: documents and the claimant's name.
  await D.click(D.byText('button', 'New pension case')!, 900)
  const fileInput = await D.waitFor(() => D.q<HTMLInputElement>('label.drop input[type=file]'))
  await D.hover(D.byText('button', 'Choose files') ?? D.q('label.drop')!)
  await D.sleep(700)
  const pdf = new File([new Uint8Array(1_200_000)], 'Family Pension - Mst Ghulam Zainab.pdf', { type: 'application/pdf' })
  await D.pickFiles(fileInput, [pdf])
  await D.sleep(1200)
  await D.type(D.q<HTMLInputElement>('#claimant')!, 'Mst. Ghulam Zainab', 65)
  await D.click(D.byText('button', 'File case and run verification')!, 800)

  // 4. The AI verification runs (the stream is replayed, sped up).
  await D.waitFor(() => D.q('.an-bar'), 20000)
  await D.moveTo(window.innerWidth * 0.66, window.innerHeight * 0.62, 900)
  const started = performance.now()
  while (!demoCase() || demoCase()!.status === 'AI_CHECKING') {
    await D.sleep(700)
    if (performance.now() - started > 90000) break
  }
  // the screen lingers on 100 % before it turns to the findings
  await D.waitFor(() => D.q('.findings') || D.byText('.banner .title', 'The AI verification'), 25000)
  await D.sleep(1200)

  // 5. Findings, then a remark and submission to the Accountant General.
  const summary = D.q('.banner.good, .banner.warn')
  if (summary) { await D.hover(summary); await D.sleep(2600) }
  const findingsTab = D.byText('.tab', 'AI findings'); if (findingsTab) { await D.hover(findingsTab); await D.sleep(600) }
  const checklistTab = D.byText('.tab', 'Checklist'); if (checklistTab) { await D.click(checklistTab, 1800) }
  window.scrollTo({ top: 0, behavior: 'smooth' }); await D.sleep(700)
  await D.click(D.byText('button', "Submit to Accountant General's Office")!, 700)
  const remark = await D.waitFor(() => D.q<HTMLTextAreaElement>('aside textarea'))
  await D.type(remark, 'All documents verified and complete. Forwarded for sanction of family pension.', 38)
  await D.click((await D.waitFor(() => D.byText('aside button', 'Confirm'))), 900)
  await D.waitFor(() => D.byText('.pill', "Submitted to Accountant General's Office"))
  await D.sleep(2200)

  // 6. The department's register: the case is with the Accountant General.
  await D.click(D.byText('button', 'Back to the register')!, 900)
  await D.click(D.byText('.tile', 'With the Office of the Accountant General') ?? D.byText('.tile', '1')!, 700)
  await D.waitFor(() => D.byText('.pill', 'Submitted'))
  await D.hover(D.byText('.pill', 'Submitted')!)
  await D.sleep(2600)

  // 7. The Pension Wing, at the Accountant General's portal: sign in, the queue, the department,
  //    the case, the decision.
  await signOut()
  await switchPortal(AG)
  await login('ag.reviewer')
  await D.waitFor(() => D.q('.dept-sidebar'))
  await D.sleep(1800)
  await D.hover(D.byText('.tile', 'Awaiting decision')!); await D.sleep(900)
  await D.hover(D.q('.chart-card')!); await D.sleep(1200)
  await D.click(D.byText('.dept-row', 'Punjab Police')!, 1300)
  await D.click(D.q('.portal-nav a[href="#/cases"]')!, 900)
  await D.click(await D.waitFor(() => D.byText('button.row-go', 'Take up')), 1200)
  await D.waitFor(() => D.byText('.pill', 'Under review at AG Office') || D.byText('.pill', "Submitted to Accountant General's Office"))
  await D.click(D.byText('.tab', 'Documents')!, 1800)
  const doc = D.q('.card table a'); if (doc) { await D.hover(doc); await D.sleep(900) }
  await D.click(D.byText('.tab', 'AI findings')!, 1600)
  const summaryTab = D.byText('.findings .tab', 'Summary'); if (summaryTab) { await D.hover(summaryTab); await D.sleep(1200) }
  const fl = D.byText('.findings .tab', 'Findings') ?? D.byText('.findings .tab', 'Flags'); if (fl) { await D.click(fl, 1800) }
  window.scrollTo({ top: 0, behavior: 'smooth' }); await D.sleep(600)
  await D.click(D.byText('aside button', 'Approve')!, 700)
  const agRemark = await D.waitFor(() => D.q<HTMLTextAreaElement>('aside textarea'))
  await D.type(agRemark, 'Family pension sanctioned. Documents complete; family verified against the NADRA certificate.', 36)
  await D.click((await D.waitFor(() => D.byText('aside button', 'Confirm'))), 900)
  await D.waitFor(() => D.byText('.pill', 'Approved'))
  await D.sleep(2600)

  // 8. Back at the department: approved, with the Accountant General's remark.
  await signOut()
  await switchPortal(dept('punjab-police'))
  await login('punjab-police')
  await D.waitFor(() => D.byText('h1', 'Pension cases'))
  await D.click(D.byText('.tile', 'Disposed')!, 900)
  const approvedRow = await D.waitFor(() => D.byText('.pill', 'Approved'))
  await D.hover(approvedRow); await D.sleep(1000)
  const openBtn = approvedRow.closest('tr')?.querySelector('button.row-go')
  if (openBtn) await D.click(openBtn, 1200)
  await D.click(await D.waitFor(() => D.byText('.tab', 'Remarks and history')), 1400)
  const agLine = D.byText('.card *', 'Family pension sanctioned'); if (agLine) await D.hover(agLine)
  await D.sleep(3200)

  // 9. Administration: the overview and the audit log.
  await signOut()
  await switchPortal(AG)
  await login('admin')
  await D.waitFor(() => D.byText('h1', 'System overview'))
  await D.moveTo(window.innerWidth * 0.5, window.innerHeight * 0.5, 800)
  await D.sleep(2600)
  await D.click(D.q('.portal-nav a[href="#/cases"]')!, 1200)
  await D.hover(D.byText('.tile', 'All cases')!); await D.sleep(1600)
  await D.click(D.q('.portal-nav a[href="#/audit"]')!, 1200)
  await D.sleep(3200)

  // 10. And again.
  appHost.classList.add('is-hidden')
  await D.sleep(1400)
}

async function forever(): Promise<void> {
   
  while (true) {
    reset()
    try { await scenario() }
    catch (e) {
      if (!(e instanceof D.RestartSignal)) { console.warn('[demo] scene stopped:', e); await D.sleep(1500).catch(() => {}) }
    }
    D.takeRestart()
    if (state.liveRun) state.liveRun = null
  }
}

D.installControls(() => { /* the running scene sees the restart flag on its next step */ })
forever()
