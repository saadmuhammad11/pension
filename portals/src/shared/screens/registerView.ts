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

/** Whether the screen at this address draws its own "New case" button, so the header's shortcut
 *  stays away: the form itself, and a department's dashboard (the register's title row carries
 *  the button there). A department's cases screen has none of its own, so the header shows it. */
export function pageHasOwnNewCaseButton(view: ProductView | undefined, home: Home): boolean {
  return view === 'new' || (home === 'register' && view === 'dashboard')
}
