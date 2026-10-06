/** A small chart kit in plain SVG, built to the office's palette.
 *
 *  Marks are thin, gridlines are hairlines, one hue carries magnitude, status colours carry
 *  state and always come with a label, and every chart has a table view. Colours are CSS
 *  variables set in charts.css, so the theme owns them.
 */
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'

const fmt = (n: number) => n.toLocaleString('en-PK')

const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** A figure that counts up from zero when it first appears (ease-out, 1.8 s), so the eye lands
 *  on the one number the card is about. Honours reduced motion; `null` shows nothing. */
export function useCountUp(target: number | null, ms = 1800): number | null {
  const [shown, setShown] = useState<number | null>(target === null ? null : reducedMotion() ? target : 0)
  useEffect(() => {
    if (target === null) { setShown(null); return }
    if (reducedMotion() || target === 0) { setShown(target); return }
    const t0 = performance.now()
    let raf = 0
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - p, 3)
      setShown(Math.round(target * e))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return shown
}

/* -- container ------------------------------------------------------------------------- */

export function ChartCard(
  { title, sub, children, table, footer, accent, className }:
  { title: string; sub?: string; children: ReactNode; table?: { head: string[]; rows: (string | number)[][] }; footer?: ReactNode
    /** A colour along the top edge, so a row of cards is scannable. */
    accent?: string; className?: string },
) {
  const [showTable, setShowTable] = useState(false)
  return (
    <figure className={`chart-card${accent ? ' accent' : ''}${className ? ' ' + className : ''}`}
            style={accent ? { '--card-accent': accent } as CSSProperties : undefined}>
      <figcaption className="chart-head">
        <div>
          <div className="chart-title">{title}</div>
          {sub && <div className="chart-sub">{sub}</div>}
        </div>
        {table && (
          <button type="button" className="chart-toggle" onClick={() => setShowTable(!showTable)}>
            {showTable ? 'Chart' : 'Table'}
          </button>
        )}
      </figcaption>
      {showTable && table ? (
        <table className="chart-table">
          <thead><tr>{table.head.map(h => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>{table.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={j ? 'num' : ''}>{c}</td>)}</tr>)}</tbody>
        </table>
      ) : children}
      {footer && <div className="chart-foot">{footer}</div>}
    </figure>
  )
}

/* -- tooltip ------------------------------------------------------------------------------ */

type Tip = { x: number; y: number; title: string; rows: { key?: string; label: string; value: string }[] } | null

function Tooltip({ tip }: { tip: Tip }) {
  if (!tip) return null
  return (
    <div className="chart-tip" style={{ left: tip.x, top: tip.y }} role="status">
      <div className="chart-tip-title">{tip.title}</div>
      {tip.rows.map((r, i) => (
        <div key={i} className="chart-tip-row">
          {r.key && <span className="chart-tip-key" style={{ background: r.key }} />}
          <strong>{r.value}</strong><span>{r.label}</span>
        </div>
      ))}
    </div>
  )
}

/* -- horizontal bars (one series, one hue; or status-coloured with legend) ------------------- */

export function Bars(
  { data, max: maxIn, unit = '', height = 26, status }:
  { data: { label: string; value: number; sub?: string; color?: string }[]; max?: number; unit?: string; height?: number; status?: boolean },
) {
  const [tip, setTip] = useState<Tip>(null)
  const max = Math.max(1, maxIn ?? Math.max(...data.map(d => d.value)))
  if (!data.length) return <div className="empty">No data.</div>
  return (
    <div className="chart-plot" onMouseLeave={() => setTip(null)}>
      {data.map((d, i) => {
        const pct = (d.value / max) * 100
        return (
          <div key={i} className="hbar-row" style={{ height }}
               onMouseMove={e => setTip({ x: e.nativeEvent.offsetX + 12, y: i * height + 8, title: d.label, rows: [{ label: unit || 'cases', value: fmt(d.value) }] })}
               onFocus={() => setTip({ x: 120, y: i * height + 8, title: d.label, rows: [{ label: unit || 'cases', value: fmt(d.value) }] })}
               tabIndex={0}>
            <div className="hbar-label" title={d.label}>{d.label}{d.sub && <span className="muted"> · {d.sub}</span>}</div>
            <div className="hbar-track">
              <div className="hbar-fill" style={{ width: `${pct}%`, background: d.color ?? (status ? 'var(--viz-1)' : 'var(--viz-1)') }} />
            </div>
            <div className="hbar-value num">{fmt(d.value)}</div>
          </div>
        )
      })}
      <Tooltip tip={tip} />
    </div>
  )
}

/* -- split bars (one row per entity, two or three coloured parts on a shared scale, legend) -- */

export function SplitBars(
  { rows, series, unit = 'cases', height = 28 }:
  { rows: { label: string; values: number[]; sub?: string }[]; series: { name: string; color: string }[]; unit?: string; height?: number },
) {
  const [tip, setTip] = useState<Tip>(null)
  const max = Math.max(1, ...rows.map(r => r.values.reduce((a, b) => a + b, 0)))
  if (!rows.length) return <div className="empty">No data.</div>
  return (
    <div className="chart-plot" onMouseLeave={() => setTip(null)}>
      {rows.map((r, i) => {
        const total = r.values.reduce((a, b) => a + b, 0)
        const tipRows = series.map((s, k) => ({ label: s.name, value: fmt(r.values[k] ?? 0) }))
        return (
          <div key={i} className="hbar-row" style={{ height }} tabIndex={0}
               onMouseMove={e => setTip({ x: e.nativeEvent.offsetX + 12, y: i * height + 8, title: r.label, rows: tipRows })}
               onFocus={() => setTip({ x: 120, y: i * height + 8, title: r.label, rows: tipRows })}>
            <div className="hbar-label" title={r.label}>{r.label}{r.sub && <span className="muted"> · {r.sub}</span>}</div>
            <div className="hbar-track" style={{ display: 'flex', gap: 2 }}>
              {series.map((s, k) => (r.values[k] ?? 0) > 0 && (
                <div key={k} className="hbar-fill" style={{ width: `${(r.values[k] / max) * 100}%`, background: s.color, borderRadius: 0 }} />
              ))}
            </div>
            <div className="hbar-value num">{fmt(total)}</div>
          </div>
        )
      })}
      <div className="legend">
        {series.map((s, k) => (
          <span key={k} className="legend-item"><span className="legend-swatch" style={{ background: s.color }} />{s.name} <strong>{fmt(rows.reduce((n, r) => n + (r.values[k] ?? 0), 0))}</strong> {unit}</span>
        ))}
      </div>
      <Tooltip tip={tip} />
    </div>
  )
}

/* -- donut (part to whole; the total in the middle, every slice named in the legend) -------- */

export function Donut(
  { parts, centre, centreLabel, unit = 'cases', size = 176, countUp = false }:
  { parts: { label: string; value: number; color: string; sub?: string }[]; centre?: string | number; centreLabel?: string; unit?: string; size?: number
    /** Count the centre total up from zero when the donut appears (only where the centre is the total). */
    countUp?: boolean },
) {
  const [tip, setTip] = useState<Tip>(null)
  const [hot, setHot] = useState<number | null>(null)
  const total = parts.reduce((n, p) => n + p.value, 0)
  const counted = useCountUp(countUp ? total : null)
  const live = parts.filter(p => p.value > 0)
  if (!total) return <div className="empty">No data.</div>
  const r = 44, stroke = 16, c = 2 * Math.PI * r
  const gap = live.length > 1 ? 2.5 : 0                       // a sliver of surface between slices
  let offset = 0
  const slices = live.map(p => {
    const len = (p.value / total) * c
    const s = { ...p, dash: Math.max(0, len - gap), start: offset, pct: Math.round(p.value / total * 100) }
    offset += len
    return s
  })
  const show = (i: number, x: number, y: number) => {
    const p = slices[i]
    setHot(i); setTip({ x, y, title: p.label, rows: [{ label: `${unit} · ${p.pct}%`, value: fmt(p.value), key: p.color }] })
  }
  return (
    <div className="chart-plot donut" onMouseLeave={() => { setTip(null); setHot(null) }}>
      <svg viewBox="0 0 120 120" width={size} height={size} role="img" aria-label={`${fmt(total)} ${unit}`}>
        <circle cx="60" cy="60" r={r} fill="none" stroke="var(--viz-grid)" strokeWidth={stroke} />
        {slices.map((p, i) => (
          <circle key={i} cx="60" cy="60" r={r} fill="none" stroke={p.color} strokeWidth={hot === i ? stroke + 3 : stroke}
                  strokeDasharray={`${p.dash} ${c - p.dash}`} strokeDashoffset={-p.start} transform="rotate(-90 60 60)"
                  style={{ transition: 'stroke-width .15s ease', cursor: 'default', opacity: hot === null || hot === i ? 1 : .45 }}
                  tabIndex={0} onMouseMove={e => show(i, e.nativeEvent.offsetX + 12, e.nativeEvent.offsetY - 8)} onFocus={() => show(i, size / 2, 8)} />
        ))}
        <text x="60" y="57" textAnchor="middle" className="donut-centre">{counted !== null ? fmt(counted) : centre ?? fmt(total)}</text>
        <text x="60" y="71" textAnchor="middle" className="donut-centre-label">{centreLabel ?? unit}</text>
      </svg>
      <ul className="donut-legend">
        {parts.map((p, i) => (
          <li key={i} className={p.value ? '' : 'is-zero'}>
            <span className="legend-swatch" style={{ background: p.color }} />
            <span className="donut-legend-name">{p.label}{p.sub && <span className="muted"> · {p.sub}</span>}</span>
            <strong className="num">{fmt(p.value)}</strong>
            <span className="muted num">{total ? Math.round(p.value / total * 100) : 0}%</span>
          </li>
        ))}
      </ul>
      <Tooltip tip={tip} />
    </div>
  )
}

/** Identity colours for up to six named things plus "Other"; the legend carries the names. */
export const IDENTITY = ['var(--viz-1)', 'var(--viz-2)', 'var(--viz-3)', 'var(--viz-seq-5)', 'var(--viz-seq-2)', '#7A4E9E', 'var(--viz-deemph)']

/* -- columns (a few categories, one hue) ------------------------------------------------------ */

export function Columns({ data, height = 150, unit = 'cases' }: { data: { label: string; value: number; color?: string; title?: string }[]; height?: number; unit?: string }) {
  const max = Math.max(1, ...data.map(d => d.value))
  const [tip, setTip] = useState<Tip>(null)
  return (
    <div className="chart-plot columns" style={{ height }} onMouseLeave={() => setTip(null)}>
      {data.map((d, i) => (
        <div key={i} className="col" tabIndex={0}
             onMouseMove={e => setTip({ x: e.nativeEvent.offsetX + 12, y: 0, title: d.title ?? d.label, rows: [{ label: unit, value: fmt(d.value) }] })}
             onFocus={() => setTip({ x: 40, y: 0, title: d.title ?? d.label, rows: [{ label: unit, value: fmt(d.value) }] })}>
          <div className="col-value num">{fmt(d.value)}</div>
          <div className="col-track"><div className="col-fill" style={{ height: `${Math.max(d.value ? 6 : 1.5, (d.value / max) * 100)}%`, background: d.color ?? 'var(--viz-1)' }} /></div>
          <div className="col-label">{d.label}</div>
        </div>
      ))}
      <Tooltip tip={tip} />
    </div>
  )
}

/* -- gauge: one figure against a target, with what it means beside it ------------------------ */

export function Gauge(
  { value, max, unit, color, big, bigLabel, note, label }:
  { value: number; max: number; unit: string; color: string; big: string; bigLabel: string; note?: string; label: string },
) {
  const circ = 2 * Math.PI * 48
  const frac = max > 0 ? Math.min(1, value / max) : 0
  return (
    <div className="gauge-wrap">
      <svg viewBox="0 0 120 120" className="gauge" role="img" aria-label={label}>
        <circle cx="60" cy="60" r="48" fill="none" stroke="#EDF1EE" strokeWidth="12" />
        <circle cx="60" cy="60" r="48" fill="none" stroke={color} strokeWidth="12" strokeLinecap="round"
                strokeDasharray={circ} strokeDashoffset={Math.round(circ * (1 - frac) * 10) / 10} transform="rotate(-90 60 60)"
                style={{ transition: 'stroke-dashoffset .8s cubic-bezier(.22,.61,.36,1)' }} />
        <text x="60" y="58" textAnchor="middle" className="gauge-v">{value}</text>
        <text x="60" y="76" textAnchor="middle" className="gauge-u">{unit}</text>
      </svg>
      <div className="gauge-meta">
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <b className="gauge-big">{big}</b>
          <span>{bigLabel}</span>
        </div>
        {note && <div className="gauge-note">{note}</div>}
      </div>
    </div>
  )
}
