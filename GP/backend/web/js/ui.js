// Small DOM + formatting helpers shared by the views.
import { BASE } from './api.js';

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function esc(s) {
  return String(s === undefined || s === null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

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

export function openModal(title, bodyHtml) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = bodyHtml;
  $('#modal').classList.add('on');
}
export function closeModal() { $('#modal').classList.remove('on'); }

export function fmt(n) {
  if (n === null || n === undefined || n === '') return '';
  const num = Number(n);
  return isNaN(num) ? String(n) : num.toLocaleString('en-US');
}

// evidence crop -> served URL under /assets/evidence/<case-family-dir>/<file>
export function evidenceUrl(template, crop) {
  if (!crop) return null;
  // crops are named like "<template>_pNNN_...png" and live in evidence/<dir>/
  const dir = template;
  return `${BASE}/assets/evidence/${dir}/${crop}`;
}

export function pageUrl(template, page, c) {
  // A claim read from scans serves its own pages (30 Sep 2026); the demo cases' are static assets.
  if (c && c.pageImages) return `${BASE}/api/cases/${encodeURIComponent(c.id)}/pages/${page}`;
  const p = String(page).padStart(3, '0');
  return `${BASE}/assets/pages/${template}/p${p}.jpg`;
}
