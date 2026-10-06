/* ═══════════════════════════════════════════════════════════════════════
   DELEGATION OF AUTHORITY (DOA) REGISTER
   Who may sign, for or on behalf of each department authority, and their
   specimen signatures. The AG Office will supply the real register. Until
   then the entries below are PROVISIONAL: built from the signatories that
   appear in the eight case files, with no specimen on record. A provisional
   entry never raises a hard stop on its own; it creates a verification task.
   ═══════════════════════════════════════════════════════════════════════ */
const DOA_ABBR = [
  [/\bs\.?\s?p\b\.?/g,'superintendent of police'], [/\bd\.?i\.?g\b\.?/g,'deputy inspector general'],
  [/\bc\.?e\.?o\b\.?/g,'chief executive officer'], [/\bd\.?e\.?a\b\.?/g,'district education authority'],
  [/\bc\.?t\.?o\b\.?/g,'chief traffic officer'], [/\bs\.?t\.?o\b\.?/g,'senior traffic officer'],
  [/\bd\.?d\.?o\b\.?/g,'drawing and disbursing officer'], [/\bd\.?a\.?o\b\.?/g,'district accounts officer'],
  [/\badmn\b\.?/g,'admin'], [/\bhq\b|\bheadquarters?\b|\bheadquarter\b/g,'headquarters'],
  [/\bf\s*\/\s*o\b|\bfor\b|\bon behalf of\b/g,' ']
];
function doaNorm(s){
  let t = String(s||'').toLowerCase().replace(/[(),.:;]/g,' ');
  DOA_ABBR.forEach(([re,rep])=>{ t = t.replace(re, rep); });
  return t.replace(/\s+/g,' ').trim();
}
function doaScore(a, b){
  const A = new Set(doaNorm(a).split(' ').filter(w=>w.length>2));
  const B = new Set(doaNorm(b).split(' ').filter(w=>w.length>2));
  if (!A.size || !B.size) return 0;
  let hit = 0; A.forEach(w=>{ if (B.has(w)) hit++; });
  return hit / Math.min(A.size, B.size);
}

/* Look up the authority a document is issued in the name of, then the person who
   actually signed it. Returns what the register says, never a verdict on the ink. */
function doaLookup(authorityText, signatoryText){
  let best = null, bs = 0;
  (DOA.authorities||[]).forEach(a=>{
    const s = Math.max(doaScore(authorityText, a.authority), ...(a.aliases||[]).map(x=>doaScore(authorityText, x)));
    if (s > bs){ bs = s; best = a; }
  });
  if (!best || bs < 0.6) return { status:'authority_not_listed', authority:null, signatory:null };
  let sig = null, ss = 0;
  best.signatories.forEach(g=>{
    const s = doaScore(signatoryText, g.post + ' ' + (g.name||''));
    if (s > ss){ ss = s; sig = g; }
  });
  if (!sig || ss < 0.6) return { status:'signatory_not_listed', authority:best, signatory:null };
  return { status: sig.specimen ? 'listed_with_specimen' : 'listed_no_specimen', authority:best, signatory:sig };
}

function doaStatusText(m){
  if (m.status==='authority_not_listed') return 'The authority is not yet on the DOA register.';
  if (m.status==='signatory_not_listed') return 'The person who signed is not listed as an approved signatory for '+m.authority.authority+'.';
  if (m.status==='listed_no_specimen') return m.signatory.post+' is listed as authorised to sign for '+m.authority.authority+'. No specimen signature is on the register yet.';
  return m.signatory.post+' is listed as authorised to sign for '+m.authority.authority+'. Compare the signature with the specimen.';
}
