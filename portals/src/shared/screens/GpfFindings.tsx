/** The GP Fund examination, drawn with the pension findings screen's own parts. 30 Sep 2026.
 *
 *  One system, one look: until now the GP Fund module's own screens were framed in here, with
 *  their own tabs and cards. The module stays the authority -- its rules, its findings, who may
 *  decide what (it enforces that per officer), its disposal and issue pack -- and this screen
 *  shows its view in the pension screen's layout: the verdict banner, the Summary / Extracted
 *  Data / Checklist / Flags / Identity tabs, finding cards with page chips, the checklist table.
 *  Every action the module's own screen offered is here, sent through the portal
 *  (api/v2 /cases/{id}/gpf/...), which moves the case when the module's position changes.
 */
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { PagePreview } from '../components/PagePreview'
import { withToken } from '../auth/session'
import { gpfAct, gpfCure, gpfIssuePack, gpfPageUrl, gpfSapTemplate, type CaseFull, type GpfItem, type GpfView } from '../api/cases'

const TABS = ['Summary', 'Extracted Data', 'Checklist', 'Flags', 'Identity', 'Disposal'] as const
type Tab = typeof TABS[number]

/** The module's kinds of finding, in the pension screen's severity language. */
const KIND: Record<GpfItem['status'], { word: string; cls: 'high' | 'medium' | 'low'; bg: string; fg: string }> = {
  hard: { word: 'HARD STOP', cls: 'high', bg: 'var(--redbg)', fg: 'var(--red)' },
  sap: { word: 'SAP', cls: 'medium', bg: 'var(--amberbg)', fg: 'var(--amber)' },
  adv: { word: 'OBSERVATION', cls: 'medium', bg: 'var(--amberbg)', fg: 'var(--amber)' },
  conf: { word: 'VERIFY', cls: 'medium', bg: 'var(--amberbg)', fg: 'var(--amber)' },
  ok: { word: 'SATISFIED', cls: 'low', bg: 'var(--okbg)', fg: 'var(--ok)' },
}

const DISPOSAL_WORD: Record<string, { label: string; help: string; tone: string }> = {
  pay: { label: 'Pass for payment', help: 'Every hard stop cleared; the claim is paid in full.', tone: 'primary' },
  part: { label: 'Pass for part payment', help: 'Accounts Officer or above, and no hard stop open.', tone: 'gold' },
  return: { label: 'Return to the department', help: 'The rejection form lists every open hard stop.', tone: 'danger' },
  refer: { label: 'Refer upward', help: 'Send the case to a senior officer for decision.', tone: '' },
  hold: { label: 'Hold', help: 'Keep the case open, for a reason recorded against it.', tone: '' },
}

/** The pension finding card's button size. */
const SMALL: CSSProperties = { padding: '5px 12px', fontSize: 'var(--t-small)', minHeight: 0 }

const pagesOf = (i: GpfItem) => [...new Set((i.evidence ?? []).map(e => e.page).filter(Boolean))].sort((a, b) => a - b)

function Row({ k, v, mono }: { k: string; v: string | number | null | undefined; mono?: boolean }) {
  return (
    <tr>
      <td className="muted" style={{ width: 170 }}>{k}</td>
      <td className={mono ? 'mono' : undefined}>{v === null || v === undefined || v === '' ? '—' : String(v)}</td>
    </tr>
  )
}

export function GpfFindings({ c, view: initial, canAct, onChanged }:
  { c: CaseFull; view: GpfView; canAct: boolean; onChanged: () => void }) {
  const [view, setView] = useState(initial)
  useEffect(() => setView(initial), [initial])
  const [tab, setTab] = useState<Tab>('Summary')
  const [preview, setPreview] = useState<{ page: number; label: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)
  const L = view.lists
  const flags = useMemo(() => [...L.hard, ...L.sap, ...L.adv], [L])
  const checklist = useMemo(() => [...L.conf, ...L.ok], [L])
  const identity = useMemo(() => [...L.hard, ...L.adv, ...L.conf, ...L.ok].filter(i => i.group === 'signature' || i.group === 'identity'), [L])

  async function run<T extends { case?: GpfView }>(fn: () => Promise<T>) {
    setError(null)
    try {
      const r = await fn()
      if (r.case) setView(r.case)
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      throw e
    }
  }
  const openPage = (page: number, label: string) => setPreview({ page, label })

  return (
    <div className="findings" style={{ marginTop: 'var(--s4)' }}>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <p className="lead" style={{ marginTop: 0 }}>
          GP Fund · {view.meta.label ?? 'claim'}
          {view.meta.personnelNo && ` · personnel no. ${view.meta.personnelNo}`}
          {view.meta.gazetted && view.meta.gazetted !== 'unknown' && ` · ${view.meta.gazetted}`}
          {` · version ${view.version}`}
        </p>
      </div>

      <Verdict view={view} />
      {error && <div className="banner bad" style={{ marginTop: 'var(--s3)' }}><span className="mark">!</span><div className="sub">{error}</div></div>}

      <div className="tabs" role="tablist" style={{ marginTop: 'var(--s5)' }}>
        {TABS.map(t => {
          const count = t === 'Flags' ? flags.length : t === 'Checklist' ? checklist.length : null
          const alert = t === 'Flags' && L.hard.length > 0
          return (
            <button key={t} className="tab" role="tab" aria-selected={t === tab} onClick={() => setTab(t)}>
              {t}{count !== null && <span className={`count${alert ? ' alert' : ''}`}>{count}</span>}
            </button>
          )
        })}
      </div>

      {tab === 'Summary' && (
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <div className="card" style={{ flex: '1 1 320px' }}>
            <h3 style={{ marginTop: 0 }}>Claim</h3>
            <table><tbody>
              <Row k="Kind of claim" v={view.meta.label} />
              <Row k="Personnel number" v={view.meta.personnelNo} mono />
              <Row k="Hard stops" v={view.position.hard} />
              <Row k="Observations" v={view.position.adv} />
              <Row k="To verify" v={view.position.conf} />
              <Row k="SAP items" v={view.position.sap} />
              <Row k="Satisfied checks" v={L.ok.length} />
            </tbody></table>
          </div>
          <div className="card" style={{ flex: '1 1 320px' }}>
            <h3 style={{ marginTop: 0 }}>Examination</h3>
            <table><tbody>
              <Row k="Examined by" v={`${view.officer.name}, ${view.officer.desig}`} />
              <Row k="Returns so far" v={view.returns} />
              <Row k="Disposal" v={view.caseDisp ?? 'not yet disposed'} />
              <Row k="Delegation register" v={view.doa.status} />
              <Row k="Case in the module" v={view.id} mono />
            </tbody></table>
          </div>
          {view.history.length > 0 && (
            <div className="card" style={{ flex: '1 1 100%' }}>
              <h3 style={{ marginTop: 0 }}>Versions</h3>
              <table><tbody>
                {view.history.map(h => <Row key={h.v} k={`v${h.v} · ${h.at}`} v={`${h.reason} — ${h.by}`} />)}
              </tbody></table>
            </div>
          )}
        </div>
      )}

      {tab === 'Extracted Data' && <ExtractedData c={c} view={view} canAct={canAct} run={run} />}

      {tab === 'Checklist' && (
        <div className="card">
          <table>
            <thead><tr><th>Item</th><th>Requirement</th><th>Status</th><th>Pages</th>{canAct && <th />}</tr></thead>
            <tbody>
              {checklist.map(i => <CheckRow key={i.id} i={i} canAct={canAct} onPage={openPage}
                                            onVerify={(ok, note) => run(() => gpfAct(c.id, 'verify', { vid: i.cure?.vid ?? i.id, ok, note }))} />)}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'Flags' && (
        <div className="stagger">
          {flags.length === 0 ? <div className="empty">No issues found.</div>
            : flags.slice(0, showAll ? undefined : 5).map((f, n) => (
              <FindingCard key={f.id} f={f} index={n} canAct={canAct} onPage={openPage}
                           disposition={view.dispositions[f.id] ?? f.disposition ?? null}
                           onDispose={(action, ground, authority) => run(() => gpfAct(c.id, 'dispositions', { resultId: f.id, action, ground, authority }))}
                           onCure={file => run(() => gpfCure(c.id, f.id, file))} />
            ))}
          {flags.length > 5 && (
            <button className="ghost" onClick={() => setShowAll(v => !v)} style={{ marginTop: 'var(--s2)' }}>
              {showAll ? 'Show the first five only' : `Show ${flags.length - 5} more finding${flags.length - 5 === 1 ? '' : 's'}`}
            </button>
          )}
        </div>
      )}

      {tab === 'Identity' && (
        <div className="stack">
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Signatories and delegation of authority</h3>
            <p className="muted" style={{ marginTop: 0 }}>{view.doa.version ?? view.doa.status}</p>
            {identity.length === 0 ? <div className="empty">No identity or signature checks on this claim.</div> : (
              <table><tbody>
                {identity.map(i => (
                  <tr key={i.id}>
                    <td style={{ width: 130 }}><span className={`pill ${KIND[i.status].cls}`}>{KIND[i.status].word}</span></td>
                    <td><strong>{i.title}</strong>{i.finding && <div className="muted" style={{ fontSize: 12 }}>{i.finding}</div>}</td>
                    <td style={{ width: 140 }}>{pagesOf(i).map(p => (
                      <button key={p} className="chip" style={{ cursor: 'pointer' }} onClick={() => openPage(p, i.doc ?? i.title)}>p.{p}</button>))}</td>
                  </tr>
                ))}
              </tbody></table>
            )}
          </div>
        </div>
      )}

      {tab === 'Disposal' && <Disposal c={c} view={view} canAct={canAct} run={run} />}

      {preview && (
        <PagePreview runId={c.id} page={preview.page} document={preview.label}
                     srcFor={p => withToken(gpfPageUrl(c.id, p))} onClose={() => setPreview(null)} />
      )}
    </div>
  )
}

function Verdict({ view }: { view: GpfView }) {
  const P = view.position
  const pay = view.disposalOptions.find(o => o.action === 'pay')
  const [kind, mark, title, line] = view.caseDisp
    ? ['good', 'OK', `Disposed: ${view.caseDisp}`, view.caseNote || 'The examination is closed on this disposal.']
    : P.hard > 0
      ? ['bad', '!', `${P.hard} hard stop${P.hard === 1 ? '' : 's'} — cannot be passed for payment`,
         'Clear or waive each hard stop, or return the case to the department with the rejection form.']
      : P.conf > 0 || P.sap > 0
        ? ['warn', '!', `${P.conf + P.sap} item${P.conf + P.sap === 1 ? '' : 's'} for you to verify`,
           'Confirm each verification task and supply any SAP extract; the claim can then be passed.']
        : pay?.allowed
          ? ['good', 'OK', 'Ready to pass for payment', 'No hard stop open and nothing left to verify.']
          : ['warn', '!', 'Awaiting a decision', pay?.reason || 'See the Disposal tab for what is allowed.']
  return (
    <div className={`banner ${kind}`} style={{ marginTop: 'var(--s5)' }} role="status">
      <span className="mark" aria-hidden="true">{mark}</span>
      <div style={{ flex: 1 }}>
        <div className="row" style={{ gap: 'var(--s2)' }}>
          <span className="title">{title}</span>
          {view.lists.hard.length > 0 && !view.caseDisp && <span className="pill high">blocking {view.lists.hard.map(h => h.id).join(', ')}</span>}
        </div>
        <div style={{ marginTop: 2 }}>{line}</div>
        <div className="muted" style={{ fontSize: 'var(--t-small)', marginTop: 'var(--s2)' }}>
          AI examination only; the decision rests with the Office of the Accountant General.
        </div>
      </div>
    </div>
  )
}

function FindingCard({ f, index, canAct, onPage, disposition, onDispose, onCure }:
  { f: GpfItem; index: number; canAct: boolean
    onPage: (page: number, label: string) => void
    disposition: { action: string; ground?: string; authority?: string; by?: string } | null
    onDispose: (action: string, ground: string, authority: string) => Promise<void>
    onCure: (file: File) => Promise<void> }) {
  const tone = KIND[f.status]
  const [open, setOpen] = useState<null | 'uphold' | 'waive' | 'correct' | 'refer'>(null)
  const [ground, setGround] = useState('')
  const [authority, setAuthority] = useState('')
  const [busy, setBusy] = useState(false)
  const pages = pagesOf(f)
  const act = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); setOpen(null); setGround(''); setAuthority('') } catch { /* shown above */ } finally { setBusy(false) } }
  const observation = f.status === 'hard' || f.status === 'adv'
  return (
    <div className="finding" style={{
      border: '1px solid var(--line)', background: tone.bg, color: tone.fg, borderRadius: 12,
      padding: 'var(--s4) var(--s5)', marginBottom: 'var(--s3)', paddingLeft: 'calc(var(--s5) + 3px)', '--i': index,
    } as CSSProperties}>
      <div className="row" style={{ gap: 'var(--s2)' }}>
        <span className={`pill ${tone.cls}`}>{tone.word}</span>
        <span className="muted mono">{f.id}</span>
        <span className="chip">{f.code}</span>
        <span style={{ fontWeight: 700, fontSize: 'var(--t-lead)', color: 'var(--ink)' }}>{f.title}</span>
      </div>
      <details style={{ marginTop: 'var(--s2)', maxWidth: '82ch', color: 'var(--ink)' }}>
        <summary className="muted" style={{ cursor: 'pointer', fontSize: 'var(--t-small)' }}>Details</summary>
        {f.finding && <div style={{ marginTop: 6 }}>{f.finding}</div>}
        {f.remedy && <div style={{ marginTop: 6, color: 'var(--ok)', fontWeight: 600 }}>→ Action: {f.remedy}</div>}
      </details>
      {pages.length > 0 ? (
        <div className="row" style={{ marginTop: 8, gap: 'var(--s1)' }}>
          <span className="muted" style={{ fontSize: 'var(--t-small)' }}>Open</span>
          {pages.map(p => (
            <button key={p} className="chip" onClick={() => onPage(p, f.doc ?? f.title)}
                    style={{ cursor: 'pointer', border: '1px solid var(--sage2)', padding: '2px 8px', fontSize: 'var(--t-micro)' }}>
              p.{p} {(f.evidence ?? []).find(e => e.page === p)?.label ?? ''}
            </button>
          ))}
        </div>
      ) : (
        <div className="muted" style={{ marginTop: 8, fontSize: 'var(--t-small)' }}>No page located for this finding.</div>
      )}

      <div style={{ marginTop: 'var(--s3)', paddingTop: 'var(--s3)', borderTop: '1px solid rgba(31,41,55,.08)', color: 'var(--ink)' }}>
        {disposition ? (
          <div style={{ fontSize: 'var(--t-small)' }}>
            <strong>{disposition.action.replace(/^\w/, ch => ch.toUpperCase())}</strong>{disposition.by ? ` by ${disposition.by}` : ''}
            {disposition.ground && <span className="muted"> — {disposition.ground}{disposition.authority ? ` (${disposition.authority})` : ''}</span>}
          </div>
        ) : !canAct ? (
          <div className="muted" style={{ fontSize: 'var(--t-small)' }}>Findings are disposed of by the Accounts Office.</div>
        ) : open ? (
          <div>
            {/* Written grounds on every disposition, and the authority on a waiver (G1, 7 Oct 2026).
                A hard stop is waived or recorded corrected by the Deputy AG alone; the module refuses
                anyone else, and says so above. */}
            <div className="label" style={{ marginBottom: 4 }}>
              {open === 'waive' ? 'Grounds for the waiver, and the authority relied on'
                : open === 'uphold' ? 'Grounds for upholding this observation'
                : open === 'correct' ? 'What was corrected, and how it was checked'
                : 'Why this observation is referred upward'}
              {' '}(at least 15 characters)
            </div>
            <textarea rows={2} value={ground} onChange={e => setGround(e.target.value)} placeholder="Grounds…" autoFocus />
            {open === 'waive' && (
              <input value={authority} onChange={e => setAuthority(e.target.value)} placeholder="Authority (rule, order or instruction)" style={{ marginTop: 6, width: '100%' }} />
            )}
            <div className="row" style={{ gap: 'var(--s2)', marginTop: 6 }}>
              <button className="gold" disabled={busy || ground.trim().length < 15 || (open === 'waive' && authority.trim().length < 2)}
                      onClick={() => act(() => onDispose(open, ground.trim(), open === 'waive' ? authority.trim() : ''))}>
                {busy ? 'Recording…' : open === 'waive' ? 'Waive' : open === 'uphold' ? 'Uphold' : open === 'correct' ? 'Record corrected' : 'Refer'}
              </button>
              <button onClick={() => setOpen(null)}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="row" style={{ gap: 'var(--s2)', flexWrap: 'wrap' }}>
            {observation && <>
              <button disabled={busy} style={SMALL} onClick={() => setOpen('uphold')}>Uphold…</button>
              <button disabled={busy} style={SMALL} onClick={() => setOpen('waive')}>Waive…</button>
              <button disabled={busy} style={SMALL} onClick={() => setOpen('correct')}>Corrected…</button>
              <button disabled={busy} style={SMALL} onClick={() => setOpen('refer')}>Refer…</button>
            </>}
            {f.cure?.kind === 'doc' && (
              <label className="btn" style={{ ...SMALL, cursor: 'pointer', border: '1px solid var(--line)', borderRadius: 10, fontWeight: 600 }}>
                Attach the corrected document
                <input type="file" hidden onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) act(() => onCure(file)) }} />
              </label>
            )}
            {f.cure?.kind === 'sap' && <span className="muted" style={{ fontSize: 'var(--t-small)' }}>Cured by the SAP extract, on Extracted Data.</span>}
          </div>
        )}
      </div>
    </div>
  )
}

function CheckRow({ i, canAct, onPage, onVerify }:
  { i: GpfItem; canAct: boolean; onPage: (page: number, label: string) => void
    onVerify: (ok: boolean, note: string) => Promise<void> }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const verifying = i.status === 'conf' && i.cure?.kind === 'verify'
  const act = async (ok: boolean) => { setBusy(true); try { await onVerify(ok, note.trim()) } catch { /* shown above */ } finally { setBusy(false) } }
  return (
    <tr>
      <td className="mono" style={{ fontSize: 12 }}>{i.id}</td>
      <td>
        {i.title}
        {i.finding && <div className="muted" style={{ fontSize: 12 }}>{i.finding}</div>}
        {verifying && canAct && (
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="Note (optional)" style={{ marginTop: 6, width: '100%' }} />
        )}
      </td>
      <td><span className={`pill ${i.status === 'ok' ? 'low' : 'medium'}`}>{i.status === 'ok' ? 'Satisfied' : 'Verify'}</span></td>
      <td>{pagesOf(i).map(p => (
        <button key={p} className="chip" style={{ cursor: 'pointer' }} onClick={() => onPage(p, i.doc ?? i.title)}>p.{p}</button>))}</td>
      {canAct && (
        <td style={{ fontSize: 'var(--t-small)', whiteSpace: 'nowrap' }}>
          {verifying ? (<div className="row" style={{ gap: 6 }}>
            <button disabled={busy} style={{ padding: '5px 10px' }} onClick={() => act(true)}>Confirm</button>
            <button disabled={busy} style={{ padding: '5px 10px' }} onClick={() => act(false)}>Not confirmed</button>
          </div>) : null}
        </td>
      )}
    </tr>
  )
}

function ExtractedData({ c, view, canAct, run }:
  { c: CaseFull; view: GpfView; canAct: boolean; run: (fn: () => Promise<{ case?: GpfView }>) => Promise<void> }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const slip = view.sap.payslip ?? {}
  const upload = async () => { setBusy(true); try { await run(() => gpfAct(c.id, 'sap', { filename: 'extract.txt', text })); setText('') } catch { /* shown above */ } finally { setBusy(false) } }
  // Both figures are EXTRACTED from the papers -- the pay slip's LOAN/FUND block -- never
  // calculated (office instruction, 30 Sep 2026). Where the slip does not print one, it says so.
  const B = view.balances
  const rs = (n: number | null | undefined) => n === null || n === undefined ? null : `Rs. ${Math.round(n).toLocaleString('en-PK')}`
  const at = (x: { page?: number | null; month?: string | null }) =>
    ['read from the SAP pay slip', x.page ? `page ${x.page}` : null, x.month ? `for ${x.month}` : null].filter(Boolean).join(', ')
  const none = B?.payslip ? 'not printed on the SAP pay slip' : 'no SAP pay slip on the case'
  return (
    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
      <div className="card" style={{ flex: '1 1 100%' }}>
        <h3 style={{ marginTop: 0 }}>Balances</h3>
        <table><tbody>
          <Row k="GP Fund balance" v={B?.gpf ? `${rs(B.gpf.value)}  ·  ${at(B.gpf)}` : none} />
          <Row k="GP Fund advance (loan) balance" v={B?.loan ? `${rs(B.loan.value)}  ·  ${at(B.loan)}` : none} />
        </tbody></table>
        {B?.reportClosing && (
          <div className="muted" style={{ fontSize: 'var(--t-small)', marginTop: 6 }}>
            For reference: the SAP re-calculation report prints a closing balance of {rs(B.reportClosing.value)}
            {B.reportClosing.asOf ? ` for the year to ${B.reportClosing.asOf}` : ''}.
          </div>
        )}
      </div>
      <div className="card" style={{ flex: '1 1 320px' }}>
        <h3 style={{ marginTop: 0 }}>SAP pay slip</h3>
        {!view.sap.payslip ? <div className="empty">No SAP pay slip on the case yet.</div> : (
          <table><tbody>
            <Row k="Personnel number" v={slip.persNo as string} mono />
            <Row k="Name" v={slip.name as string} />
            <Row k="Month" v={slip.month as string} />
            <Row k="BPS" v={slip.bps as string} />
            <Row k="Basic pay" v={slip.basicPay !== null && slip.basicPay !== undefined ? `Rs. ${Number(slip.basicPay).toLocaleString('en-PK')}` : null} />
            <Row k="GP Fund balance" v={slip.gpfBalance !== null && slip.gpfBalance !== undefined ? `Rs. ${Number(slip.gpfBalance).toLocaleString('en-PK')}` : null} />
            <Row k="Advance balance" v={slip.loanBalance !== null && slip.loanBalance !== undefined ? `Rs. ${Number(slip.loanBalance).toLocaleString('en-PK')}` : null} />
            <Row k="DDO code" v={slip.ddoCode as string} mono />
          </tbody></table>
        )}
      </div>
      <div className="card" style={{ flex: '1 1 320px' }}>
        <h3 style={{ marginTop: 0 }}>GP Fund re-calculation report</h3>
        {!view.sap.recalc ? <div className="empty">No re-calculation report on the case yet.</div> : (
          <table><tbody>
            <Row k="Report date" v={view.sap.recalc.reportDate} />
            <Row k="Years shown" v={view.sap.recalc.rows} />
            <Row k="Last closing balance" v={view.sap.recalc.lastClosing !== undefined ? `Rs. ${Number(view.sap.recalc.lastClosing).toLocaleString('en-PK')}` : null} />
            <Row k="Source" v={view.sap.source === 'case' ? 'read from the case papers' : view.sap.source} />
          </tbody></table>
        )}
      </div>
      {canAct && (
        <div className="card" style={{ flex: '1 1 100%' }}>
          <h3 style={{ marginTop: 0 }}>Supply a SAP extract</h3>
          <p className="muted" style={{ marginTop: 0 }}>Paste the extract as SAP prints it. The examination is run again on it.</p>
          <textarea rows={6} value={text} onChange={e => setText(e.target.value)} className="mono" style={{ fontSize: 12 }} />
          <div className="row" style={{ gap: 'var(--s2)', marginTop: 8 }}>
            <button className="primary" disabled={busy || text.trim().length < 20} onClick={upload}>{busy ? 'Reading…' : 'Read the extract'}</button>
            <button disabled={busy} onClick={async () => { try { setText((await gpfSapTemplate(c.id)).template) } catch { /* ignore */ } }}>Start from the template</button>
          </div>
        </div>
      )}
    </div>
  )
}

function Disposal({ c, view, canAct, run }:
  { c: CaseFull; view: GpfView; canAct: boolean; run: (fn: () => Promise<{ case?: GpfView }>) => Promise<void> }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [pack, setPack] = useState<Record<string, unknown> | null>(null)
  const dispose = async (action: string) => { setBusy(action); try { await run(() => gpfAct(c.id, 'dispose', { disposal: action, note: note.trim() })) } catch { /* shown above */ } finally { setBusy(null) } }
  const listOf = (k: string) => (pack?.[k] as { id: string; title: string; finding?: string }[] | undefined) ?? []
  return (
    <div className="stack">
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Dispose of the claim</h3>
        {view.caseDisp ? <p style={{ marginTop: 0 }}>Disposed: <strong>{view.caseDisp}</strong>.</p> : !canAct ? <p className="muted">The Accounts Office disposes of the claim.</p> : (<>
          <textarea rows={2} value={note} onChange={e => setNote(e.target.value)} placeholder="Note on the disposal (goes on the record)…" />
          <div className="stack" style={{ gap: 8, marginTop: 10 }}>
            {view.disposalOptions.map(o => {
              const w = DISPOSAL_WORD[o.action] ?? { label: o.action, help: '', tone: '' }
              return (
                <div key={o.action} className="row" style={{ gap: 12, alignItems: 'center' }}>
                  <button className={w.tone === 'primary' ? 'primary' : w.tone === 'gold' ? 'gold' : ''} disabled={!o.allowed || !!busy}
                          style={{ minWidth: 220, ...(w.tone === 'danger' ? { color: 'var(--red)', borderColor: 'var(--red)' } : {}) }}
                          onClick={() => dispose(o.action)}>{busy === o.action ? 'Recording…' : w.label}</button>
                  <span className="muted" style={{ fontSize: 'var(--t-small)' }}>{o.allowed ? w.help : o.reason}</span>
                </div>
              )
            })}
          </div>
        </>)}
      </div>
      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h3 style={{ margin: 0 }}>Issue pack</h3>
          <button onClick={async () => { try { setPack(await gpfIssuePack(c.id)) } catch { /* ignore */ } }}>{pack ? 'Refresh' : 'Prepare the issue pack'}</button>
        </div>
        {pack && (
          <div style={{ marginTop: 10 }}>
            {(['rejectionForm', 'advisoryMemo', 'waivedAndSettled'] as const).map(k => listOf(k).length > 0 && (
              <div key={k} style={{ marginTop: 8 }}>
                <div className="label">{k === 'rejectionForm' ? 'Rejection form' : k === 'advisoryMemo' ? 'Advisory memorandum' : 'Waived and settled'}</div>
                <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                  {listOf(k).map(i => <li key={i.id}><strong>{i.title}</strong>{i.finding ? <span className="muted"> — {i.finding}</span> : null}</li>)}
                </ul>
              </div>
            ))}
            {typeof pack.portalComment === 'string' && pack.portalComment && (
              <div style={{ marginTop: 10 }}><div className="label">Comment for the portal</div><p style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>{pack.portalComment as string}</p></div>
            )}
            <button style={{ marginTop: 10 }} onClick={() => window.print()}>Print</button>
          </div>
        )}
      </div>
    </div>
  )
}
