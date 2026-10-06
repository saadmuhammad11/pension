/** A rupee figure that counts up to its value.
 *
 *  The one piece of motion on these screens that is about a NUMBER rather than a layout, and
 *  it earns that by pointing at the thing an officer puts their name to. A determination is a
 *  column of working -- base, service, gross, commutation -- and the eye needs telling which
 *  line is the answer.
 *
 *  It counts to the figure the engine produced and stops there. The value is never computed
 *  here, interpolated here, or rounded here: BUILD §2.1 is that no rupee figure may have
 *  anything but the rules engine in its causal chain, and a display that arrives at its own
 *  total by addition would be exactly that. This animates the PRESENTATION of a settled
 *  number, which is why it starts from zero rather than from a previous value.
 */
import { useEffect, useRef, useState } from 'react'

const prefersReducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export function Figure(
  { value, duration = 900, prefix = 'Rs. ' }:
  { value: number; duration?: number; prefix?: string },
) {
  const [shown, setShown] = useState(() => (prefersReducedMotion() ? value : 0))
  const frame = useRef<number>(0)

  useEffect(() => {
    if (prefersReducedMotion()) { setShown(value); return }
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1)
      // Ease out: the figure arrives quickly and settles, rather than crawling the last
      // third the way a linear count does.
      const eased = 1 - Math.pow(1 - t, 3)
      // Math.round, not floor: the last frame must land ON the engine's figure, and a floor
      // would show one rupee less than the determination says for the final frame.
      setShown(Math.round(value * eased))
      if (t < 1) frame.current = requestAnimationFrame(tick)
    }
    frame.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame.current)
  }, [value, duration])

  return (
    <span className="figure-settled" style={{ fontVariantNumeric: 'tabular-nums' }}>
      {prefix}{shown.toLocaleString('en-PK')}
    </span>
  )
}
