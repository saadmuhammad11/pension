// Thin fetch wrapper around the pre-audit API. Same-origin, no dependencies.
//
// Every address is relative to where the app is served from, so it works at / on its own port
// and under a prefix when the AG Punjab portal proxies it (28 Sep 2026: /gpf/ on :5184).
export const BASE = new URL('.', location.href).pathname.replace(/\/$/, '');

async function j(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const res = await fetch(url, opt);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || ('Request failed (' + res.status + ')'));
  return data;
}

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
  getCase: (id) => j('GET', BASE + '/api/cases/' + id),

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
    if (!res.ok) throw new Error(started.detail || 'Reading failed');
    if (onUploaded) onUploaded(started);

    // Poll about once a second. Slower would make a fast page look stalled; faster would put
    // the officer's browser in contention with the model for the same box.
    for (;;) {
      await new Promise(r => setTimeout(r, 900));
      const r = await fetch(BASE + '/api/reading/jobs/' + encodeURIComponent(started.jobId));
      const job = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(job.detail || 'Lost track of the reading job');
      if (onProgress) onProgress(job);
      if (job.state === 'error') throw new Error(job.detail || 'Reading failed');
      if (job.state === 'done') return job.result;
    }
  },

  sapText: (id, filename, text, officer) =>
    j('POST', `${BASE}/api/cases/${id}/sap`, { filename, text, officer }),
  sapTemplate: (id) => j('GET', `${BASE}/api/cases/${id}/sap-template`),

  verify: (id, vid, ok, note, officer) =>
    j('POST', `${BASE}/api/cases/${id}/verify`, { vid, ok, note, officer }),
  dispose: (id, disposal, note, officer) =>
    j('POST', `${BASE}/api/cases/${id}/dispose`, { disposal, note, officer }),
  setDisposition: (id, resultId, action, ground, authority, officer) =>
    j('POST', `${BASE}/api/cases/${id}/dispositions`, { resultId, action, ground, authority, officer }),
  issuePack: (id) => j('GET', `${BASE}/api/cases/${id}/issue-pack`),

  // cure is multipart (optional file) — send FormData directly
  cure: async (id, resultId, values, officer, file) => {
    const fd = new FormData();
    fd.append('resultId', resultId);
    fd.append('officer', officer);
    fd.append('values', JSON.stringify(values || {}));
    if (file) fd.append('file', file);
    const res = await fetch(`${BASE}/api/cases/${id}/cure`, { method: 'POST', body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'Cure failed');
    return data;
  },

  doaSpecimen: async (sigId, officer, file) => {
    const fd = new FormData();
    fd.append('sigId', sigId); fd.append('officer', officer); fd.append('file', file);
    const res = await fetch(BASE + '/api/doa/specimens', { method: 'POST', body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'Specimen upload failed');
    return data;
  },
  doaSignatory: (authorityId, post, name, mayFor, powers, officer) =>
    j('POST', BASE + '/api/doa/signatories', { authorityId, post, name, mayFor, powers, officer }),
  doaFinalize: (officer) => j('POST', BASE + '/api/doa/finalize', { officer }),
};
