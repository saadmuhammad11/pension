/* ═══════════════════════════════════════════════════════════════════════
   RULE CATALOGUE, PART 2: rules by case family
   ═══════════════════════════════════════════════════════════════════════ */
const PARAMS = {
  advanceCapPct: 80,                 /* R9, office practice. Rule 1.14(1)(c)(i) text differs: open item */
  claimTolerance: 1                  /* rupees */
};
const D = F => F.docs || {};
const docCure = (docType, apply, fields) => ({ kind:'doc', docType, apply, fields: fields || [] });
const yes = v => v === true || v === 'yes';

/* ── Advances: refundable and non-refundable ───────────────────────────── */
check({ id:'ADV-SANCTION', group:'checklist', checklist:'A1-i', ref:'A1-i · B1-ii', code:'B1-ii', title:'Original sanction of the competent authority',
  applies: F => KIND(F, ...ADVANCES),
  run: F => {
    const s = D(F).sanction;
    if (s && s.present) return { status:'ok', finding:'Sanction No. ' + (s.orderNo||'(not stated)') + ' dated ' + (s.date||'(not stated)') + ' of ' + (s.printedAuthority||s.dept) +
      ', page ' + s.page + ', for Rs ' + fmt(s.amount) + '. The signatory is checked against the DOA register below.', evidence:[ev(s.page, 'Sanction', s.crop)] };
    return { status:'hard', finding:'No original sanction is on file.', remedy:'Produce the original sanction of the competent authority.',
             cure: docCure('Original sanction', 'add-sanction', [{k:'orderNo',label:'Order no.',type:'text'},{k:'date',label:'Date',type:'text'},{k:'amount',label:'Amount sanctioned (Rs)',type:'number'},{k:'rule',label:'Rule quoted',type:'text'}]) };
  }});

check({ id:'ADV-RULE', group:'checklist', ref: 'B1-iv · B2-ix', title:'Rule and reason quoted on the sanction',
  code: 'B1-iv',
  applies: F => KIND(F, ...ADVANCES) && D(F).sanction && D(F).sanction.present,
  run: F => {
    const s = D(F).sanction, code = KIND(F,'refundable') ? 'B1-iv' : 'B2-ix';
    const needReason = KIND(F,'refundable');
    if (s.rule && (!needReason || s.reason)) return { status:'ok', code, finding:'Rule quoted: ' + s.rule + (s.reason ? '. Reason: ' + s.reason + '.' : '.'), evidence:[ev(s.page,'Sanction')] };
    return { status:'hard', code, finding: !s.rule ? 'The sanction does not quote the rule under which the advance is granted.' : 'The sanction does not state the reason for the advance.',
             remedy:'Obtain a sanction quoting the rule' + (needReason ? ' and the reason for the advance.' : '.'), evidence:[ev(s.page,'Sanction')],
             cure: docCure('Revised sanction', 'set-sanction-rule', [{k:'rule',label:'Rule quoted',type:'text'},{k:'reason',label:'Reason stated',type:'text'}]) };
  }});

check({ id:'ADV-CNIC', group:'checklist', checklist:'A1-ii', ref:'A1-ii · R5', title:'Copy of CNIC of the subscriber',
  applies: F => KIND(F, ...ADVANCES),
  run: F => {
    const c = (D(F).cnics || []).find(x=>(x.whose||'subscriber') === 'subscriber');
    if (c) return { status:'ok', finding:'CNIC copy at page ' + c.page + ', no. ' + c.number + '. Attestation is not required (R5).', evidence:[ev(c.page,'CNIC', c.crop)] };
    return { status:'hard', code:'A1-ii', finding:'No copy of the subscriber’s CNIC is on file.', remedy:'Obtain a copy of the subscriber’s CNIC. Attestation is not required.',
             cure: docCure('CNIC copy', 'add-cnic', [{k:'number',label:'CNIC number',type:'text'},{k:'type',label:'Card type',type:'select',options:['smart','old']}]) };
  }});

check({ id:'ADV-FORM', group:'checklist', checklist:'A1-iii', ref:'A1-iii · R6', title:'Form 5 (refundable) or Form 6-B (non-refundable)',
  applies: F => KIND(F, ...ADVANCES),
  run: F => {
    const cf = D(F).changeForm, want = KIND(F,'refundable') ? '05' : '06', name = KIND(F,'refundable') ? 'Form 5 (FORM PAY 05)' : 'Form 6-B (FORM PAY 06)';
    const code = KIND(F,'refundable') ? 'B1-v' : 'B2-iii';
    if (!cf || !cf.present) return { status:'hard', code, finding: name + ' is not attached.', remedy:'Attach ' + name + ' with the subscriber’s personal number and signature.',
      cure: docCure(name, 'add-form', [{k:'personalNo',label:'Personal number on the form',type:'text',expect:F.personnelNo},{k:'signed',label:'Signed by the subscriber',type:'yesno'},{k:'ddoSigned',label:'Signed and stamped by the DDO',type:'yesno'}]) };
    if (String(cf.label).indexOf(want) < 0) return { status:'hard', code, finding:'The form attached is ' + cf.label + ', not ' + name + '.', remedy:'Attach ' + name + '.', evidence:[ev(cf.page, cf.label)],
      cure: docCure(name, 'add-form', [{k:'personalNo',label:'Personal number on the form',type:'text',expect:F.personnelNo},{k:'signed',label:'Signed by the subscriber',type:'yesno'},{k:'ddoSigned',label:'Signed and stamped by the DDO',type:'yesno'}]) };
    return { status:'ok', finding: name + ' at page ' + cf.page + '. Only the personal number and signatures are mandatory; the loan details box is not examined (R6).', evidence:[ev(cf.page, cf.label)] };
  }});

check({ id:'ADV-FORM-DDO', group:'checklist', ref:'B1-vii · B2-v', title:'Form signed by the DDO',
  applies: F => KIND(F, ...ADVANCES) && D(F).changeForm && D(F).changeForm.present,
  run: F => {
    const cf = D(F).changeForm, code = KIND(F,'refundable') ? 'B1-vii' : 'B2-v';
    if (cf.ddoSigned) return { status:'ok', code, finding:'Signed and stamped by ' + (cf.ddoStamp || 'the DDO') + '.', evidence:[ev(cf.page,'DDO signature', cf.ddoCrop)] };
    return { status:'hard', code, finding:'The ' + cf.label + ' is not signed by the Drawing and Disbursing Officer.', remedy:'Obtain the DDO’s signature and stamp on the form.',
             evidence:[ev(cf.page, cf.label)], cure: docCure(cf.label + ' signed by DDO', 'ddo-signed', [{k:'ddoSigned',label:'Signed and stamped by the DDO',type:'yesno'}]) };
  }});

check({ id:'ADV-PERSNO', group:'identity', ref:'R6', code:'R6', title:'Personal number on the form tallies with the pay slip',
  applies: F => KIND(F, ...ADVANCES) && D(F).changeForm && D(F).changeForm.present,
  run: F => {
    const cf = D(F).changeForm, p = F.sap && F.sap.payslip;
    if (!cf.personalNo) return { status:'hard', finding:'The personal number is not filled in on the ' + cf.label + '. It is a mandatory field.', remedy:'Enter the personal number on the form.',
      evidence:[ev(cf.page, cf.label)], cure: docCure(cf.label, 'set-form-persno', [{k:'personalNo',label:'Personal number on the corrected form',type:'text',expect:F.personnelNo}]) };
    if (!p) return { status:'sap', finding:'Personal number ' + cf.personalNo + ' on the form. The pay slip is needed to tally it.', cure:{ kind:'sap' } };
    if (digits(cf.personalNo) === digits(p.persNo)) return { status:'ok', finding:'Personal number ' + cf.personalNo + ' on the ' + cf.label + ' tallies with the SAP pay slip.', evidence:[ev(cf.page, cf.label), ev(p.page, 'Pay slip')] };
    return { status:'hard', finding:'The ' + cf.label + ' gives personal number ' + cf.personalNo + '; the SAP pay slip gives ' + p.persNo + '.', remedy:'Correct the personal number on the form.',
             evidence:[ev(cf.page, cf.label), ev(p.page, 'Pay slip')], cure: docCure(cf.label, 'set-form-persno', [{k:'personalNo',label:'Personal number on the corrected form',type:'text',expect:p.persNo}]) };
  }});

check({ id:'ADV-APPLICANT', group:'identity', ref:'R6', code:'R6', title:'Applicant on the form is the subscriber',
  applies: F => KIND(F, ...ADVANCES) && D(F).changeForm && D(F).changeForm.present,
  run: F => {
    const cf = D(F).changeForm, p = F.sap && F.sap.payslip, card = (D(F).cnics||[]).find(c=>(c.whose||'subscriber')==='subscriber');
    const refs = [];
    if (p && p.name) refs.push(['SAP pay slip', p.name, sameName(cf.name, p.name)]);
    if (card && card.name) refs.push(['CNIC', card.name, sameName(cf.name, card.name)]);
    if (!refs.length) return { status:'sap', finding:'Name on the form: ' + (cf.name||'(not filled in)') + '. Nothing yet to compare it with.', cure:{ kind:'sap' } };
    const bad = refs.filter(r=>r[2] === false);
    if (bad.length) return { status:'hard', finding:'Name on the ' + cf.label + ' is ' + cf.name + '; ' + bad.map(r=>r[0] + ' reads ' + r[1]).join('; ') + '.', remedy:'Confirm the applicant and correct the form.' };
    return { status:'ok', finding:'Name ' + cf.name + ' agrees with ' + refs.map(r=>r[0]).join(' and ') + '.' };
  }});

check({ id:'ADV-FORM-CNIC', group:'identity', ref:'R6', code:'R6', title:'CNIC number written on the form',
  applies: F => KIND(F, ...ADVANCES) && D(F).changeForm && D(F).changeForm.cnic && (D(F).cnics||[]).some(c=>(c.whose||'subscriber')==='subscriber' && c.number),
  run: F => {
    const cf = D(F).changeForm, card = D(F).cnics.find(c=>(c.whose||'subscriber')==='subscriber' && c.number);
    if (digits(cf.cnic) === digits(card.number)) return { status:'ok', finding:'CNIC ' + card.number + ' on the form agrees with the card.' };
    return { status:'adv', finding:'The ' + cf.label + ' records CNIC ' + cf.cnic + '; the card reads ' + card.number + '. The applicant is otherwise confirmed by personal number and name, and the CNIC field is not mandatory on this form (R6), so this is noted only.',
             remedy:'Correct the CNIC on the department’s record.', evidence:[ev(cf.page, cf.label), ev(card.page, 'CNIC', card.crop)] };
  }});

/* Balance available for the 80% test: the balance before this advance. */
function balanceBefore(F){
  if (F.balanceBasis) return F.balanceBasis;
  const s = D(F).sanction, amt = s && s.amount;
  const rc = F.sap && F.sap.recalc, ps = F.sap && F.sap.payslip;
  if (rc && rc.rows && rc.rows.length){
    const col = KIND(F,'refundable') ? 'tempAdvance' : 'permanentAdvance';
    const row = rc.rows.slice().reverse().find(r=>amt && r[col] && Math.abs(r[col] - amt) <= 1);
    if (row) return { value: row.opening + (row.subscription||0) + (row.adjustments||0) + (row.recTempAdvance||0),
      explanation:'This advance (Rs ' + fmt(amt) + ') is already posted in the re-calculation report for ' + row.start + ' to ' + row.end +
                  '. The balance before it is taken as the opening balance Rs ' + fmt(row.opening) + ' plus that period’s subscriptions Rs ' + fmt(row.subscription||0) +
                  (row.recTempAdvance ? ' and recoveries Rs ' + fmt(row.recTempAdvance) : '') + '.', source:'re-calculation report' };
    const last = rc.rows[rc.rows.length-1];
    return { value:last.closing, explanation:'Closing balance Rs ' + fmt(last.closing) + ' for ' + last.start + ' to ' + last.end + '. This advance is not yet posted.', source:'re-calculation report' };
  }
  if (ps && ps.gpfBalance !== null && ps.gpfBalance !== undefined)
    return { value:ps.gpfBalance, explanation:'GPF balance Rs ' + fmt(ps.gpfBalance) + ' on the pay slip for ' + ps.month + '. Without the re-calculation report it cannot be confirmed whether this advance is already deducted.', source:'pay slip', provisional:true };
  return null;
}

check({ id:'ADV-80', group:'balance', ref:'R9 · B1-i', code:'B1-i', title:'Advance within 80% of the GPF balance',
  applies: F => KIND(F, ...ADVANCES) && D(F).sanction && D(F).sanction.present,
  run: F => {
    const s = D(F).sanction, b = balanceBefore(F);
    if (!b) return { status:'sap', finding:'Sanctioned Rs ' + fmt(s.amount) + '. The SAP balance is needed for the 80% test.', cure:{ kind:'sap' } };
    const cap = Math.floor(b.value * PARAMS.advanceCapPct / 100);
    const calc = { amount:s.amount, balance:b.value, pct:PARAMS.advanceCapPct, cap, basis:b.explanation, stated:s.balanceStated };
    const note = (s.balanceStated && Math.abs(s.balanceStated - b.value) > 1) ? ' The sanction itself states a balance of Rs ' + fmt(s.balanceStated) + '.' : '';
    if (s.amount <= cap) return { status: b.provisional ? 'conf' : 'ok', calc,
      finding:'Rs ' + fmt(s.amount) + ' is within ' + PARAMS.advanceCapPct + '% of Rs ' + fmt(b.value) + ' (limit Rs ' + fmt(cap) + '). ' + b.explanation + note,
      remedy: b.provisional ? 'Upload the re-calculation report to confirm the balance basis.' : '', cure: b.provisional ? { kind:'sap' } : null };
    return { status:'hard', calc, finding:'Rs ' + fmt(s.amount) + ' exceeds ' + PARAMS.advanceCapPct + '% of the balance. Balance Rs ' + fmt(b.value) + ', limit Rs ' + fmt(cap) +
      ', excess Rs ' + fmt(s.amount - cap) + '. ' + b.explanation + note, remedy:'Reduce the sanction to Rs ' + fmt(cap) + ' or less, or show a higher balance from SAP.' };
  }});

check({ id:'ADV-ACTIVE', group:'balance', ref:'R12', code:'R12', title:'No other advance outstanding',
  applies: F => KIND(F,'refundable'),
  run: F => {
    if (F.prevAdvance){
      const pa = F.prevAdvance, s = D(F).sanction;
      if (pa.outstanding > 0) return { status:'hard', finding:'Another advance is still outstanding: Rs ' + fmt(pa.outstanding) + '. ' + pa.explanation, remedy:'The earlier advance must be fully recovered first.' };
      if (pa.zeroMonth && s && s.month && s.month <= pa.zeroMonth) return { status:'hard', finding:'The earlier advance was fully recovered in ' + pa.zeroMonthLabel + '. A new advance may be settled only after that month. ' + pa.explanation, remedy:'Re-submit after ' + pa.zeroMonthLabel + '.' };
      return { status:'ok', finding: pa.explanation };
    }
    const p = F.sap && F.sap.payslip;
    if (!p) return { status:'sap', finding:'The SAP pay slip and re-calculation report are needed to see any advance still outstanding.', cure:{ kind:'sap' } };
    if (!p.loanBalance) return { status:'ok', finding:'The SAP pay slip shows no GPF advance outstanding.' };
    return { status:'conf', finding:'The SAP pay slip shows a GPF advance balance of Rs ' + fmt(p.loanBalance) + '. Confirm whether this is the advance under examination or an earlier one.', cure:{ kind:'verify', vid:'ADV-ACTIVE' } };
  }});

/* ── Final payments ─────────────────────────────────────────────────────── */
check({ id:'FP-GPF10', group:'checklist', checklist:'A2-ii', ref:'A2-ii · B2-i', code:'B2-i', title:'G.P.F. Form 10, properly filled and signed',
  applies: F => KIND(F, ...FINALS),
  run: F => {
    const g = D(F).gpf10;
    if (!g || !g.present) return { status:'hard', finding:'G.P.F. Form 10 is not on file.', remedy:'Submit Form 10 signed by the DDO and the subscriber or claimant.',
      cure: docCure('G.P.F. Form 10', 'add-gpf10', [{k:'accountNo',label:'GP Fund account no.',type:'text'},{k:'signed',label:'Signed by subscriber or claimant',type:'yesno'},{k:'ddoSigned',label:'Signed by DDO',type:'yesno'}]) };
    const miss = (g.missing || []).slice();
    if (!miss.length) return { status:'ok', finding:'Form 10 at page ' + g.page + ', account no. ' + (g.accountNo||'') + ', signed.', evidence:[ev(g.page,'Form 10')] };
    const sapCovers = F.sap && F.sap.payslip && miss.every(m=>/account|personnel/i.test(m));
    return { status: sapCovers ? 'adv' : 'hard', finding:'Form 10 at page ' + g.page + ' is incomplete: ' + miss.join(', ') + '.' + (sapCovers ? ' The missing identifiers are available on the SAP pay slip, so this is noted only.' : ''),
             remedy:'Complete Form 10: ' + miss.join(', ') + '.', evidence:[ev(g.page,'Form 10')],
             cure: docCure('Completed G.P.F. Form 10', 'gpf10-complete', miss.map((m,i)=>({k:'m'+i,label:m+' now filled in',type:'yesno'}))) };
  }});

check({ id:'FP-NOTIF', group:'checklist', checklist:'A2-iii', ref:'A2-iii', title:'Retirement, dismissal or obituary notification',
  applies: F => KIND(F, ...FINALS),
  run: F => {
    const n = D(F).notification;
    if (n && n.present) return { status:'ok', finding:(n.label||'Notification') + ' No. ' + (n.no||'(not stated)') + ' dated ' + (n.date||'(not stated)') + ', page ' + n.page + '.', evidence:[ev(n.page, n.label||'Notification')] };
    return { status:'hard', code:'A2-iii', finding:'The ' + (KIND(F,'death') ? 'obituary' : KIND(F,'dismissal') ? 'dismissal' : 'retirement') + ' notification is not on file.', remedy:'Attach a copy of the notification.',
             cure: docCure('Notification', 'add-notification', [{k:'no',label:'Notification no.',type:'text'},{k:'date',label:'Date',type:'text'}]) };
  }});

check({ id:'FP-CNIC', group:'checklist', checklist:'A2-iv', ref:'A2-iv · R5', title:'Copy of CNIC of the subscriber',
  applies: F => KIND(F, ...FINALS),
  run: F => {
    const c = (D(F).cnics || []).find(x=>/subscriber|deceased/.test(x.whose||'subscriber'));
    if (c) return { status:'ok', finding:'CNIC copy of the ' + (c.whose||'subscriber') + ' at page ' + c.page + ', no. ' + c.number + '. Attestation is not required (R5).', evidence:[ev(c.page,'CNIC', c.crop)] };
    return { status:'hard', code:'A2-iv', finding:'No copy of the subscriber’s CNIC is on file.', remedy:'Attach a copy of the subscriber’s CNIC.',
             cure: docCure('CNIC copy', 'add-cnic', [{k:'number',label:'CNIC number',type:'text'},{k:'type',label:'Card type',type:'select',options:['smart','old']}]) };
  }});

check({ id:'FP-FORM06', group:'checklist', checklist:'A2-v', ref:'A2-v · B2-iii · B2-v', title:'Change Form-06 signed by DDO and subscriber',
  applies: F => KIND(F, ...FINALS),
  run: F => {
    const cf = D(F).changeForm;
    if (!cf || !cf.present) return { status:'hard', code:'B2-iii', finding:'Change Form-06 is not attached.', remedy:'Attach Change Form-06 signed by the DDO and the subscriber.',
      cure: docCure('Change Form-06', 'add-form', [{k:'personalNo',label:'Personal number on the form',type:'text',expect:F.personnelNo},{k:'signed',label:'Signed or thumbed by subscriber/claimant',type:'yesno'},{k:'ddoSigned',label:'Signed and stamped by the DDO',type:'yesno'}]) };
    const gaps = [];
    if (!cf.ddoSigned) gaps.push('the DDO');
    if (!cf.sigKind || cf.sigKind === 'none') gaps.push(KIND(F,'death') ? 'the claimant' : 'the subscriber');
    if (gaps.length) return { status:'hard', code:'B2-v', finding:'Change Form-06 at page ' + cf.page + ' is not signed by ' + gaps.join(' or ') + '.', remedy:'Obtain the missing signature.', evidence:[ev(cf.page,'Form 06')],
      cure: docCure('Signed Change Form-06', 'form-signatures', [{k:'ddoSigned',label:'Signed and stamped by the DDO',type:'yesno'},{k:'signed',label:'Signed or thumbed by subscriber/claimant',type:'yesno'}]) };
    return { status:'ok', finding:'Change Form-06 at page ' + cf.page + ', signed by the DDO and ' + (cf.sigKind === 'thumb' ? 'thumbed' : 'signed') + ' by the ' + (KIND(F,'death') ? 'claimant' : 'subscriber') + '.', evidence:[ev(cf.page,'Form 06')] };
  }});

check({ id:'FP-OLDAC', group:'identity', ref:'B2-vii', code:'B2-vii', title:'Old GP Fund account no. on the change form',
  applies: F => KIND(F, ...FINALS) && D(F).changeForm && D(F).changeForm.present,
  run: F => {
    const cf = D(F).changeForm, p = F.sap && F.sap.payslip;
    const sapOld = p && p.oldGpfNo && digits(p.oldGpfNo).length > 3 ? p.oldGpfNo : null;
    if (cf.oldGpfNo && digits(cf.oldGpfNo).length > 3){
      if (sapOld && digits(sapOld) !== digits(cf.oldGpfNo)) return { status:'hard', finding:'Old A/c ' + cf.oldGpfNo + ' on the form; SAP pay slip Old # reads ' + sapOld + '.', remedy:'Reconcile the old account number.' };
      return { status:'ok', finding:'Old GP Fund A/c ' + cf.oldGpfNo + ' on the form' + (sapOld ? ', agreeing with the SAP pay slip.' : '.') };
    }
    if (sapOld) return { status:'adv', finding:'The old account number is not written on the form (' + (cf.oldGpfNoState || 'blank') + '), but SAP holds it as ' + sapOld + '. Noted; the office can settle it from SAP.', remedy:'None needed to process. The department should complete field 16 in future.' };
    if (!p) return { status:'sap', finding:'The old account number is not written on the form. The SAP pay slip may carry it.', cure:{ kind:'sap' } };
    return { status:'hard', finding:'The old GP Fund account number is not on the form (' + (cf.oldGpfNoState || 'blank') + ') and SAP shows none.', remedy:'State the old account number, or write "manual" where none was allotted.',
             evidence:[ev(cf.page,'Form 06')], cure: docCure('Corrected Change Form-06', 'set-oldac', [{k:'oldGpfNo',label:'Old GP Fund A/c no. now stated',type:'text'}]) };
  }});

check({ id:'FP-SB', group:'checklist', checklist:'A2-vii', ref:'A2-vii · B2-viii', code:'B2-viii', title:'Original Service Book (non-gazetted)',
  applies: F => KIND(F,'final','death','dismissal') && F.gazetted === 'non-gazetted',
  run: F => {
    const sb = D(F).serviceBook;
    if (!sb || !sb.present) return { status:'hard', finding:'No Service Book is on file for a non-gazetted subscriber.', remedy:'Produce the original Service Book.',
      cure: docCure('Original Service Book', 'add-servicebook', [{k:'dor',label:'Date of retirement entered',type:'yesno'},{k:'order',label:'Order of retirement entered',type:'yesno'},{k:'leave',label:'Leave account present',type:'yesno'}]) };
    const e = sb.entries || {}, miss = [];
    if (!e.dor) miss.push('date of retirement'); if (!e.order) miss.push('order of retirement'); if (!e.leave) miss.push('leave account');
    if (!miss.length) return { status:'ok', finding:'Service Book carries the requisite entries.' };
    return { status:'hard', finding:'Service Book (' + (sb.note || 'pages ' + (sb.pages||[]).join(', ')) + ') does not show: ' + miss.join(', ') + '.', remedy:'Produce the Service Book pages carrying ' + miss.join(', ') + '.',
             evidence:(sb.pages||[]).map(p=>ev(p,'Service Book')),
             cure: docCure('Service Book pages', 'add-servicebook', [{k:'dor',label:'Date of retirement entered',type:'yesno'},{k:'order',label:'Order of retirement entered',type:'yesno'},{k:'leave',label:'Leave account present',type:'yesno'}]) };
  }});

check({ id:'FP-CLAIM', group:'balance', ref:'B2-vi · R11', code:'B2-vi', title:'Amount claimed reconciles with the re-calculation report',
  applies: F => KIND(F, ...FINALS) && F.claim && F.claim.amount,
  run: F => {
    const rc = F.sap && F.sap.recalc;
    if (!rc || !rc.rows || !rc.rows.length) return { status:'sap', finding:'Rs ' + fmt(F.claim.amount) + ' claimed. The re-calculation report is needed to reconcile it.', cure:{ kind:'sap' } };
    const exp = F.claim.expected !== undefined ? F.claim.expected : rc.rows[rc.rows.length-1].closing;
    const basis = F.claim.basis || ('closing balance Rs ' + fmt(exp) + ' in the last period of the report');
    const diff = F.claim.amount - exp;
    if (Math.abs(diff) <= PARAMS.claimTolerance) return { status:'ok', calc:{claim:F.claim.amount, expected:exp, basis}, finding:'Rs ' + fmt(F.claim.amount) + ' claimed agrees with the ' + basis + '.' };
    return { status:'hard', calc:{claim:F.claim.amount, expected:exp, basis}, finding:'Rs ' + fmt(F.claim.amount) + ' claimed against the ' + basis + ': a difference of Rs ' + fmt(Math.abs(diff)) + (diff > 0 ? ' over.' : ' short.') + (F.claim.note ? ' ' + F.claim.note : ''),
             remedy:'Reconcile the claim with the SAP re-calculation report.', evidence: F.claim.page ? [ev(F.claim.page, 'Amount claimed')] : [] };
  }});

/* ── Death cases ────────────────────────────────────────────────────────── */
check({ id:'DEATH-HEIRS', group:'checklist', checklist:'A2-iv', ref:'A2-iv', code:'A2-iv', title:'CNIC copies of all legal heirs',
  applies: F => KIND(F,'death') && D(F).death,
  run: F => {
    const heirs = D(F).death.heirs || [];
    const miss = heirs.filter(h=>!h.cnicCopy && !h.minor);
    if (!heirs.length) return { status:'conf', finding:'The legal heirs could not be established from the case.', cure:{ kind:'verify', vid:'DEATH-HEIRS' } };
    if (!miss.length) return { status:'ok', finding:'Copies on file for every adult legal heir: ' + heirs.filter(h=>!h.minor).map(h=>h.name).join(', ') + '.' + (heirs.some(h=>h.minor) ? ' Minor heirs: ' + heirs.filter(h=>h.minor).map(h=>h.name).join(', ') + ', covered by the NADRA family registration certificate.' : '') };
    return { status:'hard', finding:'No CNIC copy for ' + miss.map(h=>h.name + ' (' + h.relation + ')').join(', ') + '.', remedy:'Attach CNIC copies for every adult legal heir.',
             cure: docCure('CNIC copy of legal heir', 'add-heir-cnic', [{k:'name',label:'Heir',type:'select',options:miss.map(h=>h.name)},{k:'number',label:'CNIC number',type:'text'}]) };
  }});

check({ id:'DEATH-AFFIDAVIT', group:'checklist', checklist:'A2-vi', ref:'A2-vi', code:'A2-vi', title:'Original affidavit for lawful widow',
  applies: F => KIND(F,'death') && D(F).death && D(F).death.widowClaim,
  run: F => {
    const a = D(F).death.affidavit || {};
    if (a.present && a.original) return { status:'ok', finding:(a.label||'Affidavit') + ' at page ' + a.page + '.', evidence:[ev(a.page,'Affidavit')] };
    return { status:'hard', finding: a.present ? (a.label||'The document') + ' at page ' + a.page + ' is not an original affidavit for lawful widow. ' + (a.note||'') : 'No affidavit for lawful widow is on file.',
             remedy:'Produce the original affidavit for lawful widow.', cure: docCure('Original affidavit for lawful widow', 'add-affidavit', [{k:'original',label:'Original, on stamp paper, attested',type:'yesno'}]) };
  }});

check({ id:'DEATH-SUCCESSION', group:'checklist', checklist:'A2-vi', ref:'A2-vi · R13', code:'A2-vi', title:'Succession certificate, or OSD post created',
  applies: F => KIND(F,'death') && D(F).death,
  run: F => {
    const d = D(F).death, p = F.sap && F.sap.payslip;
    const osdSap = p && p.osdPost && /yes|created|osd/i.test(String(p.osdPost));
    if (osdSap) return { status:'ok', finding:'The SAP pay slip shows an OSD post created (' + p.osdPost + '). A succession certificate is not required (R13).' };
    if (d.successionCert === 'granted') return { status:'ok', finding:'Succession certificate granted, page ' + d.successionPage + '.' };
    if (!d.successionRequired) return { status:'ok', finding:'Not required: one widow and heirs within the family.' };
    if (!p) return { status:'sap', finding:'Succession certificate: ' + (d.successionNote||'not on file') + '. If SAP shows an OSD post created, it is not required (R13). Pull the pay slip first.', cure:{ kind:'sap' } };
    if (d.osdAnnotation){
      const v = verified(F, 'DEATH-OSD');
      if (v) return v.ok ? { status:'ok', finding:'OSD post creation confirmed in SAP by ' + v.by + (v.note ? ': ' + v.note : '') + '. Succession certificate not required (R13).' }
                         : { status:'hard', finding:'SAP does not show an OSD post, and no succession certificate is on file. ' + (d.successionNote||''), remedy:'Produce the succession certificate granted by the court.',
                             cure: docCure('Succession certificate', 'add-succession', [{k:'granted',label:'Certificate granted by the court',type:'yesno'}]) };
      return { status:'conf', finding:'Form 06 page ' + d.osdAnnotation.page + ' is annotated "' + d.osdAnnotation.text + '", but the SAP pay slip shows no OSD post field. ' + (d.successionNote||''),
               remedy:'Confirm in SAP whether an OSD post was created. If so no succession certificate is needed (R13).', cure:{ kind:'verify', vid:'DEATH-OSD' }, evidence:[ev(d.osdAnnotation.page,'OSD annotation', d.osdAnnotation.crop)] };
    }
    return { status:'hard', finding:'No succession certificate. ' + (d.successionNote||''), remedy:'Produce the succession certificate, or evidence from SAP that an OSD post was created.',
             cure: docCure('Succession certificate', 'add-succession', [{k:'granted',label:'Certificate granted by the court',type:'yesno'}]) };
  }});

/* ── Missing credits ────────────────────────────────────────────────────── */
check({ id:'MC-PERIOD', group:'checklist', checklist:'A4-ii', ref:'A4-ii', title:'Period of missing months',
  applies: F => KIND(F,'missing_credits'),
  run: F => { const ch = D(F).challans || {}; return ch.period ? { status:'ok', finding:'Period stated: ' + ch.period + '.' }
    : { status:'hard', code:'A4-ii', finding:'The period of the missing months is not stated.', remedy:'State the period.', cure: docCure('Letter stating the period', 'set-period', [{k:'period',label:'Period',type:'text'}]) }; } });

function challanSubstitute(F){
  const ch = D(F).challans || {}, copies = ch.copies || [];
  const noStamp = copies.filter(c=>!c.bankStamp);
  return { ok: copies.length > 0 && !noStamp.length && ch.toVerified, noStamp, toVerified: ch.toVerified, copies, ch };
}
[['MC-DDO-CERT','A4-iii','R14','Manual deduction certificate by DDO, with bills and acquaintance roll (non-gazetted period)','non-gazetted'],
 ['MC-AG-CERT','A4-iv','R15','Manual deduction certificate by AG Office (gazetted period)','gazetted']].forEach(([id, item, r, title, period])=>{
  check({ id, group:'checklist', checklist:item, ref:item + ' · ' + r, code:item, title,
    applies: F => KIND(F,'missing_credits') && (F.gazetted === period || F.gazetted === 'mixed' || F.gazetted === 'unknown'),
    run: F => {
      const x = challanSubstitute(F);
      if (x.ch.certificate && x.ch.certificate[period]) return { status:'ok', finding:'Certificate on file.' };
      if (x.ok) return { status:'sub', finding:'No certificate, but every one of the ' + x.copies.length + ' challans attached carries the bank’s stamp and the covering letter carries the Treasury Office verification (page ' + x.ch.toPage + '). Accepted in place of the certificate (' + r + ').',
                         evidence:[ev(x.ch.toPage,'Treasury verification', x.ch.toCrop)].concat(x.copies.map(c=>ev(c.page,'Bank stamp', c.crop))) };
      const why = [];
      if (x.noStamp.length) why.push('challan' + (x.noStamp.length>1?'s':'') + ' at page ' + x.noStamp.map(c=>c.page).join(', ') + ' carr' + (x.noStamp.length>1?'y':'ies') + ' no bank stamp');
      if (!x.toVerified) why.push('the covering letter carries no Treasury Office verification');
      if (!x.copies.length) why.push('no challans are attached');
      return { status:'hard', finding:'No certificate, and the challans cannot yet stand in for it: ' + why.join('; ') + '.',
               remedy:'Produce challan copies carrying the bank’s stamp' + (!x.toVerified ? ' and obtain Treasury Office verification on the covering letter' : '') + ', or the certificate itself.',
               cure: x.noStamp.length ? docCure('Challan copy with bank stamp', 'challan-stamp', [{k:'page',label:'Replaces challan at page',type:'select',options:x.noStamp.map(c=>String(c.page))},{k:'bankStamp',label:'Bank stamp present on the new copy',type:'yesno'}])
                                      : docCure('Treasury-verified covering letter', 'to-verified', [{k:'toVerified',label:'Treasury Office verification stamp present',type:'yesno'}]) };
    }});
});

check({ id:'MC-CHALLANS', group:'checklist', checklist:'A4-v', ref:'A4-v', code:'A4-v', title:'Challans verified by Treasury, as scheduled',
  applies: F => KIND(F,'missing_credits'),
  run: F => {
    const ch = D(F).challans || {}, copies = ch.copies || [], sch = ch.schedule || {};
    const attached = copies.reduce((a,c)=>a + (c.amount||0), 0);
    const missing = (sch.items || []).filter(it=>!copies.some(c=>String(c.sr) === String(it.sr)));
    if (!missing.length && (!sch.total || Math.abs(attached - sch.total) <= 1)) return { status:'ok', finding:copies.length + ' challans attached, total Rs ' + fmt(attached) + ', agreeing with the Treasury-verified schedule.' };
    return { status:'hard', calc:{ attached, scheduled:sch.total, variance:(sch.total||0) - attached },
      finding:'The schedule lists ' + (sch.items||[]).length + ' challans for Rs ' + fmt(sch.total) + '; ' + copies.length + ' are attached for Rs ' + fmt(attached) + '. ' +
              (missing.length ? 'Missing: ' + missing.map(m=>'Sr. ' + m.sr + ' (' + m.period + ', Rs ' + fmt(m.amount) + (m.cheque ? ', cheque ' + m.cheque : '') + ')').join('; ') + '. ' : '') +
              'Variance Rs ' + fmt((sch.total||0) - attached) + '.',
      remedy:'Attach the missing challan copy with the bank’s stamp, or amend the schedule and the Treasury verification to the challans produced.',
      cure: missing.length ? docCure('Challan Form 32-A, Sr. ' + missing[0].sr, 'add-challan', [{k:'sr',label:'Schedule Sr.',type:'text',expect:String(missing[0].sr)},{k:'amount',label:'Amount (Rs)',type:'number',expect:String(missing[0].amount)},{k:'bankStamp',label:'Bank stamp present',type:'yesno'}]) : null };
  }});

/* ── Balance transfer ───────────────────────────────────────────────────── */
check({ id:'BT-PROFORMA', group:'checklist', checklist:'A3-i', ref:'A3-i', code:'A3-i', title:'Proforma particulars complete',
  applies: F => KIND(F,'balance_transfer'),
  run: F => {
    const pf = D(F).proforma || {}, p = F.sap && F.sap.payslip, miss = [];
    const acct = v => v && !/personal|pers/i.test(v) && digits(v).length > 3;
    if (!acct(pf.oldAc)) miss.push('old GP Fund account no. (column 4 reads "' + (pf.oldAc||'blank') + '")');
    if (!acct(pf.newAc)) miss.push('new GP Fund account no. allotted by the DAO (column 5 reads "' + (pf.newAc||'blank') + '")');
    if (!pf.lastDeduction) miss.push('treasury voucher and date of the last fund deduction (column 6)');
    if (!pf.periods) miss.push('period of posting');
    if (!miss.length) return { status:'ok', finding:'All particulars stated.', evidence:[ev(pf.page,'Proforma')] };
    const sapHelps = p && (p.gpfNo || p.oldGpfNo);
    return { status:'hard', finding:'The proforma at page ' + pf.page + ' does not state: ' + miss.join('; ') + '.' + (sapHelps ? ' SAP holds GPF # ' + (p.gpfNo||'-') + ' and Old # ' + (p.oldGpfNo||'-') + ', which the officer may use to settle the account numbers.' : ''),
             remedy:'Complete the proforma and obtain a fresh DAO confirmation against the account number.', evidence:[ev(pf.page,'Proforma')],
             cure: docCure('Completed proforma', 'proforma', [{k:'oldAc',label:'Old A/c no. (column 4)',type:'text'},{k:'newAc',label:'New A/c no. (column 5)',type:'text'},{k:'lastDeduction',label:'Voucher and date of last deduction (column 6)',type:'text'}]) };
  }});

/* ═══════════════════════════════════════════════════════════════════════
   CURES: how a confirmed upload changes the facts. The rules then decide.
   ═══════════════════════════════════════════════════════════════════════ */
const up = (file) => 'upload: ' + file;
const CURES = {
  'add-sanction': (F,v,f)=>{ F.docs.sanction = Object.assign(F.docs.sanction||{}, {present:true, page:up(f), orderNo:v.orderNo, date:v.date, amount:num(v.amount), rule:v.rule}); },
  'set-sanction-rule': (F,v)=>{ Object.assign(F.docs.sanction, {rule:v.rule || F.docs.sanction.rule, reason:v.reason || F.docs.sanction.reason}); },
  'add-cnic': (F,v,f)=>{ F.docs.cnics = F.docs.cnics||[]; F.docs.cnics.push({page:up(f), whose:'subscriber', type:v.type||'smart', number:v.number, attested:false}); },
  'add-form': (F,v,f)=>{ const lab = KIND(F,'refundable') ? 'FORM PAY 05' : 'FORM PAY 06';
    F.docs.changeForm = Object.assign(F.docs.changeForm||{}, {present:true, label:lab, page:up(f), personalNo:v.personalNo, sigKind: yes(v.signed)?'signature':'none', ddoSigned: yes(v.ddoSigned)}); },
  'ddo-signed': (F,v)=>{ F.docs.changeForm.ddoSigned = yes(v.ddoSigned); },
  'form-signed': (F,v)=>{ F.docs.changeForm.sigKind = yes(v.signed) ? 'signature' : 'none'; },
  'form-signatures': (F,v)=>{ if (yes(v.ddoSigned)) F.docs.changeForm.ddoSigned = true; if (yes(v.signed) && (!F.docs.changeForm.sigKind || F.docs.changeForm.sigKind==='none')) F.docs.changeForm.sigKind = 'signature'; },
  'set-form-persno': (F,v)=>{ F.docs.changeForm.personalNo = v.personalNo; },
  'add-gpf10': (F,v,f)=>{ F.docs.gpf10 = {present:true, page:up(f), accountNo:v.accountNo, missing:[].concat(yes(v.signed)?[]:['signature of subscriber or claimant'], yes(v.ddoSigned)?[]:['signature of DDO'], v.accountNo?[]:['GP Fund account no.'])}; },
  'gpf10-complete': (F,v)=>{ const g = F.docs.gpf10; g.missing = (g.missing||[]).filter((m,i)=>!yes(v['m'+i])); },
  'add-notification': (F,v,f)=>{ F.docs.notification = {present:true, page:up(f), no:v.no, date:v.date, label:'Notification'}; },
  'set-oldac': (F,v)=>{ F.docs.changeForm.oldGpfNo = v.oldGpfNo; },
  'add-servicebook': (F,v,f)=>{ F.docs.serviceBook = {present:true, pages:[up(f)], entries:{dor:yes(v.dor), order:yes(v.order), leave:yes(v.leave)}, note:'uploaded pages'}; },
  'add-heir-cnic': (F,v)=>{ const h = F.docs.death.heirs.find(x=>x.name===v.name); if (h) h.cnicCopy = true; },
  'add-affidavit': (F,v,f)=>{ F.docs.death.affidavit = {present:true, original:yes(v.original), page:up(f), label:'Affidavit for lawful widow'}; },
  'add-succession': (F,v,f)=>{ if (yes(v.granted)){ F.docs.death.successionCert = 'granted'; F.docs.death.successionPage = up(f); } },
  'set-period': (F,v)=>{ F.docs.challans.period = v.period; },
  'challan-stamp': (F,v)=>{ const c = F.docs.challans.copies.find(x=>String(x.page)===String(v.page)); if (c && yes(v.bankStamp)) c.bankStamp = true; },
  'to-verified': (F,v)=>{ F.docs.challans.toVerified = yes(v.toVerified); },
  'add-challan': (F,v,f)=>{ F.docs.challans.copies.push({page:up(f), sr:v.sr, amount:num(v.amount), bankStamp:yes(v.bankStamp)}); },
  'proforma': (F,v)=>{ Object.assign(F.docs.proforma, {oldAc:v.oldAc || F.docs.proforma.oldAc, newAc:v.newAc || F.docs.proforma.newAc, lastDeduction:v.lastDeduction || F.docs.proforma.lastDeduction}); }
};
