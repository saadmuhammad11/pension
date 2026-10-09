// GP Fund Pre-Audit — SPA controller. Buildless ES module.
import { api, BASE, tellPortal } from './api.js';
import { $, $$, esc, h, badge, toast, openModal, closeModal, trapModalFocus, confirmDialog, busy, fmt, rupees, evidenceUrl, pageUrl, itemHeading } from './ui.js';
import { noteFromPrompt, throttle, sequence, disposalConfirmText } from './pure.js';

// Embedded in the AG Punjab portal (28 Sep 2026): `?embed=1&officer=ao` in the address hides the
// header and the intake, fixes the officer the portal signed in, and shows one case's screens.
const params = new URLSearchParams(location.search);
const EMBED = params.get('embed') === '1';
if (EMBED) {
  document.documentElement.classList.add('embed');
  // The portal sizes its frame to this document, so the officer scrolls one page, not two.
  const tell = () => { try { parent.postMessage({ gpfHeight: document.documentElement.scrollHeight }, location.origin); } catch (e) { /* not framed */ } };
  new ResizeObserver(tell).observe(document.documentElement);
  window.addEventListener('load', tell);
  // The portal's idle timer hears nothing from inside this frame, so an officer working here for
  // half an hour was signed out under their hands (frontend review F9). Pointer and key activity
  // is reported to the portal, at most once every ten seconds.
  const active = throttle(() => tellPortal({ gpfActivity: 1 }), 10_000);
  for (const ev of ['pointerdown', 'pointermove', 'keydown', 'wheel']) {
    window.addEventListener(ev, active, { passive: true });
  }
}

// Renders are sequenced (F13): a slow earlier render must not write over a newer one.
const ROUTE = sequence();

const state = {
  officer: (EMBED && params.get('officer')) || localStorage.getItem('gpf.officer') || 'ao',
  officers: [],
  tab: 'exam',
  lastDiff: null,
};

// ── bootstrap ─────────────────────────────────────────────────────────────────
async function boot() {
  state.officers = await api.officers();
  // Opened through the pension portal, the officer is the signed-in account's (5 Oct 2026): the
  // server records every action under it whatever this page sends, so the page shows it and
  // offers no other.
  let fixed = null;
  try { fixed = (await api.acting()).officer; } catch (e) { /* the module on its own */ }
  if (fixed) state.officer = fixed;
  const sel = $('#officer');
  sel.innerHTML = state.officers.map(o =>
    `<option value="${esc(o.id)}">${esc(o.desig)} · ${esc(o.grade)}</option>`).join('');
  sel.value = state.officer;
  setOfficerInitials();
  if (EMBED || fixed) sel.disabled = true;
  sel.onchange = () => {
    state.officer = sel.value; localStorage.setItem('gpf.officer', state.officer);
    setOfficerInitials(); route();
  };
  $('#modal-close').onclick = closeModal;
  $('#modal').onclick = e => { if (e.target.id === 'modal') closeModal(); };
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); else trapModalFocus(e); });
  window.addEventListener('hashchange', route);
  if (!location.hash) location.hash = '#/cases';
  route();
}

// boot() used to have no catch: a failed first request left "Loading…" on screen for good (F13).
async function start() {
  try {
    await boot();
  } catch (e) {
    const app = $('#app');
    app.innerHTML = `<div class="panel"><h2>The GP Fund module could not load</h2>
      <p class="muted">${esc(e.message)}</p><button class="btn primary" id="boot-retry">Retry</button></div>`;
    $('#boot-retry').onclick = () => { app.innerHTML = '<div class="loading">Loading…</div>'; start(); };
  }
}

// The header avatar. The select names a designation; who is sitting in it matters when the
// register is signed, so the name travels with the role rather than being buried in the API.
function setOfficerInitials() {
  const who = state.officers.find(o => o.id === state.officer);
  $('#officer-initials').textContent = who
    ? who.name.split(/\s+/).map(w => w[0]).slice(0, 2).join('') : '';
  $('#officer-initials').title = who ? `${who.name} — ${who.desig}` : '';
}

function setNav(name) {
  $$('#mainnav a').forEach(a => a.classList.toggle('on', a.dataset.nav === name));
}

async function route() {
  const seq = ROUTE.next();
  const hash = location.hash.slice(2) || 'cases';
  const [head, arg] = hash.split('/');
  const app = $('#app');
  app.innerHTML = '<div class="loading">Loading…</div>';
  try {
    if (EMBED && head !== 'case') { app.innerHTML = '<div class="panel"><p class="muted">Open a GP Fund case from the portal.</p></div>'; return; }
    if (head === 'cases') { setNav('cases'); await renderCases(app, seq); }
    else if (head === 'case') { setNav('cases'); await renderCase(app, arg, seq); }
    else if (head === 'doa') { setNav('doa'); await renderDoa(app, seq); }
    else if (head === 'rules') { setNav('rules'); await renderRules(app, seq); }
    else { location.hash = '#/cases'; }
  } catch (e) {
    if (ROUTE.isStale(seq)) return;
    app.innerHTML = `<div class="panel"><h2>Something went wrong</h2><p class="muted">${esc(e.message)}</p>
      <button class="btn" id="route-retry">Retry</button></div>`;
    $('#route-retry').onclick = route;
  }
}

// ── cases list + intake ───────────────────────────────────────────────────────
async function renderCases(app, seq = ROUTE.current) {
  const [templates, open] = await Promise.all([api.templates(), api.listCases()]);
  if (ROUTE.isStale(seq)) return;
  app.innerHTML = `
    <div class="panel">
      <div class="spread"><h2>Intake — open a case</h2>
        <label class="chk"><input type="checkbox" id="nosap"> Treat as received without its SAP pages</label></div>
      <p class="muted small">The corpus of eight cases supplied by the office. Opening a case runs initial processing.</p>
      <div class="cards" id="tmpl-cards"></div>
    </div>
    <div class="panel">
      <h2>Open from scanned pages</h2>
      <p class="muted small">Reads the scans through the pipeline (stages 1–5) into a facts object.
        Needs the vision model on the DGX Spark (<code>GPF_VLLM_URL</code>); until then this returns a clear notice.</p>
      <div class="row">
        <div class="field" style="min-width:200px"><label>Case type</label>
          <select id="scan-kind">
            <option value="refundable">Refundable advance</option>
            <option value="nonrefundable">Non-refundable advance</option>
            <option value="final">Final payment</option>
            <option value="death">Final payment — death</option>
            <option value="dismissal">Final payment — dismissal</option>
            <option value="missing_credits">Missing credits</option>
            <option value="balance_transfer">Balance transfer</option>
          </select></div>
        <div class="field" style="min-width:160px"><label>Scanned pages</label><input type="file" id="scan-files" multiple></div>
      </div>
      <button class="btn primary" id="scan-go">Read and open</button>
      <div class="reading" id="reading" hidden>
        <div class="reading-head">
          <span class="spinner" aria-hidden="true"></span>
          <div style="flex:1">
            <div class="reading-title" id="rd-title">Uploading the pages…</div>
            <div class="reading-sub muted small" id="rd-sub">Nothing has been read yet.</div>
          </div>
          <div class="reading-clock mono" id="rd-clock">0:00</div>
        </div>
        <div class="bar" role="progressbar" aria-live="polite" id="rd-bar-wrap"
             aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
          <div class="bar-fill" id="rd-bar"></div>
        </div>
        <ol class="stages" id="rd-stages">
          <li data-stage="ingest">Pages received</li>
          <li data-stage="classify">Identifying documents</li>
          <li data-stage="extract">Reading fields</li>
          <li data-stage="assemble">Assembling the case</li>
        </ol>
      </div>
    </div>
    <div class="panel">
      <h2>Cases in progress</h2>
      <div id="open-cases"></div>
    </div>`;
  $('#tmpl-cards').innerHTML = templates.map(t => `
    <div class="card">
      <div class="kind">${esc(t.family || '')}</div>
      <h3>${esc(t.label)}</h3>
      <p class="muted small">${esc(t.subject || '')}</p>
      <p class="small">Personnel no. <span class="mono">${esc(t.personnelNo)}</span> · ${t.pages || '?'} pages
        · ${t.hasSap ? 'SAP pages present' : 'no SAP pages'}</p>
      <button class="btn primary small" data-open="${esc(t.key)}">Open case</button>
    </div>`).join('');
  $$('#tmpl-cards [data-open]').forEach(b => b.onclick = () => busy(b, async () => {
    try {
      const r = await api.createCase(b.dataset.open, $('#nosap').checked, state.officer);
      toast('Case opened, initial processing done');
      location.hash = '#/case/' + encodeURIComponent(r.id);
    } catch (e) { toast(e.message, true); }
  }));
  $('#scan-go').onclick = async () => {
    const files = $('#scan-files').files;
    if (!files.length) return toast('Choose the scanned pages first', true);
    const rd = readingProgress(files.length);
    try {
      const r = await api.fromScans($('#scan-kind').value, 'unknown', state.officer, files,
                                    rd.update, rd.uploaded);
      rd.finish();
      toast('Scans read, case opened');
      location.hash = '#/case/' + encodeURIComponent(r.id);
    } catch (e) { rd.fail(); toast(e.message, true); }
  };
  const oc = $('#open-cases');
  if (!open.length) { oc.innerHTML = '<p class="muted">No cases open yet.</p>'; return; }
  oc.innerHTML = `<div class="table-wrap"><table><thead><tr>
    <th>Case</th><th>Subject</th><th>Ver.</th><th>Hard</th><th>Verify</th><th>SAP</th><th>Open obs.</th><th>State</th><th></th>
    </tr></thead><tbody>${open.map(c => `<tr>
      <td><b>${esc(c.label)}</b><div class="mono small muted">${esc(c.id)}</div></td>
      <td class="small">${esc(c.subject || '')}</td><td>${esc(c.version)}</td>
      <td>${c.hard ? badge('hard', c.hard) : '0'}</td>
      <td>${c.conf ? badge('conf', c.conf) : '0'}</td>
      <td>${c.sap ? badge('sap', c.sap) : '0'}</td>
      <td>${esc(c.open)}</td>
      <td>${c.issued ? '<span class="pill">issued</span>' : (c.mayAdvance ? badge('ok', 'may advance') : badge('hard', 'blocked'))}</td>
      <td><a class="btn small" href="#/case/${esc(c.id)}">Open</a></td>
    </tr>`).join('')}</tbody></table></div>`;
}

// ── reading progress ──────────────────────────────────────────────────────────
// Two vision-model calls per page means a real file takes a minute or more, and the button
// used to sit there through all of it with nothing on screen. The bar is driven by pages
// actually finished, so it is a measurement rather than a guess; one page can still take
// twenty seconds, which is why the spinner, the stage list and the clock keep moving between
// ticks. The officer should be able to tell a working model from a hung one without a log.
function readingProgress(pageCount) {
  const box = $('#reading'), btn = $('#scan-go');
  const bar = $('#rd-bar'), wrap = $('#rd-bar-wrap');
  const title = $('#rd-title'), sub = $('#rd-sub'), clock = $('#rd-clock');
  const started = Date.now();
  const STAGES = ['ingest', 'classify', 'extract', 'assemble'];

  const setBar = pct => {
    const v = Math.max(0, Math.min(100, pct));
    bar.style.width = v + '%';
    wrap.setAttribute('aria-valuenow', Math.round(v));
  };
  // The list describes the run, not the page under the model. Each page cycles classify ->
  // extract, so following the raw stage would walk the ticks backwards every page — and a
  // checklist that un-ticks itself reads as "something was undone". A high-water mark keeps
  // it monotonic; the within-page detail lives in the line above, which is free to move.
  let reached = 0;
  const setStage = stage => {
    const at = STAGES.indexOf(stage === 'page-done' ? 'extract' : stage);
    if (at > reached) reached = at;
    $$('#rd-stages li').forEach((li, i) => {
      li.className = i < reached ? 'done' : i === reached ? 'now' : '';
    });
  };

  box.hidden = false;
  box.className = 'reading';
  btn.disabled = true;
  btn.textContent = 'Reading…';
  setStage('ingest');
  // Before the server has spoken the only honest statement is "uploading", so the bar shows
  // a small fixed amount rather than crawling — it must never imply reading has begun.
  setBar(4);

  const tick = setInterval(() => {
    const s = Math.floor((Date.now() - started) / 1000);
    clock.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }, 1000);

  return {
    uploaded() {
      title.textContent = `Reading ${pageCount} page${pageCount === 1 ? '' : 's'}`;
      sub.textContent = 'The vision model is working through the scans on the DGX Spark.';
      setBar(8);
    },
    update(job) {
      if (job.total) {
        // Pages finished is the real fraction. The last 8% belongs to the assemble step, so
        // the bar does not sit at 100% while there is still work to do.
        setBar(8 + (job.done / job.total) * 84 + (job.stage === 'assemble' ? 8 : 0));
      }
      setStage(job.stage);
      if (job.message) sub.textContent = job.message;
      if (job.stage === 'assemble') title.textContent = 'Assembling the case';
    },
    finish() {
      clearInterval(tick);
      setBar(100);
      $$('#rd-stages li').forEach(li => li.className = 'done');
      box.className = 'reading ok';
      title.textContent = 'Read — opening the case';
    },
    fail() {
      clearInterval(tick);
      box.className = 'reading bad';
      title.textContent = 'Reading stopped';
      btn.disabled = false;
      btn.textContent = 'Read and open';
    },
  };
}

// ── single case ───────────────────────────────────────────────────────────────
async function renderCase(app, id, seq = ROUTE.current) {
  const c = await api.getCase(id);
  if (ROUTE.isStale(seq)) return;
  const p = c.position;
  app.innerHTML = `
    <div class="panel">
      <div class="spread">
        <div>
          <div class="kind muted small">${esc(c.meta.family || '')} · ${esc(c.meta.kind || '')}</div>
          <h2 style="margin-bottom:2px">${esc(c.meta.label)}</h2>
          <div class="muted small">${esc(c.meta.subject || '')} · ${esc(c.meta.dept || '')}</div>
          <div class="muted small">Personnel no. <span class="mono">${esc(c.meta.personnelNo)}</span>
            · ${esc(c.meta.gazetted)} · version ${c.version}
            ${c.withoutSap ? '· <span class="pill">received without SAP</span>' : ''}
            ${c.issued ? '· <span class="pill">'+esc(c.caseDisp||'issued')+'</span>' : ''}</div>
        </div>
        ${EMBED ? '' : '<a class="btn small" href="#/cases">← All cases</a>'}
      </div>
      <div class="statstrip" style="margin-top:12px">
        ${stat('hard', p.hard, 'Hard stops')}${stat('adv', p.adv, 'Observations')}
        ${stat('conf', p.conf, 'Verify')}${stat('sap', p.sap, 'SAP items')}
        ${stat('ok', c.lists.ok.length, 'Satisfied')}
      </div>
    </div>
    <div class="subnav" id="subnav">
      ${tabBtn('overview', 'Overview')}${tabBtn('sap', 'SAP extracts')}
      ${tabBtn('exam', 'Examination')}${tabBtn('disposal', 'Disposal')}${tabBtn('issue', 'Issue pack')}
    </div>
    <div id="tabc"></div>`;
  $$('#subnav button').forEach(b => b.onclick = () => { state.tab = b.dataset.tab; renderTab(id, c); });
  renderTab(id, c);
}

const stat = (cls, n, label) =>
  `<div class="stat ${esc(cls)}${Number(n) ? '' : ' zero'}"><b>${esc(n)}</b><span>${esc(label)}</span></div>`;
const tabBtn = (t, label) => `<button data-tab="${esc(t)}" class="${state.tab === t ? 'on' : ''}">${esc(label)}</button>`;

function renderTab(id, c) {
  $$('#subnav button').forEach(b => b.classList.toggle('on', b.dataset.tab === state.tab));
  const el = $('#tabc');
  if (state.tab === 'overview') el.innerHTML = viewOverview(c);
  else if (state.tab === 'sap') { el.innerHTML = viewSap(c); wireSap(id, c); }
  else if (state.tab === 'exam') { el.innerHTML = viewExam(c); wireExam(id, c); }
  else if (state.tab === 'disposal') { el.innerHTML = viewDisposal(c); wireDisposal(id, c); }
  else if (state.tab === 'issue') { renderIssue(id, el); }
}

// ── overview ──────────────────────────────────────────────────────────────────
function viewOverview(c) {
  const rec = (c.record || []).map(r => `<tr>
    <td><b>${esc(r[0])}</b></td><td>${esc(r[1])}</td><td class="small muted">${esc(r[2])}</td>
    <td class="small num">${r[3] != null ? (r[3] * 100).toFixed(0) + '%' : ''}</td></tr>`).join('');
  return `
    <div class="panel">
      <h2>What the reading stage lifted</h2>
      ${c.meta.note ? `<p class="muted">${esc(c.meta.note)}</p>` : ''}
      <div class="table-wrap"><table><thead><tr><th>Field</th><th>Value</th><th>Source</th><th class="num">Conf.</th></tr></thead>
        <tbody>${rec || '<tr><td colspan=4 class="muted">No reading record.</td></tr>'}</tbody></table></div>
    </div>`;
}

// ── SAP tab ───────────────────────────────────────────────────────────────────
function viewSap(c) {
  const s = c.sap;
  if (s.present) {
    const ps = s.payslip || {}, rc = s.recalc || {};
    return `<div class="panel">
      <div class="spread"><h2>SAP extracts</h2>${badge('ok', 'present · ' + esc(s.source))}</div>
      <div class="row" style="margin-top:10px">
        <div style="flex:1;min-width:260px"><h4>Pay slip</h4>
          <table><tbody>
            <tr><td>Personnel no.</td><td class="mono">${esc(ps.persNo)}</td></tr>
            <tr><td>Name</td><td>${esc(ps.name)}</td></tr>
            <tr><td>Month</td><td>${esc(ps.month)}</td></tr>
            <tr><td>GPF balance</td><td>${rupees(ps.gpfBalance)}</td></tr>
            <tr><td>Loan balance</td><td>${rupees(ps.loanBalance)}</td></tr>
            <tr><td>Basic pay</td><td>${rupees(ps.basicPay)}</td></tr>
          </tbody></table></div>
        <div style="flex:1;min-width:260px"><h4>Re-calculation report</h4>
          <table><tbody>
            <tr><td>Report date</td><td>${esc(rc.reportDate || '')}</td></tr>
            <tr><td>Rows</td><td>${rc.rows || 0}</td></tr>
            <tr><td>Last closing</td><td>${rupees(rc.lastClosing)}</td></tr>
          </tbody></table></div>
      </div>
      <hr class="hr"><p class="muted small">A fresher extract can replace this. Uploading re-evaluates the case.</p>
      <div id="sap-upload"></div>
    </div>`;
  }
  return `<div class="panel">
    <h2>SAP extracts</h2>
    <p class="muted">No SAP pay slip or re-calculation report is in the case. Pull them from SAP against
      personnel no. <span class="mono">${esc(s.personnelNo)}</span> and upload here (R1). This is a section action, not a department defect.</p>
    <div id="sap-upload"></div>
  </div>`;
}

function wireSap(id, c) {
  const box = $('#sap-upload');
  box.innerHTML = `
    <div class="field"><label>Paste the SAP text export (pay slip + re-calculation report)</label>
      <textarea id="sap-text" placeholder="SAP EXTRACT: PAY SLIP&#10;Personnel No: ..."></textarea></div>
    <div class="row">
      <button class="btn" id="sap-sample">Use the extract saved for this prototype</button>
      <button class="btn primary" id="sap-submit">Upload and re-check</button>
    </div>`;
  $('#sap-sample').onclick = async () => {
    try {
      const res = await fetch(BASE + '/assets/sap-samples/SAP_EXTRACT_' + c.meta.personnelNo + '.txt');
      if (!res.ok) return toast('No saved sample for this case', true);
      $('#sap-text').value = await res.text();
    } catch { toast('Could not load sample', true); }
  };
  $('#sap-submit').onclick = () => busy($('#sap-submit'), async () => {
    const text = $('#sap-text').value.trim();
    if (!text) return toast('Paste the extract first', true);
    try {
      const r = await api.sapText(id, 'extract.txt', text, state.officer);
      state.lastDiff = r.diff; state.tab = 'exam';
      toast('SAP extract accepted, case re-checked');
      refresh(id);
    } catch (e) { toast(e.message, true); }
  });
}

// ── examination ───────────────────────────────────────────────────────────────
const GROUPS = [
  ['hard', 'Hard stops — go on the rejection form'],
  ['adv', 'Observations — advisory memorandum'],
  ['conf', 'Verification tasks — the officer decides'],
  ['sap', 'SAP items — the section pulls these'],
  ['ok', 'Satisfied checks'],
];

function viewExam(c) {
  let html = '';
  const d = state.lastDiff;
  state.lastDiff = null;  // banner shows once, then clears
  if (d && (d.resolved.length || d.raised.length || d.changed.length)) {
    html += `<div class="banner good"><b>Case re-checked.</b>
      ${d.resolved.length ? `${d.resolved.length} resolved` : ''}${d.raised.length ? ` · ${d.raised.length} newly raised` : ''}${d.changed.length ? ` · ${d.changed.length} changed` : ''}.
      ${d.resolved.length ? '<ul>' + d.resolved.map(r => `<li>${esc(r.title || r.id)} — now ${esc(r.status)}</li>`).join('') + '</ul>' : ''}</div>`;
  }
  for (const [key, label] of GROUPS) {
    const items = c.lists[key];
    if (!items.length) continue;
    const collapsed = key === 'ok';
    html += `<div class="panel"><h2>${label} <span class="muted">(${items.length})</span></h2>
      ${items.map(r => itemHtml(c, r, collapsed)).join('')}</div>`;
  }
  return html || '<div class="panel"><p class="muted">No results.</p></div>';
}

function itemHtml(c, r, collapsed) {
  const disp = r.disposition;
  const ev = (r.evidence || []).filter(e => e && (e.url || e.crop || e.page));
  const evHtml = ev.length ? `<div class="evgrid">${ev.map(e => {
    const url = e.url ? `${BASE}/${e.url}` : e.crop ? evidenceUrl(c.template, e.crop) : pageUrl(c.template, e.page, c);
    return `<figure><img loading="lazy" src="${esc(url)}" data-zoom="${esc(url)}"><figcaption>${esc(e.label ? (e.reference || !e.page || /page/i.test(e.label) ? e.label : e.label + ' · page ' + e.page) : ('page ' + e.page))}</figcaption></figure>`;
  }).join('')}</div>` : '';
  const calc = r.calc ? `<pre class="small mono" style="white-space:pre-wrap;background:var(--na-bg);padding:10px;border-radius:8px">${esc(JSON.stringify(r.calc, null, 1))}</pre>` : '';
  // Specimens on file for the signing authority, beside the signature as read (C1, 9 Oct 2026). The
  // comparison is the officer's; the images come from the shared master store, never cached.
  const specs = Array.isArray(r.specimens) ? r.specimens.filter(sp => sp && sp.url) : [];
  const specHtml = specs.length ? `<div class="small muted" style="margin-top:8px">Specimen on file${r.specimen_authority ? ` · ${esc(r.specimen_authority.officer || r.specimen_authority.post)}, ${esc(r.specimen_authority.department)}${r.specimen_authority.provisional ? ' (provisional register)' : ''}` : ''}</div>
    <div class="evgrid">${specs.map(sp => { const u = `${BASE}/${sp.url}`; return `<figure><img loading="lazy" src="${esc(u)}" data-zoom="${esc(u)}" alt="Specimen signature"><figcaption>Specimen</figcaption></figure>`; }).join('')}</div>` : '';
  const heading = itemHeading(r);
  return `<div class="item ${collapsed ? '' : ''}" data-id="${esc(r.id)}">
    <div class="item-head">
      ${badge(r.status)}
      <span class="item-title">${esc(heading.title)}${heading.sub ? `<span class="item-doc">${esc(heading.sub)}</span>` : ''}</span>
      ${r.code ? `<span class="pill">${esc(r.code)}</span>` : ''}
      <span class="item-id">${esc(r.id)}</span>
      ${disp ? `<span class="disp-tag">${esc(disp.action)}${disp.cured ? ' · cured' : ''}</span>` : ''}
    </div>
    <div class="item-body">
      <div class="finding">${esc(r.finding || '')}</div>
      ${r.remedy ? `<div class="remedy small"><b>Remedy:</b> ${esc(r.remedy)}</div>` : ''}
      ${r.ref ? `<div class="small muted" style="margin-top:6px">Reference: ${esc(r.ref)}</div>` : ''}
      ${calc}${evHtml}${specHtml}
      <div class="item-actions">${actionsHtml(r)}</div>
    </div>
  </div>`;
}

function actionsHtml(r) {
  const btns = [];
  const cure = r.cure || {};
  if (r.status === 'sap' || cure.kind === 'sap') {
    btns.push(`<button class="btn small" data-act="gosap">Go to SAP extracts</button>`);
  }
  if (cure.kind === 'verify') {
    btns.push(`<button class="btn small primary" data-act="verify-ok">Record verified</button>`);
    btns.push(`<button class="btn small" data-act="verify-no">Did not verify</button>`);
  }
  if (cure.kind === 'doc') {
    btns.push(`<button class="btn small primary" data-act="cure-doc">Upload document against this</button>`);
  }
  if (cure.kind === 'qr') {
    btns.push(`<button class="btn small primary" data-act="cure-qr">Upload clearer copy / missing side</button>`);
  }
  if (r.status === 'hard' || r.status === 'adv') {
    btns.push(`<button class="btn small" data-act="disp-uphold">Uphold</button>`);
    btns.push(`<button class="btn small" data-act="disp-waive">Waive…</button>`);
    btns.push(`<button class="btn small" data-act="disp-refer">Refer upward</button>`);
  }
  return btns.join('') || '<span class="muted small">Recorded.</span>';
}

function wireExam(id, c) {
  $$('#tabc .item-head').forEach(head => head.onclick = () => head.parentElement.classList.toggle('open'));
  $$('#tabc [data-zoom]').forEach(img => {
    // An evidence image that fails to load drops out of the grid. Bound here, not inline: the
    // portal's CSP allows no inline handlers under /gpf/ (F13).
    img.addEventListener('error', () => { const f = img.closest('figure'); if (f) f.remove(); });
    img.onclick = e => { e.stopPropagation(); openModal('Evidence', `<img src="${esc(img.dataset.zoom)}" alt="Evidence">`); };
  });
  $$('#tabc .item').forEach(item => {
    const rid = item.dataset.id;
    const r = findResult(c, rid);
    item.querySelectorAll('[data-act]').forEach(btn => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        await handleAction(id, c, r, btn.dataset.act, btn);
      };
    });
  });
}

function findResult(c, id) {
  for (const k of ['hard', 'adv', 'conf', 'sap', 'ok']) {
    const r = c.lists[k].find(x => x.id === id);
    if (r) return r;
  }
  return null;
}

async function refresh(id, diff) {
  if (diff) state.lastDiff = diff;
  try {
    await renderCase($('#app'), id);
  } catch (e) {
    // The POST succeeded; only the screen is stale. Say so, rather than "something went wrong".
    toast('The action was recorded, but the screen could not be refreshed: ' + e.message + '. Reload the case.', true);
  }
}

async function handleAction(id, c, r, act, btn) {
  try {
    if (act === 'gosap') { state.tab = 'sap'; refresh(id); return; }
    if (act === 'verify-ok' || act === 'verify-no') {
      const ok = act === 'verify-ok';
      // Cancel on the note aborts and records nothing (F1): prompt() answers null for Cancel,
      // and `|| ''` used to turn that into an empty note and carry on.
      const note = noteFromPrompt(prompt(ok ? 'Note (what did you verify?)' : 'Note (why did it not verify?)', ''));
      if (note.cancelled) return;
      return busy(btn, async () => {
        const res = await api.verify(id, r.cure.vid, ok, note.text, state.officer);
        toast('Verification recorded'); await refresh(id, res.diff);
      });
    }
    if (act === 'disp-uphold' || act === 'disp-refer') {
      // Written grounds on every disposition (G1, 7 Oct 2026): the next desk reads why.
      const what = act === 'disp-uphold' ? 'uphold' : 'refer';
      const ground = noteFromPrompt(prompt(`Grounds for ${what === 'uphold' ? 'upholding' : 'referring'} this observation (at least 15 characters)`, ''));
      if (ground.cancelled) return;
      if (ground.text.length < 15) { toast('Written grounds of at least 15 characters are required.', true); return; }
      return busy(btn, async () => {
        await api.setDisposition(id, r.id, what, ground.text, '', state.officer);
        toast(what === 'uphold' ? 'Upheld' : 'Referred upward'); await refresh(id);
      });
    }
    if (act === 'disp-waive') return waiveModal(id, r);
    if (act === 'cure-doc') return cureDocModal(id, r);
    if (act === 'cure-qr') return cureQrModal(id, r);
  } catch (e) { toast(e.message, true); }
}

function waiveModal(id, r) {
  openModal('Waive observation — ' + (r.code || r.id), `
    <p class="small muted">A waiver needs written grounds (at least 15 characters) and the authority relied on (recorded in the office copy). A hard stop is waived by the DAG alone.</p>
    <div class="field"><label>Ground for the waiver</label><input type="text" id="w-ground"></div>
    <div class="field"><label>Authority relied on</label><input type="text" id="w-auth"></div>
    <button class="btn primary" id="w-go">Waive</button>`);
  $('#w-go').onclick = () => busy($('#w-go'), async () => {
    try {
      await api.setDisposition(id, r.id, 'waive', $('#w-ground').value, $('#w-auth').value, state.officer);
      closeModal(); toast('Waived'); refresh(id);
    } catch (e) { toast(e.message, true); }
  });
}

function cureDocModal(id, r) {
  const fields = (r.cure.fields || []);
  const fh = fields.map(f => {
    if (f.type === 'yesno') return fieldSelect(f, ['yes', 'no']);
    if (f.type === 'select') return fieldSelect(f, f.options || []);
    return `<div class="field"><label>${esc(f.label)}${f.expect ? ` <span class="muted small">(expected: ${esc(f.expect)})</span>` : ''}</label>
      <input type="${f.type === 'number' ? 'number' : 'text'}" data-k="${esc(f.k)}"></div>`;
  }).join('');
  openModal('Upload document — ' + esc(r.cure.docType || r.title), `
    <p class="small muted">The document is read; below-threshold fields must be confirmed. (No vision model in this build — confirm the fields.)</p>
    ${fh}
    <div class="field"><label>Attach the file (optional)</label><input type="file" id="c-file"></div>
    <button class="btn primary" id="c-go">Confirm and re-check</button>`);
  $('#c-go').onclick = () => busy($('#c-go'), async () => {
    const values = {};
    $$('#modal-body [data-k]').forEach(inp => { values[inp.dataset.k] = inp.value; });
    const file = $('#c-file').files[0] || null;
    try {
      const res = await api.cure(id, r.id, values, state.officer, file);
      closeModal(); toast('Document applied, case re-checked'); refresh(id, res.diff);
    } catch (e) { toast(e.message, true); }
  });
}

function fieldSelect(f, opts) {
  return `<div class="field"><label>${esc(f.label)}${f.expect ? ` <span class="muted small">(expected: ${esc(f.expect)})</span>` : ''}</label>
    <select data-k="${esc(f.k)}">${opts.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('')}</select></div>`;
}

function cureQrModal(id, r) {
  openModal('QR code — ' + esc(r.title), `
    <p class="small muted">Upload a clearer copy or the missing card side. Confirm what the decoded code shows.</p>
    <div class="field"><label>Decoded payload (optional)</label><input type="text" data-k="payload"></div>
    <div class="chk field"><input type="checkbox" data-k="agrees" checked> The code agrees with the document</div>
    <div class="field"><label>Attach the image (optional)</label><input type="file" id="q-file"></div>
    <button class="btn primary" id="q-go">Apply</button>`);
  $('#q-go').onclick = () => busy($('#q-go'), async () => {
    const values = { payload: $('#modal-body [data-k="payload"]').value,
                     agrees: $('#modal-body [data-k="agrees"]').checked };
    const file = $('#q-file').files[0] || null;
    try {
      const res = await api.cure(id, r.id, values, state.officer, file);
      closeModal(); toast('QR checked, case re-checked'); refresh(id, res.diff);
    } catch (e) { toast(e.message, true); }
  });
}

// ── disposal ──────────────────────────────────────────────────────────────────
const DISPOSAL_LABEL = {
  return: 'Return to the department', pay: 'Pass for payment',
  part: 'Pass for part payment', refer: 'Refer to the DAG (Funds)', hold: 'Hold pending verification',
};

function viewDisposal(c) {
  const opts = c.disposalOptions.map(o => `
    <div class="item"><div class="item-head" style="cursor:default">
      <span class="item-title">${esc(DISPOSAL_LABEL[o.action] || o.action)}</span>
      ${o.allowed ? badge('ok', 'available') : `<span class="muted small">${esc(o.reason || 'not available')}</span>`}
      <button class="btn small primary" data-disp="${esc(o.action)}" ${o.allowed ? '' : 'disabled'}>Do this</button>
    </div></div>`).join('');
  return `<div class="panel">
    <h2>Disposal</h2>
    <p class="muted small">No case may be disposed while an observation is undisposed, a verification task or SAP item is open,
      or the re-calculation report does not reconcile. A second return needs the DAG (Funds).</p>
    ${opts}
    ${c.issued ? `<div class="banner good" style="margin-top:14px">This case has been ${esc(c.caseDisp || 'issued')} (returns so far: ${c.returns}).</div>` : ''}
  </div>`;
}

function wireDisposal(id, c) {
  $$('#tabc [data-disp]').forEach(b => b.onclick = async () => {
    const action = b.dataset.disp;
    const label = DISPOSAL_LABEL[action] || action;
    // A disposal is the case's outcome: it is confirmed first, naming the case and the outcome,
    // and sent once (F2). Cancel anywhere along the way records nothing (F1).
    const sure = await confirmDialog(label, disposalConfirmText(label, c.meta), label);
    if (!sure) return;
    let note = '';
    if (action === 'return' || action === 'refer' || action === 'hold') {
      const answer = noteFromPrompt(prompt('Note (optional)', ''));
      if (answer.cancelled) return;
      note = answer.text;
    }
    await busy(b, async () => {
      try {
        await api.dispose(id, action, note, state.officer);
        toast(label + ' — done');
        if (action === 'return' || action === 'pay' || action === 'part') { state.tab = 'issue'; }
        await refresh(id);
      } catch (e) { toast(e.message, true); }
    });
  });
}

// ── issue pack ────────────────────────────────────────────────────────────────
async function renderIssue(id, el) {
  el.innerHTML = '<div class="panel"><p class="muted">Building the pack…</p></div>';
  const pk = await api.issuePack(id);
  const list = (arr) => arr.length ? '<ul>' + arr.map(r =>
    `<li><b>${esc(r.code || r.ref || '')}</b> — ${esc(r.finding)}${r.remedy ? ` <span class="muted">(${esc(r.remedy)})</span>` : ''}</li>`).join('') + '</ul>'
    : '<p class="muted small">None.</p>';
  el.innerHTML = `
    <div class="panel">
      <div class="spread"><h2>Issue pack</h2><span class="muted small">generated ${esc(pk.generatedAt)} · version ${pk.version}</span></div>
      <p class="muted small">${esc(pk.case.label)} · ${esc(pk.case.subject)} · personnel no. ${esc(pk.case.personnelNo)}
        ${pk.caseDisposal ? '· <span class="pill">' + esc(pk.caseDisposal) + '</span>' : ''}</p>
      <h3>Claim rejection form (hard stops)</h3>${list(pk.rejectionForm)}
      <h3>Advisory memorandum</h3>${list(pk.advisoryMemo)}
      <h3>Waived / settled in office</h3>${list(pk.waivedAndSettled)}
      <hr class="hr">
      <h3>Employee Service Portal comment (single instance)</h3>
      <pre class="small mono" style="white-space:pre-wrap;background:var(--na-bg);padding:12px;border-radius:8px">${esc(pk.portalComment)}</pre>
      <h3>Documents on file</h3>
      <div class="table-wrap"><table><thead><tr><th>Kind</th><th>File</th><th>SHA-256</th><th>By</th></tr></thead>
      <tbody>${[...pk.sapExtracts, ...pk.uploadedDocuments].map(u => `<tr>
        <td>${esc(u.kind)}</td><td>${esc(u.name)}</td><td class="mono small">${esc((u.hash||'').slice(0,16))}…</td><td>${esc(u.by||'')}</td>
      </tr>`).join('') || '<tr><td colspan=4 class="muted">None.</td></tr>'}</tbody></table></div>
      <h3>Payment register entry (circular C(i))</h3>
      <pre class="small mono" style="white-space:pre-wrap;background:var(--na-bg);padding:12px;border-radius:8px">${esc(JSON.stringify(pk.paymentRegisterEntry, null, 1))}</pre>
    </div>`;
}

// ── DOA register ──────────────────────────────────────────────────────────────
async function renderDoa(app, seq = ROUTE.current) {
  const doa = await api.doa();
  if (ROUTE.isStale(seq)) return;
  const level = state.officers.find(o => o.id === state.officer)?.level || 1;
  app.innerHTML = `<div class="panel">
    <div class="spread"><h2>Delegation of Authority register</h2>
      ${badge(doa.status === 'final' ? 'ok' : 'conf', doa.status)}</div>
    <p class="muted small">${esc(doa.version || '')}</p>
    ${level >= 3 && doa.status !== 'final' ? '<button class="btn small" id="finalize">Mark register final</button>' : ''}
    <div id="auth-list" style="margin-top:14px"></div>
  </div>`;
  $('#auth-list').innerHTML = doa.authorities.map(a => `
    <div class="item open"><div class="item-head" style="cursor:default">
      <span class="item-title">${esc(a.authority)}</span><span class="pill">${esc(a.dept)}</span></div>
      <div class="item-body">
        <table><thead><tr><th>Post</th><th>Signs for</th><th>Powers</th><th>Specimen</th><th></th></tr></thead>
        <tbody>${a.signatories.map(g => `<tr>
          <td>${esc(g.post)}${g.name ? ' — ' + esc(g.name) : ''}</td>
          <td>${g.mayFor ? 'yes' : '—'}</td>
          <td class="small muted">${esc(g.powers || '')}</td>
          <td>${g.specimen ? badge('ok', 'on file') : '<span class="muted small">none</span>'}</td>
          <td>${level >= 2 ? `<button class="btn small" data-spec="${esc(g.id)}">Upload specimen</button>` : ''}</td>
        </tr>`).join('')}</tbody></table>
      </div></div>`).join('');
  if ($('#finalize')) $('#finalize').onclick = () => busy($('#finalize'), async () => {
    const sure = await confirmDialog('Mark the register final', 'Marking the Delegation of Authority register final ends the provisional period: an unlisted signatory becomes a hard stop. This is recorded under your name.', 'Mark final');
    if (!sure) return;
    try { await api.doaFinalize(state.officer); toast('Register marked final'); renderDoa(app); }
    catch (e) { toast(e.message, true); }
  });
  $$('#auth-list [data-spec]').forEach(b => b.onclick = () => specimenModal(b.dataset.spec, app));
}

function specimenModal(sigId, app) {
  openModal('Upload specimen signature', `
    <p class="small muted">The specimen is placed beside the case signature for the officer to compare (§8.4).</p>
    <div class="field"><label>Specimen image</label><input type="file" id="spec-file"></div>
    <button class="btn primary" id="spec-go">Upload</button>`);
  $('#spec-go').onclick = () => busy($('#spec-go'), async () => {
    const f = $('#spec-file').files[0];
    if (!f) return toast('Choose a file', true);
    try { await api.doaSpecimen(sigId, state.officer, f); closeModal(); toast('Specimen recorded'); renderDoa(app); }
    catch (e) { toast(e.message, true); }
  });
}

// ── rules in force ────────────────────────────────────────────────────────────
async function renderRules(app, seq = ROUTE.current) {
  const r = await api.rules();
  if (ROUTE.isStale(seq)) return;
  const clar = r.officeClarifications.map(x => `<tr><td><b>${esc(x.code)}</b></td><td>${esc(x.text)}</td></tr>`).join('');
  const limits = r.advanceLimits.map(l => `<tr>
    <td class="mono">${esc(l.clause)}</td><td>${esc(l.label)}</td>
    <td>${esc(l.pct)}%${l.months ? ' / ' + esc(l.months) + ' mo' : ''}${l.combine ? ' (' + esc(l.combine) + ')' : ''}</td>
    <td>${esc(l.officePct)}%</td><td class="small ${l.flag ? '' : 'muted'}">${l.flag ? '⚑ ' + esc(l.flag) : '—'}</td></tr>`).join('');
  const open = r.openItems.map(o => `<tr><td><b>${esc(o.ref)}</b></td><td>${esc(o.item)}</td></tr>`).join('');
  app.innerHTML = `
    <div class="panel"><h2>Rules in force</h2>
      <p class="muted small">Circular: ${esc(r.rulesetVersion.circular)}<br>Rules: ${esc(r.rulesetVersion.rules)}<br>
        Clarifications: ${esc(r.rulesetVersion.clarifications)}</p></div>
    <div class="panel"><h2>Cite a rule</h2>
      <p class="muted small">Search the circular clauses, rejection reasons, office clarifications and advance limits (semantic search via the embedding model, keyword fallback otherwise).</p>
      <div class="row"><input type="text" id="cite-q" style="flex:1;min-width:260px;padding:8px 10px;border:1px solid var(--line);border-radius:8px" placeholder="e.g. sanction signed by someone not authorised">
        <button class="btn primary" id="cite-go">Search</button></div>
      <div id="cite-results" style="margin-top:12px"></div>
    </div>
    <div class="panel"><h2>Office clarifications (R1–R15)</h2>
      <div class="table-wrap"><table><tbody>${clar}</tbody></table></div></div>
    <div class="panel"><h2>Advance limits by clause <span class="muted">(office 80% flagged where it differs)</span></h2>
      <div class="table-wrap"><table><thead><tr><th>Clause</th><th>Purpose</th><th>Rules limit</th><th>Office</th><th>Flag</th></tr></thead>
        <tbody>${limits}</tbody></table></div></div>
    <div class="panel"><h2>Thumb impressions</h2>
      <p><b>${esc(r.thumbprintFinding.conclusion)}</b></p>
      <ul>${r.thumbprintFinding.why.map(w => `<li>${esc(w)}</li>`).join('')}</ul>
      <p class="muted small">${esc(r.thumbprintFinding.instead)}</p></div>
    <div class="panel"><h2>Open items for the AG Office</h2>
      <div class="table-wrap"><table><tbody>${open}</tbody></table></div></div>`;

  const runCite = async () => {
    const q = $('#cite-q').value.trim();
    if (!q) return;
    $('#cite-results').innerHTML = '<p class="muted small">Searching…</p>';
    try {
      const out = await api.citations(q, 6);
      $('#cite-results').innerHTML =
        `<p class="muted small">method: ${esc(out.method)}</p>` +
        (out.results.map(x => `<div class="item"><div class="item-head" style="cursor:default">
          <span class="pill">${esc(x.id)}</span>
          <span class="item-title" style="font-weight:500">${esc(x.text)}</span>
          <span class="muted small">${esc(x.source)}${x.score != null ? ' · ' + x.score : ''}</span>
        </div></div>`).join('') || '<p class="muted">No match.</p>');
    } catch (e) { $('#cite-results').innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
  };
  $('#cite-go').onclick = runCite;
  $('#cite-q').addEventListener('keydown', e => { if (e.key === 'Enter') runCite(); });
}

start();
