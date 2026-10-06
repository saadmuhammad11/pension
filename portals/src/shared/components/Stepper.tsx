/** Persistent four-step stepper. BUILD §9.3: 30px dots, 60px connectors. */

const STEPS = ['Case Intake', 'AI Analysis', 'Review Findings', 'Decision & Dispatch']

export function Stepper({ current }: { current: number }) {
  return (
    <div id="stepper" style={{ background: '#fff', borderBottom: '1px solid var(--line)', padding: '16px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
        {STEPS.map((label, i) => {
          const done = i < current, active = i === current
          return (
            <div key={label} style={{ display: 'flex', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                <div style={{
                  width: 30, height: 30, borderRadius: '50%', display: 'grid', placeItems: 'center',
                  fontSize: 13, fontWeight: 700,
                  background: active ? 'var(--green)' : done ? 'var(--sage)' : '#fff',
                  color: active ? '#fff' : done ? 'var(--green2)' : 'var(--muted)',
                  border: `1px solid ${active ? 'var(--green)' : done ? 'var(--green3)' : 'var(--line)'}`,
                }}
                     className={active ? 'working' : undefined}>{done ? '✓' : i + 1}</div>
                <span style={{
                  fontSize: 13, fontWeight: active ? 700 : 500,
                  color: active ? 'var(--ink)' : 'var(--muted)',
                }}>{label}</span>
              </div>
              {i < STEPS.length - 1 && (
                // The connector fills as the step behind it completes, so progress reads as
                // travel along the row rather than four dots changing colour independently.
                <div className="rail" style={{ width: 60, margin: '0 14px' }}>
                  <span style={{ width: done ? '100%' : '0%' }} />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
