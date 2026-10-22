/** The portal's frame: sign-in, header, routes, footer.
 *
 *  One portal, two products (28 Sep 2026): pension cases, and GP Fund claims examined by the GP
 *  Fund module. A department portal shows that department's registers to that department's
 *  officer. The AG portal shows the review queues to the Pension Wing and the overview to the
 *  administrator. The server enforces the same split on every call; this file only decides what
 *  to draw.
 *
 *  Routes (hash):  #/                     the chooser: pension or GP Fund
 *                  #/pension  #/gpf       a product's home: the AG's review dashboard or the admin
 *                                         overview; for a department it is its cases (12 Oct 2026),
 *                                         and the address moves to #/{slug}/cases
 *                  #/pension/cases  #/gpf/cases    the cases of that home
 *                  #/pension/dashboard  #/gpf/dashboard   a department's dashboard, on its own tab
 *                  #/pension/new    #/gpf/new      a new case (where the role may create one)
 *                  #/pension/cases/:id  ·  #/gpf/cases/:id   one case, under its product (…/analysis: on the findings)
 *                  #/cases/:id            the older address; opens, then moves to the product's own
 *                  #/users  #/audit       administration
 */
import { useEffect, useState, type ReactNode } from 'react'
import { AuthProvider, useSession } from './auth/AuthProvider'
import { Header } from './components/Header'
import { Footer } from './components/Footer'
import { ToastProvider } from './components/Toast'
import { inAppNavigations, match, navigate, useHashPath } from './router/hash'
import { ChangePassword, Login } from './screens/Login'
import { Upload } from './screens/Upload'
import { CaseDetail } from './screens/CaseDetail'
import { RegisterHome } from './screens/RegisterHome'
import { ReviewHome } from './screens/ReviewHome'
import { ProductChooser } from './screens/ProductChooser'
import { registerView } from './screens/registerView'
import { productHref } from './screens/productSwitch'
import { AdminHome } from './screens/admin/AdminHome'
import { Users } from './screens/admin/Users'
import { AuditLog } from './screens/admin/AuditLog'
import { Signatories } from './screens/admin/Signatories'
import { PRODUCT_OF_SLUG, PRODUCT_SLUG, PRODUCT_WORDS, caseHref, type CaseStatus, type Product } from './api/cases'
import { isAgReader, type SessionUser } from './auth/session'
import { portal, type PortalConfig } from './portal'
import { checkApiOnline } from './apiOnline'

const DEPT_WAITING: CaseStatus[] = ['DRAFT', 'AI_CHECKED', 'RETURNED', 'DOCS_REQUESTED']
const AG_WAITING: CaseStatus[] = ['FORWARDED', 'AI_FAILED', 'UNDER_REVIEW']

type Home = 'register' | 'review' | 'admin'

function homeFor(user: SessionUser): Home {
  if (isAgReader(user.role)) return 'review'
  if (user.role === 'ADMIN') return 'admin'
  return 'register'
}

export function PortalApp() {
  return (
    <AuthProvider>
      <ToastProvider>
        <Shell config={portal()} />
      </ToastProvider>
    </AuthProvider>
  )
}

/** The API is probed a few times before the outage screen is shown: one dropped request must
 *  not switch a working portal into "unavailable", and a degraded answer (503 for a short disk or
 *  a model down) is still an answer (frontend review F11; shared/apiOnline.ts). */
function useApiOnline(): boolean | null {
  const [online, setOnline] = useState<boolean | null>(null)
  useEffect(() => {
    let live = true
    checkApiOnline({ isLive: () => live }).then(r => { if (live && r !== null) setOnline(r) })
    return () => { live = false }
  }, [])
  return online
}

/** `/pension/cases` → { product: 'PENSION', view: 'cases' }; null where the path is not a product's. */
function productRoute(path: string): { product: Product; view: 'home' | 'dashboard' | 'cases' | 'new' | 'case' | 'analysis'; id?: string } | null {
  const [, slug, rest, id, sub, ...more] = path.split('/')
  const product = PRODUCT_OF_SLUG[slug ?? '']
  if (!product) return null
  if (rest === undefined || rest === '') return { product, view: 'home' }
  if (rest === 'dashboard' && id === undefined) return { product, view: 'dashboard' }
  if (rest === 'new' && id === undefined) return { product, view: 'new' }
  if (rest === 'cases') {
    if (!id) return { product, view: 'cases' }
    let caseId = id
    try { caseId = decodeURIComponent(id) } catch { /* keep as typed */ }
    if (sub === undefined && !more.length) return { product, view: 'case', id: caseId }
    if (sub === 'analysis' && !more.length) return { product, view: 'analysis', id: caseId }
  }
  return null
}

function Shell({ config }: { config: PortalConfig }) {
  const { user, can, loading, logout } = useSession()
  const path = useHashPath()
  const online = useApiOnline()
  const theme = config.theme
  const cleanPath = path.split('?')[0]
  const pr = productRoute(cleanPath)

  // Wrong or forbidden routes go home rather than leaving a broken address in the bar.
  useEffect(() => {
    if (!user || !can) return
    // The Accountant General's desk and the administrator open on the pension register (29 Sep
    // 2026): the product chooser is a department's screen. GP Fund stays one press away in the header.
    if ((cleanPath === '/' || cleanPath === '') && homeFor(user) !== 'register') { navigate('/pension', { replace: true }); return }
    // A department's bare product address is its cases, and the cases have one address (12 Oct
    // 2026): the bare one moves there. Replaced, not pushed, so Back is not trapped on it (F17).
    if (pr?.view === 'home' && homeFor(user) === 'register') { navigate(`/${PRODUCT_SLUG[pr.product]}/cases`, { replace: true }); return }
    const known = cleanPath === '/' || !!pr || cleanPath === '/users' || cleanPath === '/audit' || cleanPath === '/signatories'
      || !!match('/cases/:id', cleanPath) || !!match('/cases/:id/analysis', cleanPath)
    const allowed = (pr?.view !== 'new' || can.create_case) && (cleanPath !== '/users' || can.manage_users)
      && (cleanPath !== '/audit' || can.audit_log) && (cleanPath !== '/signatories' || can.manage_users)
    if (!known || !allowed) navigate('/', { replace: true })
  }, [cleanPath, user, can, pr])

  if (online === false) {
    return (
      <>
        <Header theme={theme} user={null} />
        <main className="page container" style={{ paddingTop: 40 }}>
          <div className="card" style={{ borderColor: 'var(--amber)', background: 'var(--amberbg)' }}>
            <h3 style={{ marginTop: 0 }}>The system is temporarily unavailable</h3>
            <p>The application server is not responding. Please try again shortly or contact the system administrator.</p>
            <button onClick={() => window.location.reload()}>Try again</button>
          </div>
        </main>
        <Footer />
      </>
    )
  }
  if (loading) {
    return <><Header theme={theme} user={null} /><main className="page container" style={{ paddingTop: 30 }}><div className="skeleton" style={{ height: 90 }} /></main><Footer /></>
  }
  if (!user || !can) {
    return <Login theme={theme} portal={config} />
  }
  if (user.must_change_password) {
    return <ChangePassword theme={theme} portal={config} />
  }

  const home = homeFor(user)
  const product: Product | null = pr?.product ?? null
  const slug = product ? PRODUCT_SLUG[product] : null
  // Pension | GP Fund, then the views inside the chosen product; the administrator's pages after.
  const nav: ReactNode = (
    <nav className="portal-nav" aria-label="Products and views">
      {/* Switching product keeps the tab the officer is on (screens/productSwitch.ts). */}
      <a href={productHref('PENSION', pr?.view, home)} className={product === 'PENSION' ? 'is-active' : ''}>Pension</a>
      <a href={productHref('GPF', pr?.view, home)} className={product === 'GPF' ? 'is-active' : ''}>GP Fund</a>
      {product && <>
        <span className="nav-sep" aria-hidden="true" />
        {/* Cases, then Dashboard, on every portal (22 Oct 2026). The two sides had opposite
            orders, each listing the tab that role opens on first: a department opens on its
            cases, the Accountant General's desk and the administrator on the dashboard. One
            order is easier to learn than two, and the cases are the work.
            The addresses are productSwitch's, so the tabs and the product links cannot drift:
            a department's dashboard has its own address because its bare one is its cases,
            and for every other role the bare address IS the dashboard. A bare #/{slug} counts
            as the tab it is about to become while it redirects (12 Oct 2026). */}
        <a href={productHref(product, 'cases', home)}
           className={pr?.view === 'cases' || (pr?.view === 'home' && home === 'register') ? 'is-active' : ''}>Cases</a>
        <a href={productHref(product, 'dashboard', home)}
           className={pr?.view === 'dashboard' || (pr?.view === 'home' && home !== 'register') ? 'is-active' : ''}>Dashboard</a>
      </>}
      {home === 'admin' && <>
        <span className="nav-sep" aria-hidden="true" />
        <a href="#/users" className={cleanPath === '/users' ? 'is-active' : ''}>Users</a>
        <a href="#/audit" className={cleanPath === '/audit' ? 'is-active' : ''}>Audit log</a>
        <a href="#/signatories" className={cleanPath === '/signatories' ? 'is-active' : ''}>Signing authorities</a>
      </>}
    </nav>
  )
  // The AG and the administrator open a product on its dashboard; a department opens on its
  // cases, with the dashboard on its own tab (screens/registerView.ts, 12 Oct 2026). Never both.
  const view = registerView(pr?.view, home)

  // No case action in the header bar (22 Oct 2026). It carried "File a pension case" on every
  // screen of a product that did not draw its own, which meant the one action sat in the bar on
  // the Cases tab and in the page on the Dashboard tab, under two different names. The register
  // draws it on both of its faces now, in the same place, and the bar is left to say who you
  // are and where you are.

  // Back goes to the previous screen of this portal only; a case opened from a bookmark or a
  // new tab has no such screen, so it goes to that product's register instead of leaving the site.
  const back = (p: Product) => {
    if (inAppNavigations() > 0) window.history.back()
    else navigate(`/${PRODUCT_SLUG[p]}/cases`)
  }

  let body: ReactNode
  let m
  if (cleanPath === '/') {
    body = home === 'register' ? <ProductChooser /> : <div className="skeleton" style={{ height: 90, marginTop: 30 }} />
  } else if (pr?.view === 'new' && can.create_case) {
    body = <Upload product={pr.product} onCreated={id => navigate(caseHref(pr.product, id), { replace: true })} onCancel={() => navigate(`/${slug}/cases`)} />
  } else if (pr && (pr.view === 'case' || pr.view === 'analysis') && pr.id) {
    // A case under its product. Opened under the other product's address (a hand-typed link),
    // it moves to its own, so the header never highlights the wrong one.
    const analysis = pr.view === 'analysis'
    body = <CaseDetail key={pr.id} caseId={pr.id} onBack={back} initialTab={analysis ? 'AI findings' : undefined}
                       onProduct={p => { if (p !== pr.product) navigate(caseHref(p, pr.id!, analysis), { replace: true }) }} />
  } else if ((m = match('/cases/:id/analysis', cleanPath)) || (m = match('/cases/:id', cleanPath))) {
    // The address before cases carried their product: still opens, then settles on the new one.
    const id = m.id, analysis = cleanPath.endsWith('/analysis')
    body = <CaseDetail key={id} caseId={id} onBack={back} initialTab={analysis ? 'AI findings' : undefined}
                       onProduct={p => navigate(caseHref(p, id, analysis), { replace: true })} />
  } else if (cleanPath === '/users' && can.manage_users) {
    body = <Users />
  } else if (cleanPath === '/audit' && can.audit_log) {
    body = <AuditLog />
  } else if (cleanPath === '/signatories' && can.manage_users) {
    body = <Signatories />
  } else if (pr && home === 'admin') {
    body = pr.view === 'cases'
      ? <RegisterHome key={pr.product} product={pr.product} title={`All ${PRODUCT_WORDS[pr.product].cases.toLowerCase()}`} lead="Every case filed by every department." waitingOn={AG_WAITING} showDepartment charts={null} view="cases" />
      : <AdminHome key={pr.product} product={pr.product} />
  } else if (pr && home === 'review') {
    body = <ReviewHome key={pr.product} product={pr.product} view={view} />
  } else if (pr) {
    body = <RegisterHome key={pr.product} product={pr.product} title={`${PRODUCT_WORDS[pr.product].cases}, ${user.department_name ?? config.name}`}
                         lead={pr.product === 'PENSION'
                           ? 'Cases filed by this department, and the status of each at the Office of the Accountant General.'
                           : 'GP Fund claims filed by this department, and the status of each at the Office of the Accountant General.'}
                         waitingOn={DEPT_WAITING} newLabel={pr.product === 'PENSION' ? 'New pension case' : 'New GP Fund case'} view={view}
                         onNew={can.create_case ? () => navigate(`/${slug}/new`) : undefined} />
  } else {
    body = <ProductChooser />
  }

  return (
    <>
      <Header theme={theme} user={user} onLogout={logout} nav={nav} />
      <main className="page">{body}</main>
      <Footer />
    </>
  )
}
