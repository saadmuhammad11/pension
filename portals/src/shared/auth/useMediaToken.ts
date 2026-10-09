/** Re-render when the media token changes, so image addresses built with `withToken` carry the
 *  new one (F10); and the handler an `<img>` calls when the server refused its address. */
import { useEffect, useState } from 'react'
import { mediaTokenRejected, onMediaToken } from './media'

export function useMediaTokenVersion(): number {
  const [v, setV] = useState(0)
  useEffect(() => onMediaToken(() => setV(n => n + 1)), [])
  return v
}

let lastRejectedAt = 0
/** An image failed to load: most likely the media token ran out. Asked for once per 5 s. */
export function imageRefused(): void {
  const now = Date.now()
  if (now - lastRejectedAt < 5000) return
  lastRejectedAt = now
  void mediaTokenRejected()
}
