/* ═══════════════════════════════════════════════════════════════════════
   SCREEN 4: examination, verification tasks, uploads and reprocessing
   ═══════════════════════════════════════════════════════════════════════ */
const CLAUSE = {
  'B1-i':'Insufficient balance in the GP Fund Account',
  'B1-ii':'Original sanction not attached and/or not signed by competent authority as per delegation of power',
  'B1-iii':'QR-coded sanction not verified by department (Health, Education & Police)',
  'B1-iv':'Respective rule and relevant reason for advance not mentioned on sanction',
  'B1-v':'Change Form-05 not found attached with the GP Fund case',
  'B1-vi':'Signature of sanctioning authority does not match the specimen signature provided',
  'B1-vii':'Change Form not signed by respective DDO and subscriber',
  'B2-i':'Incomplete GP Fund Form-10: signature, old and new GP Fund A/c No., Personnel Number, Date of Retirement',
  'B2-ii':'Mismatch in the subscription period with the service as mentioned on Service Book and Service Statement',
  'B2-iii':'Change Form-06 for final payment and non-refundable advance not attached',
  'B2-iv':'Signature of sanctioning authority does not match the specimen provided',
  'B2-v':'Change Form not signed by respective DDO and subscriber',
  'B2-vi':'Missing credits and adjustments found in Re-Calculation Sheet of applicant',
  'B2-vii':'Old GP Fund A/c No. / manual not mentioned in change form',
  'B2-viii':'Requisite entries not found in Service Book (date of retirement, order of retirement, leave account)',
  'B2-ix':'Respective rule not quoted on sanction (non-refundable advance)',
  'A1-ii':'Checklist A.1(ii): copy of CNIC of the subscriber',
  'A2-iii':'Checklist A.2(iii): retirement / dismissal / obituary notification',
  'A2-iv':'Checklist A.2(iv): CNIC of subscriber; in a death case, of all legal heirs',
  'A2-vi':'Checklist A.2(vi): affidavit for lawful widow and succession certificate where applicable',
  'A3-i':'Checklist A.3(i): completely filled proforma for transfer of GP Fund balances',
  'A4-ii':'Checklist A.4(ii): period of missing months',
  'A4-iii':'Checklist A.4(iii): manual deduction certificate by DDO, non-gazetted period',
  'A4-iv':'Checklist A.4(iv): manual deduction certificate by AG Office, gazetted period',
  'A4-v':'Checklist A.4(v): challan forms verified by Treasury Office',
  'R1':'Office clarification 15-09-2026, R1: SAP extracts', 'R4':'Office clarification 15-09-2026, R4: delegation of authority',
  'R5':'Office clarification 15-09-2026, R5: attestation not required; noted only',
  'R6':'Office clarification 15-09-2026, R6: Form 5 / Form 6-B personal number and signature',
  'R10':'Office clarification 15-09-2026, R10: QR codes scanned and validated',
  'R12':'Office clarification 15-09-2026, R12: no two active advances'
};
function clauseText(code){ return CLAUSE[code] || (String(code).indexOf('OFF')===0 ? 'Outside the standardised list, raised with justification' : 'Checklist item '+code); }

function renderExam(k){
  const s = STATE[k], F = s.F, L = lists(s.results), p = position(k);
  let h = '<h1 class="pagetitle">'+esc(F.label)+', examination</h1>'+
    '<p class="pagesub">'+esc(F.subject)+' · '+esc(F.dept)+' · version '+s.version+' · '+plural(p.total,'observation')+', '+p.open+' still to be disposed of · '+plural(L.conf.length,'verification task')+' · '+plural(L.sap.length,'SAP item')+'</p>';
  if (s.lastDiff && s.version > 1) h += diffBanner(k);
  h += '<div class="notice '+(p.hard ? 'red' : 'ok')+'" id="posband"><b>'+(p.hard ? 'As things stand the case cannot advance: '+plural(p.hard,'hard stop')+' outstanding.' : 'No hard stop outstanding.')+'</b> '+
       (p.waived||p.corrected||p.referred ? p.waived+' waived, '+p.corrected+' settled in office, '+p.referred+' referred upward. ' : '')+
       (L.conf.length ? plural(L.conf.length,'verification task')+' for an officer. ' : '')+(L.sap.length ? plural(L.sap.length,'check')+' waiting for SAP data. ' : '')+
       'Observations issue together, in one instance, as para 2 of the circular requires.</div>';
  if (s.returns >= 1) h += '<div class="notice gold"><b>This case has already been returned once.</b> A second return needs the review and signature of the DAG (Funds) / DAO I under para 3. The gate applies at disposal.</div>';
  h += '<div class="secnav"><a href="#x-obs">Observations</a><a href="#x-conf">Verification tasks</a><a href="#x-all">All checks</a><a href="#x-rec">Case record</a><a href="#x-hist">Case history</a></div>';

  /* observations */
  h += '<div class="card" id="x-obs"><h3>Observations, and what the officer decides to do with each</h3>'+
       '<p class="hint"><b>Uphold</b> keeps it on the form. <b>Waive</b> accepts the deficiency on recorded grounds. <b>Settle in office</b> is for a datum the file or SAP already evidences. '+
       '<b>Refer upward</b> sends it to a higher officer. <b>Upload document</b> takes the curing paper against the observation and re-checks the case.</p>';
  if (!L.obs.length) h += '<div class="src">No observation is raised on this case.</div>';
  L.obs.forEach(o=>{ h += obsBlock(k, o); });
  const openAdv = L.adv.filter(o=>!s.disp[o.id]);
  if (openAdv.length > 1) h += '<div class="act"><button class="abtn" onclick=\'upholdAllAdv('+JSON.stringify(k)+')\'>Uphold all '+openAdv.length+' open advisory observations</button></div>';
  h += '</div>';

  /* verification tasks */
  h += '<div class="card" id="x-conf"><h3>Verification tasks</h3><p class="hint">Things the module sets up but an officer must decide: signatures against the DOA register and the CNIC, thumb impressions, QR links that need the portal, and facts to confirm. '+
       (may('verify') ? '' : '<b>Recording a verification requires '+whoCan('verify')+'.</b>')+'</p>';
  if (!L.conf.length) h += '<div class="src">None open.</div>';
  L.conf.forEach(r=>{ h += confBlock(k, r); });
  h += '</div>';

  if (L.sap.length){
    h += '<div class="card"><h3>Waiting for SAP data</h3><p class="hint">Actions for this section, not defects of the department.</p><ul style="margin:0;padding-left:18px;font-size:13px">'+
         L.sap.map(r=>'<li>'+esc(r.title)+': <span class="src">'+esc(r.finding)+'</span></li>').join('')+'</ul>'+
         '<div class="act"><button class="abtn up" onclick=\'renderSap('+JSON.stringify(k)+');go(3)\'>Go to SAP extracts</button></div></div>';
  }

  /* all checks */
  const GROUPS = [['checklist','Checklist'],['sap','SAP extracts'],['identity','Identity and personal number'],['signature','Signatures and delegation of authority'],['qr','QR codes'],['balance','Balance and advances']];
  h += '<div class="card" id="x-all"><h3>All checks</h3><p class="hint">Every rule applied to this case, with the result and where it was found. Satisfied items are recorded here so the file shows what was checked, not only what failed.</p>';
  GROUPS.forEach(([g,lab])=>{
    const rows = s.results.filter(r=>r.group===g);
    if (!rows.length) return;
    h += '<h4>'+lab+'</h4><table><tr><th style="width:120px">Reference</th><th>Check and finding</th><th style="width:150px">Result</th></tr>';
    rows.forEach(r=>{
      h += '<tr><td class="mono" style="font-size:11.5px">'+esc(typeof r.checklist==='function' ? r.checklist(F) : (r.checklist||r.ref))+'</td><td><div class="fv">'+esc(r.doc||r.title)+'</div>'+
           '<div class="src" style="margin-top:3px">'+esc(r.finding)+'</div>'+(r.payload ? '<div class="qrpay" style="margin-top:5px">'+esc(r.payload)+'</div>' : '')+calcBlock(r)+
           (r.evidence && r.evidence.length ? '<div class="src" style="margin-top:3px">'+r.evidence.map(e=>pglink(k,e.page,e.label,e.bbox)).join(' ')+'</div>' : '')+'</td><td>'+vd(r.status)+'</td></tr>';
    });
    h += '</table>';
  });
  h += '</div>';

  /* case record */
  h += '<div class="card" id="x-rec"><h3>Extracted case record</h3><p class="hint">Read by the vision stage. Each value carries its source page and a confidence; below threshold goes to an officer.</p><table>'+
       '<tr><th>Field</th><th>Value</th><th>Source</th><th>Confidence</th></tr>'+
       (F.record||[]).map(r=>'<tr><td>'+esc(r[0])+'</td><td class="fv">'+esc(r[1])+'</td><td class="src">'+esc(r[2])+(r[4] ? ' '+pglink(k,r[4]) : '')+'</td><td>'+confBar(r[3])+'</td></tr>').join('')+'</table></div>';

  /* history */
  h += '<div class="card" id="x-hist"><h3>Case history</h3><p class="hint">Each upload or verification re-checks the whole case and adds a version. Earlier versions stay on record.</p>'+
       '<table class="compact"><tr><th>Version</th><th>When</th><th>By</th><th>Why</th><th class="n">Hard</th><th class="n">Obs.</th><th class="n">Verify</th><th class="n">SAP</th></tr>'+
       s.history.map(v=>'<tr><td>'+v.v+'</td><td class="mono">'+esc(v.at)+'</td><td>'+esc(v.by)+'</td><td>'+esc(v.reason)+(v.v>1 ? '<div class="src">'+v.resolved+' resolved, '+v.raised+' raised</div>' : '')+'</td>'+
         '<td class="n">'+v.hard+'</td><td class="n">'+v.adv+'</td><td class="n">'+v.conf+'</td><td class="n">'+v.sap+'</td></tr>').join('')+'</table>'+
       (s.uploads.length ? '<h4>Documents uploaded</h4><table class="compact"><tr><th>File</th><th>Against</th><th>By</th><th>SHA-256</th></tr>'+
         s.uploads.map(u=>'<tr><td>'+esc(u.name)+'<div class="src">'+fmtSize(u.size)+'</div></td><td>'+esc(u.against)+'</td><td>'+esc(u.by)+'<div class="src">'+esc(u.at)+'</div></td><td class="mono" style="font-size:11px;word-break:break-all">'+esc(u.hash)+'</td></tr>').join('')+'</table>' : '')+
       '</div>';
  h += '<div class="actionbar"><button class="btn" id="todisposal">Proceed to disposal</button><button class="btn ghost" onclick=\'renderSap('+JSON.stringify(k)+');go(3)\'>SAP extracts</button><button class="btn ghost" onclick="renderIntake();go(1)">Take another case</button></div>';
  $('s4body').innerHTML = h;
  $('todisposal').onclick = ()=>{ renderDisposal(k); go(5); };
}

function confBar(v){
  if (v===undefined || v===null) return '';
  const pct = Math.round(v*100);
  return '<span class="src nowrap" style="color:'+(v<0.9?'var(--amber)':'var(--muted)')+'">'+pct+'%</span>';
}
function calcBlock(r){
  const c = r.calc; if (!c) return '';
  if (c.ruleLimit !== undefined) return '<table class="num compact" style="margin-top:6px;max-width:520px"><tr><td>Sanctioned</td><td class="n mono">Rs '+fmt(c.amount)+'</td></tr>'+
    '<tr><td>GPF balance before this advance</td><td class="n mono">Rs '+fmt(c.balance)+'</td></tr>'+
    '<tr><td>'+c.pct+'% of the balance</td><td class="n mono">Rs '+fmt(c.byPct)+'</td></tr>'+
    (c.byPay!==null ? '<tr><td>'+c.months+' months’ pay at Rs '+fmt(c.pay)+'</td><td class="n mono">Rs '+fmt(c.byPay)+'</td></tr>' : '')+
    '<tr><td class="fv">Limit under '+esc(c.rule)+(c.byPay!==null ? ' ('+(c.combine==='max'?'greater':'lesser')+' of the two)' : '')+'</td><td class="n mono fv">Rs '+fmt(c.ruleLimit)+'</td></tr>'+
    '<tr><td class="fv">'+(c.amount<=c.ruleLimit?'Headroom':'Excess')+'</td><td class="n mono fv">Rs '+fmt(Math.abs(c.ruleLimit-c.amount))+'</td></tr>'+
    '<tr><td class="muted">Office practice, '+c.officePct+'% of balance'+(c.office!==c.ruleLimit?' (flagged: differs from the Rules)':'')+'</td><td class="n mono muted">Rs '+fmt(c.office)+'</td></tr></table>';
  if (c.claim !== undefined) return '<table class="num compact" style="margin-top:6px;max-width:460px"><tr><td>Amount claimed</td><td class="n mono">Rs '+fmt(c.claim)+'</td></tr><tr><td>Per SAP re-calculation report</td><td class="n mono">Rs '+fmt(c.expected)+'</td></tr><tr><td class="fv">Difference</td><td class="n mono fv">Rs '+fmt(Math.abs(c.claim-c.expected))+'</td></tr></table>';
  if (c.attached !== undefined) return '<table class="num compact" style="margin-top:6px;max-width:460px"><tr><td>Scheduled and Treasury-verified</td><td class="n mono">Rs '+fmt(c.scheduled)+'</td></tr><tr><td>Challans attached</td><td class="n mono">Rs '+fmt(c.attached)+'</td></tr><tr><td class="fv">Variance</td><td class="n mono fv">Rs '+fmt(c.variance)+'</td></tr></table>';
  return '';
}

function obsBlock(k, o){
  const s = STATE[k], d = s.disp[o.id];
  const cls = d ? ({waive:'waived', correct:'corrected', refer:'referred', uphold:o.status})[d.action] : o.status;
  const lab = d ? ({waive:['waived','Waived on grounds'], correct:['ok','Settled in office'], refer:['ref','Referred upward'], uphold:[o.status, o.status==='hard'?'Upheld, hard stop':'Upheld, observation']})[d.action]
                : [o.status, o.status==='hard' ? 'Hard stop' : 'Observation'];
  const K = JSON.stringify(k), I = JSON.stringify(o.id);
  let h = '<div class="obs '+cls+'" id="ob-'+esc(o.id)+'"><div class="obshead"><span class="obscode">'+esc(o.code)+'</span><span class="obsdoc">'+esc(o.doc||o.title)+'</span>'+
          '<span class="vd '+(STLAB[lab[0]]?STLAB[lab[0]][0]:lab[0])+'">'+lab[1]+'</span></div>'+
          '<div class="obsrow"><span class="obsk">Defect</span><span>'+esc(o.finding)+'</span></div>'+calcBlock(o)+
          '<div class="obsrow"><span class="obsk">Clause</span><span>'+esc(clauseText(o.code))+'</span></div>'+
          (o.remedy ? '<div class="obsrow"><span class="obsk">Remedy</span><span>'+esc(o.remedy)+'</span></div>' : '')+
          (o.evidence && o.evidence.some(e=>e.crop) ? '<div class="evid">'+o.evidence.filter(e=>e.crop).map(e=>evBox(k,e)).join('')+'</div>'
            : (o.evidence && o.evidence.length ? '<div class="obsrow"><span class="obsk">Seen at</span><span>'+o.evidence.map(e=>pglink(k,e.page,e.label,e.bbox)).join(' ')+'</span></div>' : ''));
  if (d){
    h += '<div class="recorded"><b>'+lab[1]+'</b> by '+esc(d.by)+', '+esc(d.desig)+' ('+esc(d.grade)+') on '+esc(d.at)+'.'+(d.reason?'<br><b>Ground:</b> '+esc(d.reason):'')+(d.authority?'<br><b>Authority relied upon:</b> '+esc(d.authority):'')+
         '<br><button class="abtn" style="margin-top:7px" onclick=\'undoDisp('+K+','+I+')\'>Undo</button>'+(o.cure ? ' <button class="abtn up" style="margin-top:7px" onclick=\'openCure('+K+','+I+')\'>Upload document against this</button>' : '')+'</div>';
  } else {
    h += '<div class="act"><button class="abtn" onclick=\'doDisp('+K+','+I+',"uphold")\'>Uphold</button>'+dbtn(k,o,'waive','Waive on grounds')+dbtn(k,o,'correct','Settle in office')+dbtn(k,o,'refer','Refer upward')+
         (o.cure ? '<button class="abtn up" onclick=\'openCure('+K+','+I+')\'>'+(o.cure.kind==='sap' ? 'Upload SAP extract' : 'Upload document against this')+'</button>' : '')+
         '</div><div id="df-'+esc(o.id)+'"></div>';
  }
  return h + '</div>';
}
function dbtn(k, o, action, label){
  const ok = may(action, o.status);
  return '<button class="abtn" '+(ok?'':'disabled ')+'onclick=\'doDisp('+JSON.stringify(k)+','+JSON.stringify(o.id)+','+JSON.stringify(action)+')\'>'+label+'</button>'+
         (ok ? '' : '<span class="lockmsg">'+label+' requires '+whoCan(action, o.status)+'</span>');
}

function confBlock(k, r){
  const K = JSON.stringify(k), I = JSON.stringify(r.id), vid = r.cure && r.cure.vid;
  let h = '<div class="obs conf" id="ob-'+esc(r.id)+'"><div class="obshead"><span class="obscode">'+esc(r.ref)+'</span><span class="obsdoc">'+esc(r.doc||r.title)+'</span>'+vd('conf')+'</div>'+
          '<div class="obsrow"><span class="obsk">Finding</span><span>'+esc(r.finding)+'</span></div>'+
          (r.payload ? '<div class="obsrow"><span class="obsk">QR reads</span><span class="qrpay">'+esc(r.payload)+'</span></div>' : '')+calcBlock(r)+
          (r.remedy ? '<div class="obsrow"><span class="obsk">To do</span><span>'+esc(r.remedy)+'</span></div>' : '');
  if (r.pair){
    h += '<div class="cmp">'+evBox(k, {crop:r.pair.left.crop, label:r.pair.left.label, page:(STATE[k].F.docs.changeForm||{}).page})+
         evBox(k, {crop:r.pair.right.crop, label:r.pair.right.label, page:((STATE[k].F.docs.cnics||[])[0]||{}).page})+'</div>';
  } else if (r.doa && r.sig){
    const spec = r.doa.signatory && r.doa.signatory.specimen;
    h += '<div class="cmp">'+evBox(k, {crop:r.sig.crop, label:'Signature on the '+r.sig.doc, page:r.sig.page})+
         '<div class="evbox">'+(spec ? '<img src="'+spec.url+'" alt="">' : '<div class="noimg">Specimen not yet on the register</div>')+
         '<div class="evcap"><b>DOA register</b> '+esc(r.doa.authority ? r.doa.authority.authority : 'authority not listed')+(r.doa.signatory ? ', '+esc(r.doa.signatory.post) : '')+
         ' <span class="pglink" onclick="renderDoa();go(\'doa\')">open register</span></div></div></div>';
  } else if (r.evidence && r.evidence.some(e=>e.crop)){
    h += '<div class="evid">'+r.evidence.filter(e=>e.crop).map(e=>evBox(k,e)).join('')+'</div>';
  }
  if (vid){
    const ok = may('verify');
    h += '<div class="dispform"><label for="vn-'+esc(r.id)+'">What was checked, and where</label><textarea id="vn-'+esc(r.id)+'" placeholder="e.g. compared with specimen on register entry; NADRA biometric verification ref. no."></textarea>'+
         '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><button class="abtn on" '+(ok?'':'disabled ')+'onclick=\'doVerify('+K+','+I+','+JSON.stringify(vid)+',true)\'>Verified</button>'+
         '<button class="abtn" '+(ok?'':'disabled ')+'onclick=\'doVerify('+K+','+I+','+JSON.stringify(vid)+',false)\'>Does not verify</button>'+
         (r.cure.kind==='qr' || r.cure.kind==='doc' ? '<button class="abtn up" onclick=\'openCure('+K+','+I+')\'>Upload document</button>' : '')+
         (ok ? '<span class="src">Recorded against '+esc(OFFICER.desig)+' ('+esc(OFFICER.grade)+').</span>' : '<span class="lockmsg">Requires '+whoCan('verify')+'</span>')+'</div></div>';
  } else if (r.cure){
    h += '<div class="act"><button class="abtn up" onclick=\'openCure('+K+','+I+')\'>'+(r.cure.kind==='sap'?'Upload SAP extract':'Upload document against this')+'</button></div>';
  }
  return h + '</div>';
}

/* ── dispositions ─────────────────────────────────────────────────────── */
function findResult(k, id){ return STATE[k].results.find(r=>r.id===id); }
window.doDisp = function(k, id, action){
  const o = findResult(k, id); if (!o || !may(action, o.status)) return;
  if (action==='uphold'){ record(k, id, 'uphold', '', ''); return; }
  const prompt = action==='waive' ? 'On what ground is the deficiency waived? State the facts relied upon.'
               : action==='correct' ? 'Where in the file or in SAP is this already evidenced? Record what you verified.' : 'Why is this being referred, and to whom?';
  const host = document.getElementById('df-'+id);
  host.innerHTML = '<div class="dispform"><label>'+prompt+'</label><textarea id="rz-'+esc(id)+'" placeholder="Recorded on the file and printed on the office copy."></textarea>'+
    (action==='waive' ? '<label>Rule, notification or authority relied upon</label><input type="text" id="au-'+esc(id)+'" placeholder="e.g. Rule 1.14, GP Fund Rules 1978, or the order relied upon">' : '')+
    '<div style="display:flex;gap:8px;align-items:center"><button class="abtn on" id="rec-'+esc(id)+'">Record</button><button class="abtn" id="can-'+esc(id)+'">Cancel</button>'+
    '<span class="src">Recorded against '+esc(OFFICER.desig)+' ('+esc(OFFICER.grade)+').</span></div></div>';
  document.getElementById('rec-'+id).onclick = ()=> record(k, id, action, document.getElementById('rz-'+id).value, action==='waive' ? document.getElementById('au-'+id).value : '');
  document.getElementById('can-'+id).onclick = ()=>{ host.innerHTML=''; };
};
window.record = function(k, id, action, reason, authority){
  const o = findResult(k, id);
  if (action!=='uphold' && !String(reason||'').trim()){ alert('A ground must be recorded first.'); return; }
  if (action==='waive' && !String(authority||'').trim()){ alert('The rule, notification or authority relied upon must be recorded before a waiver.'); return; }
  STATE[k].disp[id] = { action, reason:reason||'', authority:authority||'', by:OFFICER.name, desig:OFFICER.desig, grade:OFFICER.grade, at:stamp() };
  logAudit(k, {uphold:'Observation upheld', waive:'Observation waived on grounds', correct:'Observation settled in office', refer:'Observation referred upward'}[action],
    '['+o.code+'] '+(o.doc||o.title)+(reason?', ground: '+reason:'')+(authority?', authority: '+authority:''));
  keepScroll(()=>renderExam(k));
};
window.undoDisp = function(k, id){
  const o = findResult(k, id); delete STATE[k].disp[id];
  logAudit(k, 'Disposition withdrawn', '['+(o?o.code:id)+'] returned to open.');
  keepScroll(()=>renderExam(k));
};
window.upholdAllAdv = function(k){
  lists(STATE[k].results).adv.filter(o=>!STATE[k].disp[o.id]).forEach(o=>{
    STATE[k].disp[o.id] = { action:'uphold', reason:'', authority:'', by:OFFICER.name, desig:OFFICER.desig, grade:OFFICER.grade, at:stamp() };
  });
  logAudit(k, 'Advisory observations upheld together', 'Carried to the advisory memorandum.');
  keepScroll(()=>renderExam(k));
};
function keepScroll(fn){ const y = window.scrollY; fn(); window.scrollTo(0, y); }

/* ── verification ─────────────────────────────────────────────────────── */
window.doVerify = function(k, id, vid, ok){
  if (!may('verify')) return;
  const note = (document.getElementById('vn-'+id)||{}).value || '';
  if (!ok && !note.trim()){ alert('Record what did not verify before closing the task.'); return; }
  const r = findResult(k, id), F = STATE[k].F;
  F.verifications = F.verifications || {};
  F.verifications[vid] = { ok, note, by:OFFICER.name, desig:OFFICER.desig, grade:OFFICER.grade, at:stamp() };
  logAudit(k, ok ? 'Verification recorded' : 'Verification failed', (r ? r.doc||r.title : vid)+(note?': '+note:''));
  reprocess(k, (ok ? 'Verified: ' : 'Did not verify: ')+(r ? r.doc||r.title : vid));
  renderExam(k); window.scrollTo(0,0);
};

/* ── upload against an item, read, confirm, re-check ──────────────────── */
window.openCure = async function(k, id){
  const r = findResult(k, id); if (!r || !r.cure) return;
  if (r.cure.kind==='sap'){ renderSap(k); go(3); return; }
  const cure = r.cure;
  openModal('Upload against: '+(r.doc||r.title),
    '<p class="src" style="margin-top:0">'+esc(r.finding)+'</p>'+
    '<div class="drop" id="cdrop"><b>Choose the '+esc(cure.docType || 'document')+'</b><br>PDF or image. The file is hashed and kept with the case.</div><div id="cfile"></div><div id="cstep"></div>');
  const take = async file=>{
    const u = await registerUpload(k, file, (r.doc||r.title));
    $('cfile').innerHTML = '<div class="filerow">'+(u.url ? '<img class="thumbimg" src="'+u.url+'">' : '')+'<div><div class="fn">'+esc(u.name)+'</div><div class="src">'+fmtSize(u.size)+' · SHA-256 '+esc(u.hash.slice(0,32))+'...</div></div></div>';
    $('cdrop').style.display='none';
    readingStep(k, r, u, file);
  };
  $('cdrop').onclick = async ()=>{ const f = await pickFile('.pdf,.png,.jpg,.jpeg,.tif,.tiff'); if (f) take(f); };
};

function readingStep(k, r, u, file){
  const steps = ['Straighten and clean the page','Identify the document','Lift the fields'];
  let i = 0;
  $('cstep').innerHTML = '<div class="card" style="margin-top:12px"><div id="cread"></div></div>';
  const tick = ()=>{
    $('cread').innerHTML = steps.map((t,j)=>'<div class="stage '+(j<i?'ok':j===i?'run':'pend')+'"><div class="sic">'+(j<i?'✓':j+1)+'</div><div><div class="sn">'+t+'</div></div></div>').join('');
    if (i++ < steps.length) return setTimeout(tick, 380);
    confirmStep(k, r, u, file);
  };
  tick();
}

async function confirmStep(k, r, u, file){
  const cure = r.cure;
  let fields = (cure.fields || []).slice();
  let decoded = null;
  if (cure.kind==='qr'){
    if ('BarcodeDetector' in window && /^image\//.test(u.type)){
      try { const bmp = await createImageBitmap(file); const codes = await new BarcodeDetector({formats:['qr_code']}).detect(bmp); if (codes[0]) decoded = codes[0].rawValue; } catch(e){}
    }
    fields = [{k:'payload', label:'QR code reads', type:'text', expect: decoded || ''}, {k:'agrees', label:'Content agrees with the printed document', type:'yesno'}];
  }
  const inp = f => {
    if (f.type==='yesno') return '<select class="finput" id="cf-'+f.k+'"><option value="">choose</option><option value="yes">Yes</option><option value="no">No</option></select>';
    if (f.type==='select') return '<select class="finput" id="cf-'+f.k+'">'+f.options.map(o=>'<option>'+esc(o)+'</option>').join('')+'</select>';
    return '<input class="finput" type="text" id="cf-'+f.k+'" value="'+esc(f.expect||'')+'">';
  };
  $('cstep').innerHTML = '<div class="card" style="margin-top:12px"><h3>Confirm what the document shows</h3>'+
    '<p class="hint">'+(decoded ? 'The QR code was decoded by the browser. ' : '')+'In production the reading stage fills these from the page with a confidence and the page region. In this prototype the officer confirms them from the uploaded document.'+
    (fields.some(f=>f.expect) ? ' Pre-filled values are what the case expects; change them if the document shows otherwise.' : '')+'</p>'+
    fields.map(f=>'<label class="flabel" for="cf-'+f.k+'">'+esc(f.label)+'</label>'+inp(f)).join('')+
    '<div class="actionbar"><button class="btn" id="capply">Apply and re-check the case</button><span class="src">The rules decide whether the item is now satisfied.</span></div></div>';
  $('capply').onclick = ()=>{
    const vals = {}; fields.forEach(f=>{ vals[f.k] = $('cf-'+f.k).value.trim(); });
    if (fields.some(f=>f.type==='yesno' && !vals[f.k])){ alert('Answer every yes / no question.'); return; }
    const F = STATE[k].F;
    if (cure.kind==='qr'){
      F.verifications = F.verifications || {};
      F.verifications['QR:'+cure.qid] = { ok: vals.agrees==='yes', note:'Uploaded '+u.name+'. QR reads: '+(vals.payload||'(not entered)'), by:OFFICER.name, desig:OFFICER.desig, grade:OFFICER.grade, at:stamp() };
    } else if (CURES[cure.apply]) {
      CURES[cure.apply](F, vals, u.name);
    }
    logAudit(k, 'Uploaded document read and confirmed', u.name+' against '+(r.doc||r.title)+': '+Object.keys(vals).map(x=>x+'='+vals[x]).join(', '));
    reprocess(k, 'Document uploaded against '+(r.doc||r.title));
    $('modal').classList.remove('on');
    renderExam(k); window.scrollTo(0,0);
  };
}
