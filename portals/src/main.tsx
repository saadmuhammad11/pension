import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './shared/updates'
import './shared/styles/base.css'
import './shared/styles/portals.css'
import './shared/charts/charts.css'
import { applyTheme } from './shared/theme/apply'
import { resolvePortal } from './shared/portal'
import { PortalApp } from './shared/PortalShell'

// A page restored from the browser's back-forward cache after sign-out would show the last
// person's screen; it is reloaded instead, and comes back as the sign-in page.
window.addEventListener('pageshow', e => { if (e.persisted) window.location.reload() })

resolvePortal().then(p => {
  applyTheme(p.theme)
  createRoot(document.getElementById('root')!).render(<StrictMode><PortalApp /></StrictMode>)
})
