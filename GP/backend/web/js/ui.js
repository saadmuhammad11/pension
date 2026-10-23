// Small DOM + formatting helpers shared by the views. The pure parts live in pure.js so they
// can be tested without a browser (GP/backend/tests/js).
import { BASE } from './api.js';
import { escapeHtml, encodeId, formatNumber, formatRupees, itemHeading } from './pure.js';
export { itemHeading };

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
 * A page or a crop, with the tools the pension side gives the same picture (23 Oct 2026):
 * turn it left or right, and switch between fitting the pane and actual size. Until now this
 * module opened the image and nothing else, and scans arrive as they were fed -- a landscape
 * table, a CNIC copied sideways, a form upside down -- so a page the officer could not read
 * was a page the officer could not check. Turning is for their eyes: nothing in the case
 * file changes, and the next open starts straight again.
 *
 * A CSS rotation does not change the space an element takes up, so a page turned on its side
 * spills out of the pane. The frame is sized to the TURNED shape and the image centred inside
 * it, which is what the pension viewer does (portals components/PagePreview.tsx).
 */
export function openImageModal(title, src, alt = 'Page') {
  openModal(title, `<div class="imgview">
      <div class="row imgview-tools">
        <button type="button" class="btn small" data-tool="left" title="Rotate left (L)">Rotate left</button>
        <button type="button" class="btn small" data-tool="right" title="Rotate right (R)">Rotate right</button>
        <button type="button" class="btn small" data-tool="zoom">Actual size</button>
        <a class="btn small" href="${esc(src)}" target="_blank" rel="noreferrer">Open full page &#8599;</a>
      </div>
      <div class="imgview-pane"><div class="imgview-frame">
        <img class="imgview-img" src="${esc(src)}" alt="${esc(alt)}">
      </div></div>
      <p class="imgview-error small" role="alert" hidden>This page could not be loaded.</p>
    </div>`);
  const modal = $('#modal');
  const pane = $('.imgview-pane'), frame = $('.imgview-frame'), img = $('.imgview-img');
  const zoomBtn = $('[data-tool="zoom"]');
  let turn = 0, zoom = false, nat = null;

  function layout() {
    if (!nat || !pane.clientWidth) return;
    const sideways = turn % 180 === 90;
    const room = pane.clientWidth - 32;
    const scale = zoom ? 1 : room / (sideways ? nat.h : nat.w);
    const w = nat.w * scale, h = nat.h * scale;
    frame.style.width = (sideways ? h : w) + 'px';
    frame.style.height = (sideways ? w : h) + 'px';
    img.style.width = w + 'px';
    img.style.height = h + 'px';
    img.style.transform = `translate(-50%, -50%) rotate(${turn}deg)`;
    img.style.visibility = 'visible';
    img.alt = alt + (turn ? `, turned ${turn}\u00b0` : '');
  }
  const rotate = (by) => { turn = (turn + by + 360) % 360; layout(); };

  img.onload = () => { nat = { w: img.naturalWidth, h: img.naturalHeight }; layout(); };
  img.onerror = () => { $('.imgview-error').hidden = false; frame.style.height = '0px'; };
  $('[data-tool="left"]').onclick = () => rotate(-90);
  $('[data-tool="right"]').onclick = () => rotate(90);
  zoomBtn.onclick = () => {
    zoom = !zoom;
    zoomBtn.textContent = zoom ? 'Fit to width' : 'Actual size';
    layout();
  };
  // L and R turn the page, as they do on the pension side. Escape is the modal's own, and
  // a key pressed in a field is the field's -- these are not shortcuts worth stealing a
  // keystroke for.
  const onKey = (e) => {
    if (!modal.classList.contains('on')) { document.removeEventListener('keydown', onKey); return; }
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
    if (e.key === 'r' || e.key === 'R') rotate(90);
    else if (e.key === 'l' || e.key === 'L') rotate(-90);
  };
  document.addEventListener('keydown', onKey);
  // The pane's width decides the fitted size, so it is measured again when the window changes.
  const ro = new ResizeObserver(() => { if (modal.classList.contains('on')) layout(); else ro.disconnect(); });
  ro.observe(pane);
  if (img.complete && img.naturalWidth) img.onload();
}

/**
 * The note a decision carries, asked for where the decision is made (23 Oct 2026): a panel
 * under the item's own buttons, holding the box, Record and Cancel, in place of window.prompt().
 *
 * prompt() was wrong here three times over. It is a window this page does not own, so it
 * carries none of this screen's wording and cannot show a validation message of its own; it
 * blocks the whole tab while it stands; and a browser that declines to draw it -- which one
 * inside a frame may -- answers null, which is exactly what Cancel answers, so an officer's
 * verification was dropped without a word said. The pension side asks for its reason inline
 * and this now matches it.
 *
 * `submit` is awaited. If it throws, the message is shown in the panel and what was typed is
 * kept, so the officer can correct and send again. Cancel records nothing (F1).
 */
export function inlineNote(anchor, { label, placeholder = '', min = 0, confirmLabel = 'Record', submit }) {
  const host = anchor.closest('.item-body') || anchor.parentElement;
  host.querySelectorAll('.note-panel').forEach(old => old.remove());
  const panel = h(`<div class="note-panel">
    <div class="note-label">${esc(label)}</div>
    <textarea class="note-box" rows="2" placeholder="${esc(placeholder)}"></textarea>
    <div class="note-error small" role="alert" hidden></div>
    <div class="row">
      <button type="button" class="btn small primary note-go">${esc(confirmLabel)}</button>
      <button type="button" class="btn small note-cancel">Cancel</button>
    </div>
  </div>`);
  host.appendChild(panel);
  const box = panel.querySelector('.note-box');
  const err = panel.querySelector('.note-error');
  const go = panel.querySelector('.note-go');
  const close = () => { if (panel.isConnected) panel.remove(); if (document.contains(anchor)) anchor.focus(); };
  const fail = (msg) => { err.textContent = msg; err.hidden = false; box.focus(); };
  const send = () => {
    const text = box.value.trim();
    if (text.length < min) return fail(`A reason of at least ${min} characters is required.`);
    err.hidden = true;
    return busy(go, async () => {
      try { await submit(text); close(); }
      catch (e) { fail(e.message || String(e)); }
    });
  };
  go.onclick = send;
  panel.querySelector('.note-cancel').onclick = close;
  // Escape closes the panel, not the case; Ctrl/Cmd+Enter sends it without reaching for the mouse.
  panel.onkeydown = (e) => {
    e.stopPropagation();
    if (e.key === 'Escape') { close(); }
    else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); }
  };
  // The panel sits inside the item; a click in it must not reach the head and fold the item away.
  panel.onclick = (e) => e.stopPropagation();
  box.focus();
  return panel;
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
