/** Where "Pension" and "GP Fund" in the header lead.
 *
 *  They led to `#/{slug}/cases`, always ("each product opens on its cases list, from wherever
 *  the officer is", 30 Sep 2026). The cost of "always" was that switching product also switched
 *  the tab: an officer reading the GP Fund dashboard who pressed Pension landed on the pension
 *  CASES, with the tab underline jumped across, and had to press Dashboard again to get back to
 *  the screen they were already on. The product is the thing being changed; the view is not.
 *
 *  So the tab is carried across. Dashboard stays Dashboard, Cases stays Cases, and anything
 *  that is neither -- a case, the filing form, or arriving with no product at all -- opens the
 *  new product where that role's home is: the cases for a department, the dashboard for the
 *  Accountant General's desk and the administrator (screens/registerView.ts).
 */
import { PRODUCT_SLUG, type Product } from '../api/cases'
import type { Home, ProductView } from './registerView'

export function productHref(product: Product, view: ProductView | undefined, home: Home): string {
  const slug = PRODUCT_SLUG[product]
  // A department's bare #/{slug} redirects to its cases, so its Dashboard has its own address;
  // for every other role the bare address IS the dashboard and 'home' means that tab.
  const onDashboard = view === 'dashboard' || (view === 'home' && home !== 'register')
  const dashboard = home === 'register' ? `#/${slug}/dashboard` : `#/${slug}`
  if (onDashboard) return dashboard
  if (view === 'cases' || view === 'home') return `#/${slug}/cases`
  return home === 'register' ? `#/${slug}/cases` : dashboard
}
