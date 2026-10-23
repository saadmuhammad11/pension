// Pure helpers behind the page's handlers: no DOM, no fetch, so `node --test` can exercise them
// (GP/backend/tests/js). The handlers in app.js and api.js stay thin around these (frontend review
// F1, F2, F9, F13, F17 — 9 Oct 2026).

/** HTML-escape a value for interpolation into markup (attribute or text). */
export function escapeHtml(s) {
  return String(s === undefined || s === null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** One path segment: a case or result id is never pasted raw into a URL (F13). */
export function encodeId(id) {
  return encodeURIComponent(String(id === undefined || id === null ? '' : id));
}

/** Rupees the way the office writes them: "Rs 1,234,567" (Western grouping, as SAP prints). */
export function formatRupees(n, { locale = 'en-PK', blank = '' } = {}) {
  if (n === null || n === undefined || n === '') return blank;
  const num = Number(n);
  if (Number.isNaN(num)) return String(n);
  return 'Rs ' + num.toLocaleString(locale, { maximumFractionDigits: 2 });
}

/** Group a number with thousands separators (display only). */
export function formatNumber(n, locale = 'en-PK') {
  if (n === null || n === undefined || n === '') return '';
  const num = Number(n);
  return Number.isNaN(num) ? String(n) : num.toLocaleString(locale, { maximumFractionDigits: 2 });
}

/**
 * At most one call per `everyMs`; later calls inside the window are dropped (not queued). `now`
 * is injectable for tests. Used to tell the portal the officer is active in the frame (F9).
 */
export function throttle(fn, everyMs, now = () => Date.now()) {
  let last = -Infinity;
  return (...args) => {
    const t = now();
    if (t - last < everyMs) return false;
    last = t;
    fn(...args);
    return true;
  };
}

/**
 * The poll loop's patience (F13): one failed request must not abandon a reading job that is
 * still running on the server, and the loop must not run forever either.
 *   budget.failed()  -> true when the loop should give up (too many failures in a row)
 *   budget.ok()      -> a good answer resets the failure count
 *   budget.tick()    -> true when the cap on total polls is reached
 */
export function pollBudget({ maxFailures = 3, maxPolls = 2700 } = {}) {
  let failures = 0, polls = 0;
  return {
    failed() { failures += 1; return failures > maxFailures; },
    ok() { failures = 0; },
    tick() { polls += 1; return polls > maxPolls; },
    get failures() { return failures; },
    get polls() { return polls; },
  };
}

/**
 * A render sequence: `next()` starts a render and returns its token; `isStale(token)` says a
 * newer render has started since, so a slow earlier one must not write over it (F13).
 */
export function sequence() {
  let current = 0;
  return {
    next() { current += 1; return current; },
    isStale(token) { return token !== current; },
    get current() { return current; },
  };
}

/** The confirmation text before a disposal (F2): the case and the outcome, in words. */
/** The heading of a result row: the check's title, and under it the document and signatory the
 *  row is about ("Sanctioning authority, Form A (page 3)"), so six rows of one check do not read
 *  as six copies of the same line (F17). A row with no title is headed by its document. */
export function itemHeading(r) {
  const title = (r && (r.title || r.doc || r.id)) || '';
  const sub = r && r.title && r.doc && r.doc !== r.title ? r.doc : '';
  return { title, sub };
}

export function disposalConfirmText(label, kase) {
  const who = [kase && kase.label, kase && kase.personnelNo ? 'personnel no. ' + kase.personnelNo : '']
    .filter(Boolean).join(', ');
  return `${label} — ${who || 'this case'}. This is recorded on the case under your name and cannot be undone here.`;
}
