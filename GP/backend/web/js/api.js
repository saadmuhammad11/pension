// Thin fetch wrapper around the pre-audit API. Same-origin, no dependencies.
//
// Every address is relative to where the app is served from, so it works at / on its own port
// and under a prefix when the AG Punjab portal proxies it (28 Sep 2026: /gpf/ on :5184).
import { encodeId, pollBudget } from './pure.js';

export const BASE = new URL('.', location.href).pathname.replace(/\/$/, '');

// Framed in the AG Punjab portal (`?embed=1`): the page may tell its parent two things, and
// only its own origin (F9, F13).
const EMBEDDED = new URLSearchParams(location.search).get('embed') === '1' && window.parent !== window;
export function tellPortal(message) {
  if (!EMBEDDED) return false;
  try { window.parent.postMessage(message, location.origin); return true; } catch (e) { return false; }
}

// A 401 means the frame's sign-in has ended: the portal re-signs the frame and reloads it.
function refused(res) {
  if (res.status === 401) tellPortal({ gpfExpired: 1 });
}

async function j(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const res = await fetch(url, opt);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { refused(res); throw new Error(data.detail || ('Request failed (' + res.status + ')')); }
  return data;
}
const id = encodeId;

export const api = {
  health: () => j('GET', BASE + '/api/health'),
  officers: () => j('GET', BASE + '/api/officers'),
  acting: () => j('GET', BASE + '/api/acting'),
  rules: () => j('GET', BASE + '/api/rules'),
  citations: (q, k = 5) => j('GET', `${BASE}/api/citations/search?q=${encodeURIComponent(q)}&k=${k}`),
  doa: () => j('GET', BASE + '/api/doa'),

  templates: () => j('GET', BASE + '/api/case-templates'),
  listCases: () => j('GET', BASE + '/api/cases'),
  createCase: (templateKey, withoutSap, officer) =>
    j('POST', BASE + '/api/cases', { templateKey, withoutSap, officer }),
  getCase: (caseId) => j('GET', BASE + '/api/cases/' + id(caseId)),

  // Reading scans is two vision-model calls per page — a minute or more on a real file.
  // Starting a job and polling it is what lets the officer see that something is happening;
  // `onProgress` is called with each poll's state. `onUploaded` fires when the bytes are in,
  // which is the moment the wait stops being about the network and starts being about the model.
  fromScans: async (kind, gazetted, officer, fileList, onProgress, onUploaded) => {
    const fd = new FormData();
    fd.append('kind', kind); fd.append('gazetted', gazetted); fd.append('officer', officer);
    for (const f of fileList) fd.append('files', f);
    const res = await fetch(BASE + '/api/cases/from-scans/start', { method: 'POST', body: fd });
    const started = await res.json().catch(() => ({}));
    if (!res.ok) { refused(res); throw new Error(started.detail || 'Reading failed'); }
    if (onUploaded) onUploaded(started);

    // Poll about once a second. Slower would make a fast page look stalled; faster would put
    // the officer's browser in contention with the model for the same box. One dropped poll
    // used to abandon a job the model was still working on, and the officer re-uploaded the
    // whole file (F13): now a few failures in a row are tolerated, the loop is capped (about 40
    // minutes), and leaving the page stops it.
    const budget = pollBudget({ maxFailures: 3, maxPolls: 2700 });
    let left = false;
    const onLeave = () => { left = true; };
    window.addEventListener('hashchange', onLeave);
    try {
      for (;;) {
        await new Promise(r => setTimeout(r, 900));
        if (left) throw new Error('The page was left while the scans were being read; the job continues on the server. Reopen the case list to see it.');
        if (budget.tick()) throw new Error('The reading job is taking longer than expected; the job continues on the server.');
        let r, job;
        try {
          r = await fetch(BASE + '/api/reading/jobs/' + id(started.jobId));
          job = await r.json().catch(() => ({}));
        } catch (e) {
          if (budget.failed()) throw new Error('Lost contact with the server while the scans were being read.');
          continue;
        }
        if (r.status === 401) { refused(r); throw new Error('The sign-in ended while the scans were being read.'); }
        if (r.status === 404) throw new Error(job.detail || 'Lost track of the reading job');
        if (!r.ok) {
          if (budget.failed()) throw new Error(job.detail || 'Lost track of the reading job');
          continue;
        }
        budget.ok();
        if (onProgress) onProgress(job);
        if (job.state === 'error') throw new Error(job.detail || 'Reading failed');
        if (job.state === 'done') return job.result;
      }
    } finally {
      window.removeEventListener('hashchange', onLeave);
    }
  },

  sapText: (caseId, filename, text, officer) =>
    j('POST', `${BASE}/api/cases/${id(caseId)}/sap`, { filename, text, officer }),
  sapTemplate: (caseId) => j('GET', `${BASE}/api/cases/${id(caseId)}/sap-template`),

  verify: (caseId, vid, ok, note, officer) =>
    j('POST', `${BASE}/api/cases/${id(caseId)}/verify`, { vid, ok, note, officer }),
  dispose: (caseId, disposal, note, officer) =>
    j('POST', `${BASE}/api/cases/${id(caseId)}/dispose`, { disposal, note, officer }),
  setDisposition: (caseId, resultId, action, ground, authority, officer) =>
    j('POST', `${BASE}/api/cases/${id(caseId)}/dispositions`, { resultId, action, ground, authority, officer }),
  issuePack: (caseId) => j('GET', `${BASE}/api/cases/${id(caseId)}/issue-pack`),

  // cure is multipart (optional file) — send FormData directly
  cure: async (caseId, resultId, values, officer, file) => {
    const fd = new FormData();
    fd.append('resultId', resultId);
    fd.append('officer', officer);
    fd.append('values', JSON.stringify(values || {}));
    if (file) fd.append('file', file);
    const res = await fetch(`${BASE}/api/cases/${id(caseId)}/cure`, { method: 'POST', body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { refused(res); throw new Error(data.detail || 'Cure failed'); }
    return data;
  },

  doaSpecimen: async (sigId, officer, file) => {
    const fd = new FormData();
    fd.append('sigId', sigId); fd.append('officer', officer); fd.append('file', file);
    const res = await fetch(BASE + '/api/doa/specimens', { method: 'POST', body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { refused(res); throw new Error(data.detail || 'Specimen upload failed'); }
    return data;
  },
  doaSignatory: (authorityId, post, name, mayFor, powers, officer) =>
    j('POST', BASE + '/api/doa/signatories', { authorityId, post, name, mayFor, powers, officer }),
  doaFinalize: (officer) => j('POST', BASE + '/api/doa/finalize', { officer }),
};
