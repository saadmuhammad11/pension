/* ═══════════════════════════════════════════════════════════════════════
   SCREEN 5: disposal of the case   ·   SCREEN 6: issue and record
   ═══════════════════════════════════════════════════════════════════════ */
const DISPOSALS = [
  { id:'return', n:'Return to the department for compliance', d:'Issue the claim rejection form with every upheld observation, in one instance, as para 2 of the circular requires.' },
  { id:'pass', n:'Pass for payment', d:'No hard stop, verification task or SAP item outstanding. The case goes to the GP Fund Payment Register and to payment.' },
  { id:'part', n:'Pass for part payment, balance withheld', d:'Release the undisputed portion now and hold the rest (Rule 1.35, Explanation). Used where the objection touches only part of the amount.' },
  { id:'refer', n:'Refer to the Deputy Accountant General (Funds)', d:'For a second return, for waiver of a hard stop, or where the case turns on a question above this desk.' },
  { id:'hold', n:'Hold pending verification', d:'Awaiting SAP, NADRA, the Treasury, a portal check or the department. It ages on the pendency report instead of sitting unnoticed.' }
];

function upheldObs(k){ const s = STATE[k]; return lists(s.results).obs.filter(o=>{ const d = s.disp[o.id]; return !d || d.action==='uphold' || d.action==='refer'; }); }
function settledObs(k){ const s = STATE[k]; return lists(s.results).obs.filter(o=>{ const d = s.disp[o.id]; return d && (d.action==='waive' || d.action==='correct'); }); }

function renderDisposal(k){
  const s = STATE[k], F = s.F, p = position(k), L = lists(s.results);
  let h = '<h1 class="pagetitle">Disposal of the case</h1><p class="pagesub">' + esc(F.subject) + ' · ' + plural(p.hard,'hard stop') + ' outstanding, ' + p.waived + ' waived, ' + p.corrected + ' settled in office, ' +
          plural(L.conf.length,'verification task') + ', ' + plural(L.sap.length,'SAP item') + '.</p>';
  if (p.open > 0) h += '<div class="notice gold"><b>' + plural(p.open,'observation') + ' still open.</b> Every observation must be disposed of before the case leaves this desk. Go back and uphold, waive, settle, refer or cure each one.</div>';
  const second = s.returns >= 1;
  if (second) h += '<div class="notice red"><b>Second return.</b> Under para 3 of the circular it may not be returned again until the DAG (Funds) / DAO I has reviewed and signed it. ' +
                   (OFFICER.level >= 3 ? 'You hold that office.' : 'Refer it to the DAG, or switch to the DAG to countersign.') + '</div>';
  h += '<div class="card"><h3>How is the case to be disposed of?</h3><p class="hint">The module never disposes of a case. It presents the position; an authorised officer decides.</p>';
  DISPOSALS.forEach(dz=>{
    let why = '';
    if (dz.id==='return' && p.hard === 0 && !upheldObs(k).length) why = 'Nothing to return the case for.';
    if (dz.id==='return' && second && OFFICER.level < 3) why = 'A second return requires the signature of the DAG (Funds) / DAO I.';
    if (dz.id==='pass'){
      const blocks = [];
      if (p.hard) blocks.push(plural(p.hard,'hard stop'));
      if (L.conf.length) blocks.push(plural(L.conf.length,'verification task'));
      if (L.sap.length) blocks.push(plural(L.sap.length,'SAP item'));
      if (blocks.length) why = 'Cannot pass for payment while ' + blocks.join(', ') + ' remain' + (blocks.length===1 && /^1 /.test(blocks[0]) ? 's' : '') + ' open.';
      else if (OFFICER.level < 2) why = 'Passing for payment is reserved to the Accounts Officer or above.';
    }
    if (dz.id==='part' && OFFICER.level < 2) why = 'Part payment is reserved to the Accounts Officer or above.';
    const on = s.caseDisp === dz.id;
    h += '<div class="dchoice' + (on?' sel':'') + (why?' disabled':'') + '" ' + (why ? '' : 'onclick=\'pickDisposal(' + JSON.stringify(k) + ',' + JSON.stringify(dz.id) + ')\'') + '>' +
         '<div class="dn">' + dz.n + '</div><div class="dd">' + dz.d + '</div>' + (why ? '<div class="dd" style="color:var(--amber);margin-top:5px">' + why + '</div>' : '') + '</div>';
  });
  h += '<div id="dispnote"></div></div>';
  const up = upheldObs(k), st2 = settledObs(k);
  h += '<div class="cols"><div class="card"><h3>' + (p.hard ? 'Will appear on the rejection form' : 'Will appear on the advisory memorandum') + '</h3><p class="hint">' + plural(up.length,'observation') + ', issued in one instance.</p>' +
       (up.length ? '<ul style="margin:0;padding-left:18px;font-size:13px">' + up.map(o=>'<li style="margin-bottom:5px"><span class="mono">' + esc(o.code) + '</span>, ' + esc(o.doc||o.title) + '</li>').join('') + '</ul>' : '<div class="src">Nothing to issue to the department.</div>') +
       '</div><div class="card"><h3>Retained on the office copy only</h3><p class="hint">Disposed of in office, recorded on the half the circular requires this office to keep.</p>' +
       (st2.length ? '<ul style="margin:0;padding-left:18px;font-size:13px">' + st2.map(o=>'<li style="margin-bottom:5px"><span class="mono">' + esc(o.code) + '</span>, ' + esc(o.doc||o.title) + '<br><span class="src">' + (s.disp[o.id].action==='waive'?'Waived':'Settled') + ' by ' + esc(s.disp[o.id].desig) + '</span></li>').join('') + '</ul>' : '<div class="src">Nothing waived or settled.</div>') +
       '</div></div>';
  if (L.conf.length || L.sap.length) h += '<div class="notice slate"><b>Still open for this office:</b> ' + L.conf.concat(L.sap).map(r=>esc(r.doc||r.title)).join('; ') + '.</div>';
  h += '<div class="actionbar"><button class="btn" id="toissue" ' + ((s.caseDisp && p.open===0 && s.dispConfirmed) ? '' : 'disabled') + '>Record disposal &amp; issue</button><button class="btn ghost" id="back4">Back to examination</button></div>';
  $('s5body').innerHTML = h;
  $('back4').onclick = ()=>{ renderExam(k); go(4); };
  $('toissue').onclick = ()=>{ s.issued = true; logAudit(k,'Pack issued','Disposal: ' + (DISPOSALS.find(d=>d.id===s.caseDisp)||{}).n + '.'); renderIssue(k); go(6); };
  if (s.caseDisp) showDispNote(k);
}
window.pickDisposal = function(k, id){ const s = STATE[k]; s.caseDisp = id; s.dispConfirmed = false; renderDisposal(k); };
function showDispNote(k){
  const s = STATE[k], dz = DISPOSALS.find(d=>d.id===s.caseDisp);
  $('dispnote').innerHTML = '<div class="dispform" style="margin-top:12px"><label for="cdnote">Officer’s note on the disposal, printed on the office copy</label>' +
    '<textarea id="cdnote" placeholder="Optional, but recorded where entered.">' + esc(s.caseNote||'') + '</textarea>' +
    (s.dispConfirmed ? '<div class="recorded"><b>Recorded:</b> ' + esc(dz.n) + '</div>' : '<button class="abtn on" id="cdgo">Confirm: ' + esc(dz.n) + '</button>') + '</div>';
  if ($('cdgo')) $('cdgo').onclick = ()=>{
    s.caseNote = $('cdnote').value; s.dispConfirmed = true;
    logAudit(k, 'Case disposal recorded', dz.n + (s.caseNote ? ', note: ' + s.caseNote : ''));
    if (s.caseDisp === 'return') s.returns = (s.returns||0) + 1;
    renderDisposal(k);
  };
}

function formMeta(k, fifth){
  const s = STATE[k], F = s.F;
  return '<div class="rfmeta"><div><div class="l">Subscriber</div>' + esc(F.subject) + '</div><div><div class="l">Personnel / GP Fund A/c</div><span class="mono">' + esc(F.personnelNo) + '</span></div>' +
         '<div><div class="l">Case type</div>' + esc(F.label) + '</div><div><div class="l">Diary no.</div><span class="mono">' + esc(s.dak.no) + '</span><br><span class="src">' + esc(s.dak.date) + '</span></div>' +
         '<div><div class="l">' + fifth[0] + '</div>' + fifth[1] + '</div></div>';
}
function obsTable(list, withSev){
  return '<div class="tscroll"><table><tr><th style="width:34px">#</th><th style="width:88px">Clause</th><th>Document, defect and remedy</th>' + (withSev ? '<th style="width:96px">Severity</th>' : '') + '</tr>' +
    list.map((o,n)=>'<tr><td class="mono">' + (n+1) + '</td><td class="mono">' + esc(o.code) + '</td><td><div class="fv">' + esc(o.doc||o.title) + '</div><div style="margin-top:3px">' + esc(o.finding) + '</div>' +
      (o.remedy ? '<div style="margin-top:4px;color:var(--green2)"><b>Remedy:</b> ' + esc(o.remedy) + '</div>' : '') + '<div class="src" style="margin-top:3px">' + esc(clauseText(o.code)) + '</div></td>' +
      (withSev ? '<td>' + vd(o.status, o.status==='hard' ? 'Hard stop' : 'Observation') + '</td>' : '') + '</tr>').join('') + '</table></div>';
}

function renderIssue(k){
  const s = STATE[k], F = s.F, L = lists(s.results), dz = DISPOSALS.find(d=>d.id===s.caseDisp) || { n:'(not recorded)' };
  const up = upheldObs(k), st2 = settledObs(k), returning = s.caseDisp === 'return';
  let h = '<h1 class="pagetitle">' + (returning ? 'Claim rejection form, office record and register' : 'Office record and register') + '</h1>' +
          '<p class="pagesub">The single-instance output required by para 2 of the circular, the office record of every decision, and the GP Fund Payment Register entry directed at C(i).</p>';
  if (returning){
    h += '<div class="rform"><div class="rfhead"><div class="o1">Office of the Accountant General Punjab</div><div class="o2">Claim Rejection Form. GP Fund</div>' +
         '<div class="o3">Issued under Office Circular No. G.P. Fund-I (Coord)/TR/127 dated 21.12.2023, para 2</div></div>' + formMeta(k, ['Return', s.returns + (s.returns===1?'st':s.returns===2?'nd':'th') + ' return']) +
         '<div class="rfbody"><div class="notice ' + (s.returns>1?'red':'gold') + '" style="margin-bottom:15px"><b>Returned for compliance: ' + plural(up.length,'observation') + ' to be removed.</b> ' +
         (s.returns>1 ? 'This return carries the signature of the DAG (Funds) / DAO I, as para 3 requires.' : 'A second return will require the review and signature of the DAG (Funds) / DAO I under para 3.') + '</div>' +
         obsTable(up, true) + '<div style="margin-top:14px;font-size:12.5px;color:var(--muted)">All observations are raised in this single instance. Each can be cured by sending the document named in the remedy; the case is then re-checked against the same rules.</div></div>' +
         '<div class="tearline">Retain the portion below in office</div><div class="rfsig"><div class="sigbox"><div class="sigline"></div>' + (s.returns>1 ? 'Deputy Accountant General (Funds) / DAO I' : 'Accounts Officer, GP Fund Section') +
         '<br><span class="src">' + esc(OFFICER.name) + ', ' + esc(OFFICER.desig) + ' (' + esc(OFFICER.grade) + ')</span></div><div class="sigbox"><div class="sigline"></div>Received on behalf of the department<br><span class="src">Name, designation and date</span></div></div></div>';
  } else {
    h += '<div class="notice ok"><b>' + esc(dz.n) + '.</b> No rejection form issues on this case. The office record and register entry below carry the decision and the grounds.</div>';
    if (up.length) h += '<div class="rform" style="margin-top:16px"><div class="rfhead"><div class="o1">Office of the Accountant General Punjab</div><div class="o2">Advisory Memorandum. GP Fund</div>' +
      '<div class="o3">Issued with the case. The case is not returned; these matters are to be put right on the department’s record.</div></div>' + formMeta(k, ['Disposal', esc(dz.n)]) +
      '<div class="rfbody">' + obsTable(up, false) + '</div><div class="tearline">Retain the portion below in office</div><div class="rfsig"><div class="sigbox"><div class="sigline"></div>Accounts Officer, GP Fund Section<br><span class="src">' +
      esc(OFFICER.name) + ', ' + esc(OFFICER.desig) + '</span></div><div class="sigbox"><div class="sigline"></div>Received on behalf of the department<br><span class="src">Name, designation and date</span></div></div></div>';
  }
  if (st2.length) h += '<div class="card" style="margin-top:16px"><h3>Office copy: observations disposed of without returning the case</h3><div class="tscroll"><table><tr><th style="width:88px">Clause</th><th>Document and ground</th><th style="width:170px">Officer</th></tr>' +
    st2.map(o=>{ const d = s.disp[o.id]; return '<tr><td class="mono">' + esc(o.code) + '</td><td><div class="fv">' + esc(o.doc||o.title) + '</div><div class="src">' + (d.action==='waive'?'Waived':'Settled in office') + ': ' + esc(d.reason) + '</div>' +
      (d.authority ? '<div class="src"><b>Authority:</b> ' + esc(d.authority) + '</div>' : '') + '</td><td><div class="fv" style="font-size:12.5px">' + esc(d.by) + '</div><div class="src">' + esc(d.desig) + '<br>' + esc(d.grade) + ' · ' + esc(d.at) + '</div></td></tr>'; }).join('') + '</table></div></div>';
  const ver = Object.entries(F.verifications||{});
  h += '<div class="card"><h3>Verifications recorded</h3>' + (ver.length ? '<div class="tscroll"><table><tr><th>Item</th><th>Result</th><th>Officer</th></tr>' +
    ver.map(([id,v])=>'<tr><td class="mono" style="font-size:11.5px">' + esc(id) + '</td><td>' + vd(v.ok?'ok':'hard', v.ok?'Verified':'Did not verify') + '<div class="src">' + esc(v.note||'') + '</div></td><td>' + esc(v.by) + '<div class="src">' + esc(v.desig) + ' · ' + esc(v.at) + '</div></td></tr>').join('') + '</table></div>'
    : '<div class="src">None recorded.</div>') + (L.conf.length ? '<div class="notice slate" style="margin-top:10px">Still open: ' + L.conf.map(r=>esc(r.doc||r.title)).join('; ') + '.</div>' : '') + '</div>';
  h += '<div class="card"><h3>SAP extracts and documents relied on</h3><p class="hint">' + (F.sap ? 'SAP extracts: ' + (F.sap.source==='case' ? 'found in the case' : 'uploaded, ' + esc(F.sap.file)) : 'No SAP extract on the case.') + '</p>' +
    (s.uploads.length ? '<div class="tscroll"><table class="compact"><tr><th>File</th><th>Against</th><th>SHA-256</th></tr>' + s.uploads.map(u=>'<tr><td>' + esc(u.name) + '</td><td>' + esc(u.against) + '</td><td class="mono" style="font-size:11px;word-break:break-all">' + esc(u.hash) + '</td></tr>').join('') + '</table></div>' : '<div class="src">No documents uploaded on this case.</div>') + '</div>';
  h += '<div class="card"><h3>Audit trail</h3><p class="hint">Every action on this case, with officer, designation, grade and time. Entries cannot be altered or removed.</p>' +
    s.audit.map(a=>'<div class="aud"><div class="audt">' + esc(a.at) + '</div><div class="audw">' + esc(a.by) + '<span>' + esc(a.desig) + ' · ' + esc(a.grade) + '</span></div><div><div class="fv" style="font-size:13px">' + esc(a.what) + '</div>' +
      (a.detail ? '<div class="src" style="margin-top:2px">' + esc(a.detail) + '</div>' : '') + '</div></div>').join('') + '</div>';
  h += '<div class="card"><h3>GP Fund Payment Register</h3><p class="hint">Direction C(i) of the circular.</p><div class="tscroll"><table><tr><th>Diary</th><th>Subscriber</th><th>Personnel no.</th><th>Case type</th><th>Version</th><th>Disposal</th><th>Officer</th></tr>' +
    '<tr><td class="mono">' + esc(s.dak.no) + '</td><td class="fv">' + esc(F.subject) + '</td><td class="mono">' + esc(F.personnelNo) + '</td><td>' + esc(F.label) + '</td><td>' + s.version + '</td><td>' + esc(dz.n) + '</td><td>' + esc(OFFICER.desig) + '<br><span class="src">' + stamp() + '</span></td></tr></table></div></div>';
  h += '<div class="card"><h3>Employee Service Portal, comment entry</h3><p class="hint">Para 2 requires observations to be recorded in the comment section of the tracking system.</p><code class="esp">' + esc(espText(k, up)) + '</code></div>';
  h += '<div class="actionbar noprint"><button class="btn ghost" id="back5">Back to disposal</button><button class="btn ghost" onclick="window.print()">Print the pack</button><button class="btn ghost" onclick="renderIntake();go(1)">Take another case</button></div>' +
       '<div class="footnote">Prototype for discussion. Prepared by TMC for the Office of the Accountant General, Punjab. Checklist items and rejection codes from Office Circular No. G.P. Fund-I (Coord)/TR/127 of 21.12.2023; limits from the Punjab GP Fund Rules 1978 (Compendium 2008); office clarifications of 15-09-2026.</div>';
  $('s6body').innerHTML = h;
  $('back5').onclick = ()=>{ renderDisposal(k); go(5); };
}
function espText(k, up){
  const s = STATE[k], F = s.F, dz = DISPOSALS.find(d=>d.id===s.caseDisp) || { n:'(not recorded)' };
  let t = 'GP FUND PRE-AUDIT, OBSERVATIONS (single instance)\nCase: ' + F.subject + ' | Personnel no. ' + F.personnelNo + ' | ' + F.label + '\nDiary: ' + s.dak.no + ' | Version ' + s.version + ' | Returns: ' + s.returns + ' | Disposal: ' + dz.n + '\n\n';
  if (!up.length) t += 'No observation issued to the department.\n';
  up.forEach((o,n)=>{ t += (n+1) + '. [' + o.code + '] ' + (o.doc||o.title) + '\n   ' + o.finding + '\n' + (o.remedy ? '   REMEDY: ' + o.remedy + '\n' : ''); });
  return t + '\nIssued by ' + OFFICER.name + ', ' + OFFICER.desig + ', under Circular G.P. Fund-I (Coord)/TR/127.';
}
