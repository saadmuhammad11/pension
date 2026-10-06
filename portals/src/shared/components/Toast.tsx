/** A quiet confirmation at the bottom of the screen: "Case forwarded to the AG." Gone in 4 s. */
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

type Toast = { id: number; text: string; tone: 'ok' | 'bad' }
const Ctx = createContext<(text: string, tone?: Toast['tone']) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const show = useCallback((text: string, tone: Toast['tone'] = 'ok') => {
    const id = Date.now() + Math.random()
    setItems(x => [...x, { id, text, tone }])
    setTimeout(() => setItems(x => x.filter(t => t.id !== id)), tone === 'ok' ? 4000 : 7000)
  }, [])
  return (
    <Ctx.Provider value={show}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map(t => (
          <div key={t.id} className={`toast ${t.tone}`}>
            <span className="mark">{t.tone === 'ok' ? 'OK' : '!'}</span>{t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}

export const useToast = () => useContext(Ctx)
