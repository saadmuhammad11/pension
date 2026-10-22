/** Which of the register's two faces a product address shows: the dashboard (title, tiles, the
 *  figures) or the cases (search, filters, the table). Never both.
 *
 *  Until 12 Oct 2026 a department's bare product address (#/gpf, the "Cases" link) computed no
 *  view at all, and the register then drew the cases with the dashboard appended below them,
 *  while #/gpf/cases drew the cases alone: "when I open the dashboard first and then the cases,
 *  the dashboard is also shown below the cases." The user's decision of 12 Oct 2026: "Cases"
 *  shows only the cases, and the dashboard is confined to its own tab. So a department's home
 *  is its cases, as #/{slug}/cases is; the AG's desk, the Pension Wing and the administrator open
 *  a product on its dashboard, as before. */
export type RegisterView = 'dashboard' | 'cases'
export type ProductView = 'home' | 'dashboard' | 'cases' | 'new' | 'case' | 'analysis'
export type Home = 'register' | 'review' | 'admin'

export function registerView(view: ProductView | undefined, home: Home): RegisterView {
  if (view === 'cases') return 'cases'
  if (view === 'home' && home === 'register') return 'cases'
  return 'dashboard'
}

/* pageHasOwnNewCaseButton lived here: it decided whether the header bar drew the new-case
   shortcut, by answering whether the page below it had one of its own. Both faces of the
   register draw their own button now and the bar draws none, so there is nothing to decide
   (22 Oct 2026). */
