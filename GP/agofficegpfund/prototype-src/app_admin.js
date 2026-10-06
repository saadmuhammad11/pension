/* ═══════════════════════════════════════════════════════════════════════
   DOA REGISTER and RULES IN FORCE, plus start-up
   ═══════════════════════════════════════════════════════════════════════ */
function doaCases(a){
  const out = [];
  ORDER.forEach(k=>(CASES[k].signatures||[]).forEach(g=>{ if (doaScore(g.authority, a.authority) >= 0.6) out.push(CASES[k].label); }));
  return Array.from(new Set(out));
}
function renderDoa(){
  const edit = OFFICER.level >= 2, dag = OFFICER.level >= 3;
  let h = '<h1 class="pagetitle">Delegation of authority register</h1><p class="pagesub">Who may sign, for or on behalf of each department authority, with specimen signatures. Every signature for an authority in a case is looked up here.</p>' +
    '<div class="notice ' + (DOA.status==='final' ? 'ok' : 'gold') + '"><b>' + (DOA.status==='final' ? 'Register marked final.' : 'Provisional register.') + '</b> ' + esc(DOA.version) +
    (DOA.status==='final' ? ' A signatory not on the register now raises a hard stop.' : ' While provisional, a signatory not on the register creates a verification task, never a hard stop.') + '</div>';
  if (dag) h += '<div class="actionbar" style="margin:-4px 0 14px"><button class="btn ghost small" id="doafinal">' + (DOA.status==='final' ? 'Mark register provisional again' : 'Mark register final (office list received)') + '</button></div>';
  DOA.authorities.forEach(a=>{
    const cs = doaCases(a);
    h += '<div class="card"><h3>' + esc(a.authority) + '</h3><p class="hint">' + esc(a.dept) + ' · seen in: ' + esc(a.source) + (cs.length ? ' · cases: ' + esc(cs.join(', ')) : '') + '</p>' +
      '<div class="tscroll"><table><tr><th>Signatory</th><th>Powers</th><th style="width:110px">Signs for</th><th style="width:230px">Specimen</th></tr>' +
      a.signatories.map(g=>'<tr><td class="fv">' + esc(g.post) + (g.name ? '<div class="src">' + esc(g.name) + '</div>' : '') + '</td><td class="src">' + esc(g.powers||'') + '</td><td>' + (g.mayFor ? 'Yes, for the authority' : 'In own name') + '</td><td>' +
        (g.specimen ? '<img src="' + g.specimen.url + '" style="max-height:60px;max-width:200px;border:1px solid var(--line)"><div class="src">' + esc(g.specimen.by) + ', ' + esc(g.specimen.at) + '</div>' : '<span class="blank">awaited from the office</span>') +
        (edit ? '<div><button class="abtn up" style="margin-top:5px" onclick=\'uploadSpecimen(' + JSON.stringify(a.id) + ',' + JSON.stringify(g.id) + ')\'>' + (g.specimen ? 'Replace' : 'Upload') + ' specimen</button></div>' : '') + '</td></tr>').join('') +
      '</table></div>' + (dag ? '<div class="act"><button class="abtn" onclick=\'addSignatory(' + JSON.stringify(a.id) + ')\'>Add signatory</button></div><div id="adds-' + esc(a.id) + '"></div>' : '') + '</div>';
  });
  if (!edit) h += '<div class="src">Uploading specimens requires the Accounts Officer or above; adding signatories requires the DAG (Funds).</div>';
  $('sdoabody').innerHTML = h;
  if ($('doafinal')) $('doafinal').onclick = ()=>{ DOA.status = DOA.status==='final' ? 'provisional' : 'final'; afterDoaChange('DOA register marked ' + DOA.status); };
}
function afterDoaChange(why){
  if (sel && STATE[sel]){ logAudit(sel, 'DOA register changed', why); reprocess(sel, why); }
  renderDoa();
}
window.uploadSpecimen = async function(aid, gid){
  const f = await pickFile('.png,.jpg,.jpeg'); if (!f) return;
  const url = await new Promise(r=>{ const fr = new FileReader(); fr.onload = ()=>r(fr.result); fr.readAsDataURL(f); });
  const g = DOA.authorities.find(a=>a.id===aid).signatories.find(x=>x.id===gid);
  g.specimen = { url, name:f.name, by:OFFICER.name, at:stamp() };
  afterDoaChange('Specimen uploaded for ' + g.post);
};
window.addSignatory = function(aid){
  const host = document.getElementById('adds-' + aid);
  host.innerHTML = '<div class="dispform"><div class="row3"><div><label>Post</label><input type="text" id="ns-post"></div><div><label>Name</label><input type="text" id="ns-name"></div><div><label>Powers</label><input type="text" id="ns-pow"></div></div>' +
    '<label class="chk"><input type="checkbox" id="ns-for"> <span>May sign for the authority</span></label><button class="abtn on" id="ns-go">Add to register</button></div>';
  document.getElementById('ns-go').onclick = ()=>{
    const post = document.getElementById('ns-post').value.trim(); if (!post){ alert('Enter the post.'); return; }
    DOA.authorities.find(a=>a.id===aid).signatories.push({ id:'s' + Date.now(), post, name:document.getElementById('ns-name').value.trim(), powers:document.getElementById('ns-pow').value.trim(), mayFor:document.getElementById('ns-for').checked, specimen:null });
    afterDoaChange('Signatory added: ' + post);
  };
};

const OFFICE_RULES = [
  ['R1','SAP extracts','Pay slip and GPF Final Re-calculation Report marked off when in the case; otherwise a SAP item for the section, uploaded straight after initial processing.','Consistent with Rule 1.40 and the 1985 office order: the balance is the office’s own record.'],
  ['R2','Cure by upload','Every observation and verification task takes a document; the whole case is re-checked and a new version recorded.','Supports Rule 1.35 Explanation: pay the undisputed portion promptly.'],
  ['R3','Covering letter','Accepted in every case, never an observation.','Rules require the claimant’s application (Rule 1.35(4)); that is still checked (Form 10).'],
  ['R4','Delegation of authority','Signatures for an authority looked up in the DOA register; specimen compared by the officer.','Appendix-IV (1983, item 3 substituted 2000) names authorities; the office register refines it.'],
  ['R5','Attestation','Unattested CNIC copies and pay slips noted only.','The Rules do not require attestation.'],
  ['R6','Form 5 and Form 6-B','Personal number tallies with the pay slip; signatures compared with the CNIC; other fields not examined.','Forms PAY 05 and 06 are not in the 1978 Rules; they rest on the circular.'],
  ['R7','Thumb impressions','Detected and routed to NADRA biometric verification or attesting officer; not matched by the module.','Tested on the corpus: not feasible from the papers.'],
  ['R8','SAP pay slip','Manual upload now; connector later, same data contract.',''],
  ['R9','80% of SAP balance','FLAG. The module applies the limits the Rules set for the clause quoted and shows the office’s 80% beside them.','Rules: 1.14(1)(c)(i) 50% or 3 months’ pay; 1.14(1)(d)(i) 80% or 24 months’ pay; 1.14(1)(e) 50%; 1.15(b),(c) 80%; 1.15(d) 80% or 12 months’ pay, whichever is more; 1.16 100%.'],
  ['R10','QR codes','Every code scanned; content compared with the document; portal links verified where reachable. Unreadable or unverifiable codes are observations.',''],
  ['R11','Final payment extracts','Pay slip and re-calculation report required; the claim is reconciled to the report.','Consistent with the 1985 office order.'],
  ['R12','One advance at a time','Earlier refundable advances must be fully recovered in SAP before a new one.','1989 proviso to Rule 1.14(1)(c) agrees. Rule 1.14(1)(c)(ii) adds a twelve-month gap in some cases: open item.'],
  ['R13','OSD post','OSD post on the SAP pay slip removes the succession certificate requirement.','Not in the Rules; Provident Funds Act s.4 still needs a certificate for non-family payees over Rs 5,000.'],
  ['R14','Non-gazetted missing credits','Bank-stamped challans with Treasury verification stand in for the DDO certificate.','Rule 1.40(3)(ii) splits at BS 1-15, not by gazetted status.'],
  ['R15','Gazetted missing credits','Bank-stamped challans verified by the Treasury stand in for the AG certificate.','Rule 1.40(3)(i) already names the Treasury Officer as a certifier.']
];
const OPEN_ITEMS = [
  ['GPF-O14','DOA register and specimen signatures for every department that signs GP Fund documents (R4).'],
  ['GPF-O15','Advance limits (FLAG): the Finance Department notification, if any, that set 80% for temporary advances; whether 80% overrides Rule 1.16’s 100% at age 50; the amendment mark on Rule 1.15(d).'],
  ['GPF-O16','Second advance timing: "after the month the earlier advance reached zero" (R12) against the twelve-month gap in Rule 1.14(1)(c)(ii); whether SAP still charges interest on advances (Rule 1.19(4)).'],
  ['GPF-O17','OSD post (R13): the instruction behind it and the SAP field that shows it.'],
  ['GPF-O18','Confirm that "Form 6-B" is FORM PAY 06 as it appears in the cases.'],
  ['GPF-O19','SAP access for the connector: RFC/BAPI, OData or a BDC recording; the transaction or report names for the pay slip and the GPF Final Re-calculation Report; a read-only service account.'],
  ['GPF-O20','QR verification portals: NADRA e-FRC returned access denied; the Punjab e-Stamp portal verified. Whether the air-gapped system may reach portals through a gateway.'],
  ['GPF-O21','Missing credits split: gazetted status (circular) against BS-16 (Rule 1.40(3)).'],
  ['GPF-O22','Thumb impressions: route to NADRA biometric verification (bank BVS or e-Sahulat slip) as the curing document.'],
  ['GPF-O23','Death cases: whether the QR-linked NADRA family registration certificate substitutes for heirs’ CNIC copies, and whether an adult son who takes no share under Rule 1.34 must still supply one; subscriptions and interest after death against an OSD post.'],
  ['GPF-O24','Service Book: how the section records that the original was physically received, so entries are checked on the original rather than the scan.'],
  ['GPF-O25','Missing credits: whether a Treasury-verified schedule row stands in for a missing challan copy, and whether proven months may be credited while one is held.'],
  ['GPF-O26','Whether R4 reaches the signatory of a forwarding endorsement that forms part of a substantive form (GPF-10 DDO block, DAO confirmation), given R3.'],
  ['GPF-O1','Blank claim rejection form attached to the circular.'],
  ['GPF-O3','Employee Service Portal integration contract.'],
  ['GPF-O4','Checklist governing residual payment.'],
  ['GPF-O6','Rejection reasons for balance transfer and missing credits.'],
  ['GPF-O13','Delegation bands inside this office.']
];
function renderRules(){
  let h = '<h1 class="pagetitle">Rules in force</h1><p class="pagesub">Rule set of 15-09-2026. Circular No. G.P. Fund-I (Coord)/TR/127 of 21.12.2023, the Punjab GP Fund Rules 1978 (Compendium 2008), and the office’s clarifications of 15-09-2026. A case is always re-checked against the rule set in force when it was examined.</p>';
  h += '<div class="card"><h3>Office clarifications of 15-09-2026</h3><div class="tscroll"><table><tr><th style="width:44px">Ref</th><th style="width:170px">Clarification</th><th>How the module applies it</th><th>Position in the Rules</th></tr>' +
       OFFICE_RULES.map(r=>'<tr' + (r[0]==='R9' ? ' class="hl"' : '') + '><td class="mono">' + r[0] + '</td><td class="fv">' + esc(r[1]) + '</td><td>' + esc(r[2]) + '</td><td class="src">' + esc(r[3]) + '</td></tr>').join('') + '</table></div></div>';
  h += '<div class="card"><h3>Advance limits in the GP Fund Rules</h3><p class="hint">Applied by clause. The office’s stated 80% is shown beside every result and flagged where it differs.</p><div class="tscroll"><table><tr><th>Clause</th><th>Advance</th><th class="n">Share of balance</th><th class="n">Months of pay</th><th>Governs</th></tr>' +
       Object.values(ADV_LIMITS).map(L=>'<tr' + (L.pct !== PARAMS.officeCapPct ? ' class="hl"' : '') + '><td class="mono">' + esc(L.src) + '</td><td>' + esc(L.label) + (L.minAge ? '<div class="src">Age ' + L.minAge + ' or over</div>' : '') + '</td><td class="n mono">' + L.pct + '%</td><td class="n mono">' + (L.months||'') + '</td><td>' + (L.combine ? (L.combine==='max' ? 'greater of the two' : 'lesser of the two') : 'share of balance') + '</td></tr>').join('') +
       '</table></div><div class="notice gold" style="margin-top:12px"><b>Flag.</b> The office stated that a sanctioned advance must be at most 80% of the SAP balance. The Rules set 80% only for house and land advances and some non-refundable advances; a general temporary advance is capped at half the balance or three months’ pay, and Rule 1.16 allows 100% at age 50. Open item GPF-O15.</div></div>';
  h += '<div class="card"><h3>Thumb impressions</h3><p>Tested on every thumb impression and CNIC copy in the eight cases. Smart CNICs carry no fingerprint, the two people who thumbed forms both hold smart cards, and even the clearest ink impressions did not separate same-person from different-person pairs. Matching from the case papers is not possible. The module records each impression and asks for NADRA biometric verification or the attesting officer’s certificate.</p></div>';
  h += '<div class="card"><h3>Open items for the AG Office</h3><table>' + OPEN_ITEMS.map(o=>'<tr><td class="mono" style="width:80px">' + o[0] + '</td><td>' + esc(o[1]) + '</td></tr>').join('') + '</table></div>';
  $('srulesbody').innerHTML = h;
}

$('lnkDoa').onclick = ()=>{ renderDoa(); go('doa'); };
$('lnkRules').onclick = ()=>{ renderRules(); go('rules'); };
document.querySelectorAll('.step').forEach(el=>{
  el.onclick = ()=>{
    const n = +el.dataset.s;
    if (n===1){ renderIntake(); go(1); return; }
    if (!sel || !STATE[sel] || !STATE[sel].results.length) return;
    if (n===3){ renderSap(sel); go(3); }
    if (n===4){ renderExam(sel); go(4); }
    if (n===5){ renderDisposal(sel); go(5); }
    if (n===6 && STATE[sel].issued){ renderIssue(sel); go(6); }
  };
});
renderIntake();
go(1);
