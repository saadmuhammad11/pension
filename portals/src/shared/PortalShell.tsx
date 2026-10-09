/** The portal's frame: sign-in, header, routes, footer.
 *
 *  One portal, two products (28 Sep 2026): pension cases, and GP Fund claims examined by the GP
 *  Fund module. A department portal shows that department's registers to that department's
 *  officer. The AG portal shows the review queues to the Pension Wing and the overview to the
 *  administrator. The server enforces the same split on every call; this file only decides what
 *  to draw.
 *
 *  Routes (hash):  #/                     the chooser: pension or GP Fund
 *                  #/pension  #/gpf       a product's home: the dashboard (a department's register,
 *                                         the AG's review queue, the admin overview)
 *                  #/pension/cases  #/gpf/cases    the cases of that home
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
      {/* Each product opens on its cases list, from wherever the officer is (30 Sep 2026). */}
      <a href="#/pension/cases" className={product === 'PENSION' ? 'is-active' : ''}>Pension</a>
      <a href="#/gpf/cases" className={product === 'GPF' ? 'is-active' : ''}>GP Fund</a>
      {slug && home === 'register' && <>
        <span className="nav-sep" aria-hidden="true" />
        <a href={`#/${slug}`} className={pr?.view === 'home' || pr?.view === 'cases' ? 'is-active' : ''}>Cases</a>
        <a href={`#/${slug}/dashboard`} className={pr?.view === 'dashboard' ? 'is-active' : ''}>Dashboard</a>
      </>}
      {slug && home !== 'register' && <>
        <span className="nav-sep" aria-hidden="true" />
        <a href={`#/${slug}`} className={pr?.view === 'home' || pr?.view === 'dashboard' ? 'is-active' : ''}>Dashboard</a>
        <a href={`#/${slug}/cases`} className={pr?.view === 'cases' ? 'is-active' : ''}>Cases</a>
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
  // register, every case with its timeline, the charts below (29 Sep 2026).
  const view: 'dashboard' | 'cases' | undefined = pr?.view === 'cases' ? 'cases'
    : pr?.view === 'home' && home === 'register' ? undefined : 'dashboard'

  // The department's register and the form itself carry their own new-case button; the header's
  // shortcut is for every other screen of a product, so the same action never shows twice.
  const pageHasOwnButton = !product || pr?.view === 'new' || (home === 'register' && (pr?.view === 'home' || pr?.view === 'dashboard'))
  const newCase = can.create_case && product && !pageHasOwnButton ? (
    <button className="header-cta" onClick={() => navigate(`/${slug}/new`)}>{PRODUCT_WORDS[product].file}</button>
  ) : null

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
    body = <RegisterHome key={pr.product} product={pr.product} title={`${PRODUCT_WORDS[pr.product].cases} — ${user.department_name ?? config.name}`}
                         lead={pr.product === 'PENSION'
                           ? 'Cases filed by this department, and the status of each at the Office of the Accountant General.'
                           : 'GP Fund claims filed by this department, and the status of each at the Office of the Accountant General.'}
                         waitingOn={DEPT_WAITING} newLabel={pr.product === 'PENSION' ? 'New pension case' : 'New GP Fund case'} view={view} casesFirst
                         onNew={can.create_case ? () => navigate(`/${slug}/new`) : undefined} />
  } else {
    body = <ProductChooser />
  }

  return (
    <>
      <Header theme={theme} user={user} onLogout={logout} nav={nav} actions={newCase} />
      <main className="page">{body}</main>
      <Footer />
    </>
  )
}
