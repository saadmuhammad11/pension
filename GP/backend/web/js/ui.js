// Small DOM + formatting helpers shared by the views. The pure parts live in pure.js so they
// can be tested without a browser (GP/backend/tests/js).
import { BASE } from './api.js';
import { escapeHtml, encodeId, formatNumber, formatRupees } from './pure.js';

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export const esc = escapeHtml;

export function h(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export const STATUS = {
  ok: ['b-ok', 'Satisfied'], sub: ['b-sub', 'Satisfied by substitute'],
  hard: ['b-hard', 'Hard stop'], adv: ['b-adv', 'Observation'],
  conf: ['b-conf', 'Verify'], sap: ['b-sap', 'Awaiting SAP'], na: ['b-na', 'N/A'],
};

export function badge(status, label) {
  const s = STATUS[status] || STATUS.na;
  return `<span class="badge ${s[0]}">${esc(label || s[1])}</span>`;
}

export function toast(msg, isErr) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast on' + (isErr ? ' err' : '');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.className = 'toast'; }, isErr ? 4200 : 2600);
}

// The modal is a real dialog (F13): focus moves into it, Tab stays inside it, and focus goes back
// to the control that opened it when it closes. `openModal` returns the dialog element.
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
let modalOpener = null;

export function openModal(title, bodyHtml) {
  const modal = $('#modal');
  modalOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = bodyHtml;
  modal.classList.add('on');
  const first = $$(FOCUSABLE, $('#modal-body'))[0] || $('#modal-close');
  if (first) first.focus();
  return modal;
}
export function closeModal() {
  const modal = $('#modal');
  if (!modal.classList.contains('on')) return;
  modal.classList.remove('on');
  if (modalOpener && document.contains(modalOpener)) modalOpener.focus();
  modalOpener = null;
}
export function trapModalFocus(e) {
  const modal = $('#modal');
  if (e.key !== 'Tab' || !modal.classList.contains('on')) return;
  const items = $$(FOCUSABLE, $('.modal-box', modal));
  if (!items.length) return;
  const first = items[0], last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

/**
 * A yes/no question in the modal (F2): resolves true on the confirm button, false on Cancel,
 * Escape or the backdrop. Used before every disposal, naming the case and the outcome.
 */
export function confirmDialog(title, bodyText, confirmLabel = 'Confirm') {
  return new Promise(resolve => {
    openModal(title, `<p>${esc(bodyText)}</p>
      <div class="row"><button class="btn primary" id="confirm-go">${esc(confirmLabel)}</button>
      <button class="btn" id="confirm-no">Cancel</button></div>`);
    let settled = false;
    const done = v => { if (settled) return; settled = true; $('#modal').removeEventListener('transitionend', noop); resolve(v); };
    const noop = () => {};
    $('#confirm-go').onclick = () => { closeModal(); done(true); };
    $('#confirm-no').onclick = () => { closeModal(); done(false); };
    // Closed any other way (Escape, the backdrop, the x): that is "no".
    const watch = new MutationObserver(() => { if (!$('#modal').classList.contains('on')) { watch.disconnect(); done(false); } });
    watch.observe($('#modal'), { attributes: true, attributeFilter: ['class'] });
  });
}

/**
 * Run one request from a button (F2): the button is disabled and marked busy for the whole
 * request, so a second click cannot send it twice; it is re-enabled afterwards (on success the
 * caller usually re-renders, which replaces the button anyway).
 */
export async function busy(btn, fn) {
  if (!btn || btn.disabled) return undefined;
  const label = btn.textContent;
  btn.disabled = true;
  btn.setAttribute('aria-busy', 'true');
  btn.textContent = label.replace(/…$/, '') + '…';
  try {
    return await fn();
  } finally {
    if (document.contains(btn)) {
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
      btn.textContent = label;
    }
  }
}

export const fmt = formatNumber;
export const rupees = formatRupees;

// evidence crop -> served URL under /assets/evidence/<case-family-dir>/<file>
export function evidenceUrl(template, crop) {
  if (!crop) return null;
  // crops are named like "<template>_pNNN_...png" and live in evidence/<dir>/
  return `${BASE}/assets/evidence/${encodeId(template)}/${encodeId(crop)}`;
}

export function pageUrl(template, page, c) {
  // A claim read from scans serves its own pages (30 Sep 2026); the demo cases' are static assets.
  if (c && c.pageImages) return `${BASE}/api/cases/${encodeId(c.id)}/pages/${encodeId(page)}`;
  const p = String(page).padStart(3, '0');
  return `${BASE}/assets/pages/${encodeId(template)}/p${encodeId(p)}.jpg`;
}
