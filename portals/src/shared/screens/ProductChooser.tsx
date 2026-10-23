/** The DDO's first screen after sign-in (28 Sep 2026; redesigned 29 Sep): one portal, two kinds of
 *  work. The department chooses what it is submitting -- a pension case or a GP Fund claim -- and
 *  each card carries the department's own standing in that register, how the work runs, and the
 *  two things to do: file a new case, or open the register. The Accountant General's desk and the
 *  administrator never see this screen; they open on the pension register. */
import { useEffect } from 'react'
import { PRODUCT_SLUG, type CaseStatus, type Product } from '../api/cases'
import { useSession } from '../auth/AuthProvider'
import { navigate } from '../router/hash'
import { useStats } from './Dashboard'

const WAITING_ON_DEPT: CaseStatus[] = ['DRAFT', 'AI_CHECKED', 'RETURNED', 'DOCS_REQUESTED']
const WITH_AG: CaseStatus[] = ['FORWARDED', 'AI_CHECKING', 'AI_FAILED', 'UNDER_REVIEW']

const CARDS: { product: Product; kicker: string; title: string; text: string; steps: string[]; file: string; register: string }[] = [
  { product: 'PENSION', kicker: 'Pension', title: 'Pension case',
    text: 'Retirement or family pension: the sanction on the prescribed form with the pension papers.',
    steps: ['Choose the case type and attach every paper', 'Verification at the Office of the Accountant General against the checklist for that type', 'Decision; returned with the list if anything is missing'],
    file: 'File a pension case', register: 'Pension register' },
  { product: 'GPF', kicker: 'GP Fund', title: 'GP Fund claim',
    text: 'An advance, a final payment, missing credits or a balance transfer from the subscriber\'s fund.',
    steps: ['Choose the kind of claim and attach every page', 'Pre-audit in the GP Fund module at the Office of the Accountant General', 'Cure, disposal and the issue pack'],
    file: 'File a GP Fund claim', register: 'GP Fund register' },
]

function Standing({ product }: { product: Product }) {
  const { stats } = useStats(null, product)
  if (!stats) return <div className="choose-standing muted">Loading your register…</div>
  const n = (keys: CaseStatus[]) => keys.reduce((s, k) => s + (stats.by_status[k] ?? 0), 0)
  const mine = n(WAITING_ON_DEPT), ag = n(WITH_AG), done = n(['APPROVED', 'REJECTED'])
  if (!stats.total) return <div className="choose-standing muted">No case filed yet.</div>
  return (
    <div className="choose-standing" aria-label="Your register">
      <span><b>{stats.total}</b> filed</span>
      <span className={mine ? 'is-hot' : ''}><b>{mine}</b> need your action</span>
      <span><b>{ag}</b> with the AG</span>
      <span><b>{done}</b> decided</span>
    </div>
  )
}

export function ProductChooser() {
  const { user } = useSession()
  // Only a DDO chooses. The Accountant General's desk and the administrator open on the pension
  // register whatever address brought them here (the shell redirects too; this is the backstop).
  const ddo = !user || user.role === 'DEPT_OFFICER'
  useEffect(() => { if (!ddo) navigate('/pension', { replace: true }) }, [ddo])
  if (!ddo) return <div className="screen container" style={{ paddingTop: 30 }}><div className="skeleton" style={{ height: 90 }} /></div>
  const today = new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
  return (
    <div className="screen container choose">
      <header className="choose-hero">
        <div className="choose-kicker">{today}</div>
        <h1>{user?.department_name ?? 'Your department'}</h1>
        <p className="lead">What are you submitting to the Office of the Accountant General today? Each kind of work has its own register; both are filed here and both are verified there.</p>
      </header>
      <div className="product-cards">
        {CARDS.map(c => (
          <article key={c.product} className={`product-card is-${c.product.toLowerCase()}`}>
            <div className="product-head">
              <span className="product-mark" aria-hidden="true">{c.product === 'PENSION' ? 'P' : 'GP'}</span>
              <div>
                <div className="product-kicker">{c.kicker}</div>
                <h2 className="product-title">{c.title}</h2>
              </div>
            </div>
            <p className="product-text">{c.text}</p>
            <ol className="product-steps">
              {c.steps.map((s, i) => <li key={i}><span className="product-step-n">{i + 1}</span><span>{s}</span></li>)}
            </ol>
            <Standing product={c.product} />
            <div className="product-actions">
              <button type="button" className={c.product === 'PENSION' ? 'primary' : 'gold'} onClick={() => navigate(`/${PRODUCT_SLUG[c.product]}/new`)}>{c.file}</button>
              <button type="button" onClick={() => navigate(`/${PRODUCT_SLUG[c.product]}/cases`)}>{c.register} →</button>
            </div>
          </article>
        ))}
      </div>
      <p className="choose-foot help">Not sure which? A pension case carries the sanction form B-I to B-IV, D-I or D-II. A GP Fund claim carries the subscriber's GP Fund application or sanction and the pay slip.</p>
    </div>
  )
}
