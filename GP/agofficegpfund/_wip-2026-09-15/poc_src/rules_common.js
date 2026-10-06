/* ═══════════════════════════════════════════════════════════════════════
   RULE CATALOGUE, PART 1: rules that apply across case families
   ref names the circular item and/or the office clarification (R1 to R15,
   AG Punjab, 15-09-2026). code is what prints on the rejection form.
   A run() may return one result or an array; array items carry a 'sub'
   key so each keeps a stable id across reprocessing.
   ═══════════════════════════════════════════════════════════════════════ */
const CHECKS = [];
const CUSTOM_CHECKS = {};
function check(def){ CHECKS.push(def); }
function ev(page, label, crop, bbox){ return { page, label, crop:crop||null, bbox:bbox||null }; }
const KIND = (F, ...k) => k.includes(F.kind);
const FINALS = ['final','death','dismissal','residual'];
const ADVANCES = ['refundable','nonrefundable'];
const digits = v => String(v||'').replace(/\D/g,'');
function nameKey(n){ return String(n||'').toLowerCase().replace(/\b(mr|mrs|ms|mst|miss|dr)\b\.?/g,'').replace(/[^a-z]/g,''); }
function sameName(a,b){
  const x = nameKey(a), y = nameKey(b);
  if (!x || !y) return null;
  return x === y || x.includes(y) || y.includes(x);
}
function verified(F, id){ return (F.verifications||{})[id] || null; }
function verifiedResult(v, okText, badText){
  return v.ok
    ? { status:'ok', finding: okText + ' Verified by ' + v.by + ' (' + v.desig + ') on ' + v.at + (v.note ? ': ' + v.note : '.') }
    : { status:'hard', finding: badText + ' Recorded by ' + v.by + ' (' + v.desig + ') on ' + v.at + (v.note ? ': ' + v.note : '.') };
}

/* ── R1, R8, R11: SAP extracts ─────────────────────────────────────────── */
check({ id:'SAP-PAYSLIP', group:'sap', ref:'R1 · R8', checklist:'SAP', title:'SAP pay slip of the subscriber',
  applies: F => true,
  run: F => {
    const p = F.sap && F.sap.payslip;
    if (p){
      const from = F.sap.source === 'case' ? 'found in the case at page ' + p.page : 'uploaded from SAP (' + F.sap.file + ')';
      return { status:'ok', finding:'Pay slip for ' + (p.month || 'the month shown') + ', personnel no. ' + p.persNo + ', ' + from + '.',
               evidence: p.page ? [ev(p.page, 'SAP pay slip')] : [] };
    }
    return { status:'sap', finding:'No SAP pay slip is in the case. Pull it from SAP against personnel no. ' + (F.personnelNo || '(not stated)') + ' and upload it on the SAP extracts step.',
             remedy:'Action for this section. Not a defect of the department.', cure:{ kind:'sap' } };
  }});

check({ id:'SAP-RECALC', group:'sap', ref:'R1 · R11', checklist:'SAP', title:'GPF Final Re-calculation Report from SAP',
  applies: F => true,
  run: F => {
    const r = F.sap && F.sap.recalc;
    const need = KIND(F, ...FINALS) ? 'Required with the pay slip for a final payment (R11).' :
                 KIND(F, ...ADVANCES) ? 'Needed to establish the balance for the 80% test and the advance position.' :
                 'Shows whether the months in question are already credited.';
    if (r && r.rows && r.rows.length){
      const last = r.rows[r.rows.length-1];
      const from = F.sap.source === 'case' ? 'found in the case at page ' + r.page : 'uploaded from SAP (' + F.sap.file + ')';
      return { status:'ok', finding:'Report ' + (r.reportDate ? 'dated ' + r.reportDate + ', ' : '') + from + '. Last period ' + last.start + ' to ' + last.end +
               ', closing balance Rs ' + fmt(last.closing) + '. ' + need, evidence: r.page ? [ev(r.page, 'GPF Final Re-calculation Report')] : [] };
    }
    return { status:'sap', finding:'No GPF Final Re-calculation Report is in the case. ' + need,
             remedy:'Pull the report from SAP against personnel no. ' + (F.personnelNo || '(not stated)') + ' and upload it.', cure:{ kind:'sap' } };
  }});

check({ id:'SAP-IDENTITY', group:'identity', ref:'R1', title:'SAP extract belongs to this subscriber',
  applies: F => !!(F.sap && (F.sap.payslip || F.sap.recalc)),
  run: F => {
    const want = digits(F.personnelNo), bad = [];
    [['pay slip', F.sap.payslip], ['re-calculation report', F.sap.recalc]].forEach(([l, x])=>{
      if (x && x.persNo && want && digits(x.persNo) !== want) bad.push('the ' + l + ' is for personnel no. ' + x.persNo);
    });
    if (bad.length) return { status:'hard', code:'R1', finding:'The case is for personnel no. ' + F.personnelNo + ' but ' + bad.join(' and ') + '.',
                             remedy:'Pull the extract for the correct personnel number.', cure:{ kind:'sap' } };
    return { status:'ok', finding:'Personnel no. ' + F.personnelNo + ' on every SAP extract.' };
  }});

/* ── R3: covering letter is never an observation ───────────────────────── */
check({ id:'COVER', group:'checklist', ref:'A2-i · A3-ii · A4-i · R3', title:'Covering / forwarding letter',
  checklist: F => KIND(F,'balance_transfer') ? 'A3-ii' : KIND(F,'missing_credits') ? 'A4-i' : 'A2-i',
  applies: F => !KIND(F, ...ADVANCES),
  run: F => {
    const c = (F.docs && F.docs.covering) || {};
    const what = c.present ? (c.nature || 'Forwarding instrument') + (c.author ? ' from ' + c.author : '') + (c.page ? ', page ' + c.page : '') + '.'
                           : 'No separate letter on file.';
    return { status:'ok', finding: what + ' Accepted under office practice: the covering letter is the authority’s notice to process the case and is not examined further (R3).',
             evidence: c.page ? [ev(c.page, 'Covering letter', c.crop)] : [] };
  }});

/* ── R5: attestation of CNIC copies and pay slips is not required ─────── */
check({ id:'CNIC-ATTEST', group:'identity', ref:'R5', title:'Attestation of CNIC copies',
  applies: F => ((F.docs && F.docs.cnics) || []).length > 0,
  run: F => F.docs.cnics.map((c, i)=>{
    const who = c.whose || 'subscriber';
    if (c.attested) return { sub:i, status:'ok', doc:'CNIC copy, ' + who,
      finding:'Copy of ' + who + '’s CNIC (' + (c.type==='smart' ? 'smart card' : 'older card') + ', page ' + c.page + ') is attested' + (c.attestedBy ? ' by ' + c.attestedBy : '') + '.',
      evidence:[ev(c.page, 'CNIC copy', c.crop)] };
    return { sub:i, status:'adv', code:'R5', doc:'CNIC copy, ' + who,
      finding:'The copy of ' + who + '’s CNIC at page ' + c.page + ' is not attested. Attestation is not required' + (c.type==='smart' ? ', and this is a smart card whose QR code is checked below' : '') + ', so this is noted only.',
      remedy:'None required. Noted for the department’s record.', evidence:[ev(c.page, 'CNIC copy', c.crop)] };
  })});

check({ id:'PAYSLIP-ATTEST', group:'identity', ref:'R5', title:'Attestation of pay slip copy',
  applies: F => !!(F.sap && F.sap.source === 'case' && F.sap.payslip && F.sap.payslip.attested === false),
  run: F => ({ status:'adv', code:'R5', finding:'The pay slip copy at page ' + F.sap.payslip.page + ' is not attested. A pay slip does not need attestation, so this is noted only.',
               remedy:'None required.', evidence:[ev(F.sap.payslip.page, 'Pay slip')] }) });

/* ── R10: every QR code is scanned and its content checked ─────────────── */
check({ id:'QR', group:'qr', ref:'R10 · B1-iii', title:'QR codes',
  applies: F => (F.qr || []).length > 0,
  run: F => F.qr.map(q=>{
    const base = { sub:q.id, doc:'QR code, ' + q.doc + ' (page ' + q.page + ')', evidence:[ev(q.page, 'QR code', q.crop)] };
    const v = verified(F, 'QR:' + q.id);
    if (!q.decoded){
      if (v) return Object.assign(base, verifiedResult(v, 'QR code checked on the original.', 'QR code on the original does not verify the document.'));
      return Object.assign(base, { status:'conf', finding:'A QR code is printed on the ' + q.doc + ' but could not be read from this scan (faded copy).',
        remedy:'Scan the original with the office QR reader, or upload a clearer copy, and record the result.', cure:{ kind:'qr', qid:q.id } });
    }
    const bad = (q.compare || []).filter(c=>c.match === false);
    const good = (q.compare || []).filter(c=>c.match === true);
    if (bad.length) return Object.assign(base, { status:'hard', code: q.codeOnMismatch || 'R10',
      finding:'QR code decoded. It disagrees with the document: ' + bad.map(c=>c.field + ' reads ' + c.qrVal + ' in the QR code but ' + c.docVal + ' on the ' + c.docLabel).join('; ') + '.',
      remedy: q.remedyOnMismatch || 'Obtain a corrected document that agrees with the QR record.', payload:q.payload });
    if (q.route === 'online'){
      if (v) return Object.assign(base, verifiedResult(v, 'Decoded link opened on the verification terminal; the portal record matches the document.', 'Portal record does not match the document.'));
      return Object.assign(base, { status:'conf', payload:q.payload,
        finding:'QR code decoded to a verification link on ' + q.host + '. ' + (good.length ? 'Its reference agrees with the document. ' : '') +
                'The portal page itself has to be opened to complete verification, which cannot be done from inside the air-gapped system.',
        remedy:'Open the link on the office verification terminal and record whether the portal record matches.', cure:{ kind:'verify', vid:'QR:' + q.id } });
    }
    return Object.assign(base, { status:'ok', payload:q.payload,
      finding:'QR code decoded and checked against the document: ' + (good.length ? good.map(c=>c.field + ' ' + c.qrVal).join(', ') + ' agree.' : 'content recorded.') });
  })});

check({ id:'QR-SANCTION', group:'qr', ref:'B1-iii · R10', code:'B1-iii', title:'QR-coded sanction (Health, Education, Police)',
  applies: F => KIND(F, ...ADVANCES) && F.docs && F.docs.sanction && F.docs.sanction.present && /health|education|police/i.test(F.docs.sanction.dept || ''),
  run: F => {
    const s = F.docs.sanction;
    const q = (F.qr || []).find(x=>x.id === s.qrId);
    if (q && q.decoded && !(q.compare || []).some(c=>c.match === false))
      return { status:'ok', finding:'The sanction carries a QR code. It was decoded and agrees with the order (see QR codes).', evidence:[ev(q.page, 'Sanction QR', q.crop)] };
    if (q) return null;                        /* the QR rule above carries the finding */
    const v = verified(F, 'QR-SANCTION');
    if (v) return verifiedResult(v, 'Sanction confirmed as properly issued without a QR code.', 'Sanction should carry a verified QR code.');
    return { status:'conf', finding:'The ' + s.dept + ' sanction at page ' + s.page + ' carries no QR code. The circular expects QR-coded sanctions from Health, Education and Police.',
             remedy:'Confirm whether this office issues QR-coded sanctions. If it does, obtain the QR-coded sanction.', cure:{ kind:'verify', vid:'QR-SANCTION' },
             evidence:[ev(s.page, 'Sanction')] };
  }});

/* ── R4: signatories against the delegation of authority register ──────── */
check({ id:'DOA', group:'signature', ref:'R4 · B1-ii · B1-vi · B2-iv', title:'Signatories and delegation of authority',
  applies: F => (F.signatures || []).some(g=>['sanctioning','ddo','forwarding'].includes(g.role)),
  run: F => F.signatures.filter(g=>['sanctioning','ddo','forwarding'].includes(g.role)).map(g=>{
    const m = doaLookup(g.authority, g.signedBy);
    const base = { sub:g.id, doc:g.roleLabel + ', ' + g.doc + ' (page ' + g.page + ')', evidence:[ev(g.page, 'Signature and stamp', g.crop)], doa:m, sig:g };
    const code = g.role === 'sanctioning' ? (KIND(F,'refundable') ? 'B1-ii' : 'B2-iv') : 'R4';
    const v = verified(F, 'DOA:' + g.id);
    const who = g.signedBy + (g.forMarker ? ' for ' + g.authority : '');
    if (v) return Object.assign(base, verifiedResult(v, who + ': authority and signature confirmed against the DOA register.', who + ': not an approved signatory, or the signature does not match the specimen.'), v.ok ? {} : { code });
    if (m.status === 'signatory_not_listed' && DOA.status === 'final')
      return Object.assign(base, { status:'hard', code, finding: doaStatusText(m) + ' Signed by ' + who + '.',
        remedy:'Obtain the document under the signature of an approved signatory.' });
    return Object.assign(base, { status:'conf', finding:'Signed by ' + who + '. ' + doaStatusText(m) + (DOA.status === 'final' ? '' : ' The register is provisional until the office supplies its DOA list.'),
      remedy: m.status === 'listed_with_specimen' ? 'Compare the signature with the specimen and record the result.' : 'Confirm the signatory’s authority, and add the specimen to the register when received.',
      cure:{ kind:'verify', vid:'DOA:' + g.id } });
  })});

/* ── R7: thumb impressions cannot be matched to a CNIC copy ────────────── */
check({ id:'THUMB', group:'signature', ref:'R7', title:'Thumb impression in place of a signature',
  applies: F => (F.thumbs || []).length > 0,
  run: F => F.thumbs.map(t=>{
    const base = { sub:t.id, doc:'Thumb impression, ' + t.doc + ' (page ' + t.page + ')', evidence:[ev(t.page, 'Thumb impression', t.crop)] };
    const v = verified(F, 'THUMB:' + t.id);
    if (v) return Object.assign(base, verifiedResult(v, 'Identity of the person who thumbed (' + t.whose + ') confirmed.', 'Identity of the person who thumbed could not be confirmed.'));
    return Object.assign(base, { status:'conf',
      finding:t.whose + ' has thumbed the ' + t.doc + ' instead of signing. The module does not match thumb impressions to CNIC copies: smart cards carry no fingerprint, and the scans are far below the resolution fingerprint comparison needs.',
      remedy:'Confirm identity through NADRA biometric verification or the attesting officer’s certificate on the impression, and record which.', cure:{ kind:'verify', vid:'THUMB:' + t.id } });
  })});

/* ── R6: subscriber signature on the change form against the CNIC ──────── */
check({ id:'SIG-CNIC', group:'signature', ref:'R6', title:'Subscriber signature on the change form matches the CNIC',
  applies: F => KIND(F, ...ADVANCES) && F.docs && F.docs.changeForm && F.docs.changeForm.present,
  run: F => {
    const cf = F.docs.changeForm;
    const card = (F.docs.cnics || []).find(c=>(c.whose || 'subscriber') === 'subscriber');
    const pair = { left:{ label:'Specimen signature, ' + cf.label + ' p' + cf.page, crop:cf.sigCrop }, right:{ label:'Holder’s signature, CNIC p' + (card ? card.page : '?'), crop: card ? card.sigCrop : null } };
    if (cf.sigKind === 'thumb') return { status:'na', finding:'Thumb impression used; see the thumb impression check (R7).' };
    if (!cf.sigKind || cf.sigKind === 'none')
      return { status:'hard', code: KIND(F,'refundable') ? 'B1-vii' : 'B2-v', finding:'The subscriber has not signed the ' + cf.label + '.',
               remedy:'Obtain the subscriber’s signature on the form.', evidence:[ev(cf.page, cf.label)], cure:{ kind:'doc', docType:cf.label, fields:[{k:'signed', label:'Subscriber has signed', type:'yesno'}], apply:'form-signed' } };
    if (!card) return { status:'hard', code:'A1-ii', finding:'No CNIC copy of the subscriber is on file to compare the signature against.', remedy:'Obtain a copy of the subscriber’s CNIC.',
                        cure:{ kind:'doc', docType:'CNIC copy', fields:[{k:'number', label:'CNIC number on the copy', type:'text', expect:cf.cnic}], apply:'add-cnic' } };
    const v = verified(F, 'SIG-CNIC');
    if (v) return Object.assign(verifiedResult(v, 'Signature on the ' + cf.label + ' matches the holder’s signature on the CNIC.', 'Signature on the ' + cf.label + ' does not match the CNIC.'), { pair, code:'R6' });
    return { status:'conf', pair, finding:'Compare the subscriber’s specimen signature on the ' + cf.label + ' with the holder’s signature on the CNIC. The module places them side by side; the officer decides.',
             remedy:'Record whether the signatures match.', cure:{ kind:'verify', vid:'SIG-CNIC' }, evidence:[ev(cf.page, cf.label, cf.sigCrop), ev(card.page, 'CNIC', card.sigCrop)] };
  }});
