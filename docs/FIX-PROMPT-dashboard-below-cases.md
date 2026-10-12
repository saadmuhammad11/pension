# Fix prompt — the dashboard is drawn below the cases (department view)

**Reported by the user, 12 Oct 2026, running GP Fund and pension cases.**

> When I open the cases directly it's fine, but when I open the dashboard first and then the
> cases, the dashboard is also shown below the cases.

This is a **frontend-only** routing/layout bug in the portal SPA (`portals/src`). It affects
**both products** (pension and GP Fund) because the register screen is shared. Nothing in the
backend, the rules engine, or the GP Fund module is involved. **Write the fix, confirm the
open question below first, do not change anything else in the working tree.**

---

## 1. What actually happens (root cause — already traced)

The register screen `CaseRegister` can draw two things: the **dashboard** (title, tiles, figures)
and the **cases** (search, filters, table). Which it draws is decided by a `view` prop and a
`casesFirst` flag:

- `portals/src/shared/screens/CaseRegister.tsx:163-164`
  ```ts
  const showDash = view !== 'cases'
  const showCases = view !== 'dashboard'
  ```
- `portals/src/shared/screens/CaseRegister.tsx:370`
  ```tsx
  {casesFirst && showDash && charts}      // the dashboard figures, drawn BELOW the cases
  ```

So the dashboard is appended **below** the cases whenever `casesFirst` is true **and**
`view !== 'cases'` (i.e. `view` is `undefined` or `'dashboard'`).

`casesFirst` is passed **only on the department home** (`PortalShell.tsx`, the `else if (pr)`
branch, ~line 212). It is the intended "department lands on its register, charts below"
layout (business decision, 29 Sep 2026 — see memory `pension-ag-side-verification` /
`pension-sections-sidebar`).

### Why "direct open" differs from "dashboard then cases"

The two navigations land on **different routes** that both render the department register, with
different `view`:

| How the user gets there | Hash route | `pr.view` | computed `view` (`PortalShell.tsx` ~line 183) | result |
|---|---|---|---|---|
| **"Cases" nav link (department)** — `PortalShell.tsx:148` → `#/{slug}` | `#/gpf` | `'home'` | `undefined` (home === 'register') | `showDash=true` → **dashboard drawn below cases** |
| **Direct open / tile / Back** → `#/{slug}/cases` | `#/gpf/cases` | `'cases'` | `'cases'` | `showDash=false` → **clean cases only** |

So the department's **"Cases" nav link points at `#/{slug}`, not `#/{slug}/cases`**
(`PortalShell.tsx:148`), and that combined home is what appends the dashboard underneath.
Compare the AG/review nav, whose "Cases" link *does* point at `#/{slug}/cases`
(`PortalShell.tsx:154`) — which is why the AG view never shows this.

### The deeper inconsistency to resolve

Since the tiered redesign the department nav now has **two separate items**: "Cases"
(`#/{slug}`) **and** "Dashboard" (`#/{slug}/dashboard`, `PortalShell.tsx:149`). That means the
**dashboard is reachable in two places** for a department: appended below the "Cases" home, and
on its own "Dashboard" tab. The user is treating the appended copy as a bug. The `is-active`
class on the "Cases" link (`PortalShell.tsx:148`) even highlights for both `pr.view === 'home'`
and `pr.view === 'cases'`, so the two routes already pretend to be the same "Cases" tab while
rendering differently.

---

## 2. Decision — SETTLED by the user, 12 Oct 2026

> **"Cases" shows only the cases, with the dashboard confined to its own tab.**

So the end state is:

- For a **department**, `#/{slug}` and `#/{slug}/cases` both show **only the cases** (clean —
  tiles + search + table, no figures below).
- The **dashboard** (figures/charts) appears **only** on its own tab, `#/{slug}/dashboard`.
- The 29 Sep 2026 "charts below the register" layout is **retired** for departments; the
  dedicated Dashboard tab replaces it.
- The AG/review and admin views already behave this way and **must not change**.

---

## 3. Implementation (prescribed)

All changes are in `portals/src/shared/`. `productRoute` / the `view` computation live in
`PortalShell.tsx`; the register rendering in `CaseRegister.tsx`; the pass-through in
`RegisterHome.tsx`. The route grammar is in the `PortalShell.tsx` header.

1. **Make the department home resolve to the clean cases view.**
   `PortalShell.tsx:166-167` currently computes `view = undefined` for a department home
   (`pr?.view === 'home' && home === 'register'`). Change that branch to `'cases'` so `view` is
   always `'cases'` or `'dashboard'` — never `undefined`. With `showDash = view !== 'cases'` and
   `showCases = view !== 'dashboard'` (`CaseRegister.tsx:163-164`), the two are then always
   mutually exclusive and the dashboard can never be appended below the cases.

2. **Repoint the department "Cases" nav link** (`PortalShell.tsx:148`) from `#/{slug}` to
   `#/{slug}/cases`, matching the AG nav (line 154). Keep its `is-active` covering both
   `pr?.view === 'cases'` and `pr?.view === 'home'` (so a bare `#/{slug}` still highlights
   "Cases"). Leave the "Dashboard" link (line 149) as `#/{slug}/dashboard`.

3. **Redirect the bare department landing** `#/{slug}` → `#/{slug}/cases` so there is one URL for
   the cases screen. Do it with `navigate('/{slug}/cases', { replace: true })` (see
   `router/hash.ts`) — a **non-replace** redirect would trap **Back** (there is explicit
   handling for this; see `inAppNavigations` and frontend review F17 in `router/hash.ts`).
   *(Alternative, if cleaner in context: keep `#/{slug}` rendering but it now shows clean cases
   via step 1. Either way, `#/{slug}` must not show the dashboard.)*

4. **Remove the now-dead `casesFirst` flag entirely** — it existed only for the charts-below
   layout being retired. Delete it from:
   - `PortalShell.tsx:217` (drop the `casesFirst` prop on the department `RegisterHome`),
   - `RegisterHome.tsx:10,17,35` (param + pass-through),
   - `CaseRegister.tsx:88,91` (param + type),
   - `CaseRegister.tsx:215` — change `{!casesFirst && charts}` to just `{charts}` (the dashboard
     block already only renders when `showDash`, i.e. on the dashboard tab),
   - `CaseRegister.tsx:370` — **delete** the `{casesFirst && showDash && charts}` line (this is
     the line that drew the dashboard below the cases).

   Verify this is behaviour-preserving for AG/admin: they never passed `casesFirst`, so line 215
   already rendered `charts` and line 370 never fired — identical after removal.

5. **Do not lose the department "New case" button.** It currently renders inside the dashboard
   block (`CaseRegister.tsx:189`, under `showDash`), so on the clean cases view (`showDash=false`)
   it will no longer appear there. The header CTA is meant to cover this
   (`pageHasOwnButton`/`newCase`, `PortalShell.tsx:171-174`) — **confirm the "New case" action is
   present and works on the department cases screen after the change**, and adjust
   `pageHasOwnButton` if the route change (`pr.view` now `'cases'` rather than `'home'`) drops or
   doubles it.

6. **Do not regress the AG/review and admin layouts** — their "Cases" is already clean and their
   dashboard is its own view; leave them as-is.

---

## 4. Verification

- **Reproduce first** (as the reporting role — a **department/DDO** login; confirm with the
  user which one, e.g. a `.pension`/DDO account). Steps: sign in → open the **Dashboard** tab →
  click the **Cases** nav link → observe the dashboard figures drawn below the table. Then open
  `#/{slug}/cases` directly → clean. The fix removes the first case.
- Check **both products**: pension and GP Fund (`#/pension…` and `#/gpf…`).
- Check **both roles**: a department user (the bug) and the AG/`ag.reviewer` desk (must stay
  unchanged).
- Confirm **Back** still returns to the previous in-portal screen and never leaves the site.
- `cd portals && npm run build && npm test` (or the repo's configured command) — the frontend
  Vitest suite under `portals/src/**/*.test.ts(x)` must stay green.

## 5. Add a test

There is currently **no test covering `CaseRegister`'s `view`/`casesFirst`/charts logic**
(checked 12 Oct 2026). Add one so this does not regress — assert that:
- `view='cases'` renders the cases and **not** the dashboard charts (both products);
- the department "Cases" route after the fix does not render the dashboard below the cases;
- the AG "Cases" route and the "Dashboard" routes are unchanged.
Put it next to the existing screen tests (`portals/src/shared/screens/*.test.ts`, e.g.
`CaseFindings.test.ts`, `analysisBar.test.ts`) and/or extend the router test
(`portals/src/shared/router/__tests__/hash.test.ts`).

---

## Ground rules (shared working tree)

- The tree currently also carries an **uncommitted `perf/read-cache` change**
  (`extraction/readcache.py`, `api/runs.py`, `pipeline/extract.py`, `tests/test_read_cache.py`,
  `tests/test_run_timings.py`, `docs/PIPELINE-OPTIMIZATION.md`). **Do not touch, commit, or
  revert those files** — they are unrelated to this bug.
- This is a frontend-only fix. Do not change rules, the pipeline, the backend, or the GP Fund
  module.
- Commit only the files this fix needs, with a message that names the route and the role.
