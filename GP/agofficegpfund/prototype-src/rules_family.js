/* ═══════════════════════════════════════════════════════════════════════
   RULE CATALOGUE, PART 2: rules by case family
   ═══════════════════════════════════════════════════════════════════════ */
const PARAMS = {
  officeCapPct: 80,                  /* office statement of 15-09-2026, flagged against the Rules */
  claimTolerance: 1
};

/* Advance limits as the Punjab GP Fund Rules 1978 (Compendium 2008) actually set them.
   pct: share of the balance; months: months of pay; combine: which of the two governs. */
const ADV_LIMITS = {
  '1.14(1)(c)(i)':  { label:'Temporary advance, general purposes (illness, passage, ceremonies, Haj, other)', pct:50, months:3, combine:'min', src:'Rule 1.14(1)(c)(i)', relaxable:'only for special reasons recorded in writing, never for purpose (a)(vi)' },
  '1.14(1)(d)(i)':  { label:'Temporary advance for a plot or house', pct:80, months:24, combine:'min', src:'Rule 1.14(1)(d)(i)' },
  '1.14(1)(e)(i)-car':        { label:'Temporary advance for a car', pct:50, months:12, combine:'min', src:'Rule 1.14(1)(e)(i)' },
  '1.14(1)(e)(i)-motorcycle': { label:'Temporary advance for a scooter or motorcycle', pct:50, months:6, combine:'min', src:'Rule 1.14(1)(e)(i)' },
  '1.14(1)(e)(i)-bicycle':    { label:'Temporary advance for a bicycle', pct:50, months:4, combine:'min', src:'Rule 1.14(1)(e)(i)' },
  '1.15(a)':        { label:'Non-refundable advance after 50, building or altering a house', pct:80, months:24, combine:'min', src:'Rule 1.15(a) with 1.14(1)(d)(i)', minAge:50 },
  '1.15(b)':        { label:'Non-refundable advance after 50, buying a house', pct:80, src:'Rule 1.15(b)(1)', minAge:50 },
  '1.15(c)':        { label:'Non-refundable advance after 50, agricultural land from Government', pct:80, src:'Rule 1.15(c)(1)', minAge:50 },
  '1.15(d)':        { label:'Non-refundable advance after 50, illness, passage, education, ceremonies', pct:80, months:12, combine:'max', src:'Rule 1.15(d)(1)', minAge:50 },
  '1.16':           { label:'Non-refundable advance at 50 or over, no reason needed', pct:100, src:'Rule 1.16 (substituted 12-12-2002)', minAge:50 },
  '1.18':           { label:'Non-refundable advance at 45 or over, building a house', pct:80, months:24, combine:'min', src:'Rule 1.18 with 1.15(a)', minAge:45 }
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
      ', page ' + s.page + ', for Rs ' + fmt(s.amount) + '. The signatory is checked against the DOA register.', evidence:[ev(s.page, 'Sanction', s.crop)] };
    return { status:'hard', finding:'No original sanction is on file.', remedy:'Produce the original sanction of the competent authority.',
             cure: docCure('Original sanction', 'add-sanction', [{k:'orderNo',label:'Order no.',type:'text'},{k:'date',label:'Date',type:'text'},{k:'amount',label:'Amount sanctioned (Rs)',type:'number'},{k:'rule',label:'Rule quoted',type:'text'}]) };
  }});

check({ id:'ADV-RULE', group:'checklist', ref:'B1-iv · B2-ix', code:'B1-iv', title:'Rule and reason quoted on the sanction',
  applies: F => KIND(F, ...ADVANCES) && D(F).sanction && D(F).sanction.present,
  run: F => {
    const s = D(F).sanction, code = KIND(F,'refundable') ? 'B1-iv' : 'B2-ix';
    const needReason = KIND(F,'refundable');
    if (s.rule && (!needReason || s.reason)) return { status:'ok', code, finding:'Rule quoted: ' + s.rule + (s.reason ? '. Reason: ' + s.reason + '.' : '.') + (s.limitClause === '1.16' ? ' Under Rule 1.16 no reason is needed.' : ''), evidence:[ev(s.page,'Sanction')] };
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
    const cure = docCure(name, 'add-form', [{k:'personalNo',label:'Personal number on the form',type:'text',expect:F.personnelNo},{k:'signed',label:'Signed by the subscriber',type:'yesno'},{k:'ddoSigned',label:'Signed and stamped by the DDO',type:'yesno'}]);
    if (!cf || !cf.present) return { status:'hard', code, finding: name + ' is not attached.', remedy:'Attach ' + name + ' with the subscriber’s personal number and signature.', cure };
    if (String(cf.label).indexOf(want) < 0) return { status:'hard', code, finding:'The form attached is ' + cf.label + ', not ' + name + '.', remedy:'Attach ' + name + '.', evidence:[ev(cf.page, cf.label)], cure };
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
    const cure = exp => docCure(cf.label, 'set-form-persno', [{k:'personalNo',label:'Personal number on the corrected form',type:'text',expect:exp}]);
    if (!cf.personalNo) return { status:'hard', finding:'The personal number is not filled in on the ' + cf.label + '. It is a mandatory field.', remedy:'Enter the personal number on the form.', evidence:[ev(cf.page, cf.label)], cure:cure(F.personnelNo) };
    if (!p) return { status:'sap', finding:'Personal number ' + cf.personalNo + ' on the form. The SAP pay slip is needed to tally it.', cure:{ kind:'sap' } };
    if (digits(cf.personalNo) === digits(p.persNo)) return { status:'ok', finding:'Personal number ' + cf.personalNo + ' on the ' + cf.label + ' tallies with the SAP pay slip.', evidence:[ev(cf.page, cf.label), ev(p.page, 'Pay slip')] };
    return { status:'hard', finding:'The ' + cf.label + ' gives personal number ' + cf.personalNo + '; the SAP pay slip gives ' + p.persNo + '.', remedy:'Correct the personal number on the form.',
             evidence:[ev(cf.page, cf.label), ev(p.page, 'Pay slip')], cure:cure(p.persNo) };
  }});

check({ id:'ADV-APPLICANT', group:'identity', ref:'R6', code:'R6', title:'Applicant on the form is the subscriber',
  applies: F => KIND(F, ...ADVANCES) && D(F).changeForm && D(F).changeForm.present,
  run: F => {
    const cf = D(F).changeForm, p = F.sap && F.sap.payslip, card = (D(F).cnics||[]).find(c=>(c.whose||'subscriber')==='subscriber');
    const refs = [];
    if (p && p.name) refs.push(['SAP pay slip', p.name, sameName(cf.name, p.name)]);
    if (card && card.name) refs.push(['CNIC', card.name, sameName(cf.name, card.name)]);
    if (!refs.length) return { status:'sap', finding:'Name on the form: ' + (cf.name||'(not filled in)') + '. Nothing yet to compare it with.', cure:{ kind:'sap' } };
    const bad = refs.filter(r=>r[2] === false && !(F.nameVariants||[]).includes(r[1]));
    if (bad.length) return { status:'hard', finding:'Name on the ' + cf.label + ' is ' + cf.name + '; ' + bad.map(r=>r[0] + ' reads ' + r[1]).join('; ') + '.', remedy:'Confirm the applicant and correct the form.' };
    return { status:'ok', finding:'Name ' + cf.name + ' agrees with ' + refs.map(r=>r[0] + ' (' + r[1] + ')').join(' and ') + '.' + (F.nameNote ? ' ' + F.nameNote : '') };
  }});

check({ id:'ADV-FORM-CNIC', group:'identity', ref:'R6', code:'R6', title:'CNIC number written on the form',
  applies: F => KIND(F, ...ADVANCES) && D(F).changeForm && D(F).changeForm.cnic && (D(F).cnics||[]).some(c=>(c.whose||'subscriber')==='subscriber' && c.number),
  run: F => {
    const cf = D(F).changeForm, card = D(F).cnics.find(c=>(c.whose||'subscriber')==='subscriber' && c.number);
    if (digits(cf.cnic) === digits(card.number)) return { status:'ok', finding:'CNIC ' + card.number + ' on the form agrees with the card.' };
    return { status:'adv', finding:'The ' + cf.label + ' records CNIC ' + cf.cnic + '; the card, the SAP pay slip and the QR codes read ' + card.number + '. The applicant is otherwise confirmed by personal number and name, and the CNIC field is not mandatory on this form (R6), so this is noted only.',
             remedy:'DDO to correct the CNIC on the form for the department’s record.', evidence:[ev(cf.page, cf.label, cf.cnicCrop), ev(card.page, 'CNIC', card.crop)],
             cure: docCure('Corrected ' + cf.label, 'set-form-cnic', [{k:'cnic',label:'CNIC on the corrected form',type:'text',expect:card.number}]) };
  }});

/* Balance before the advance under examination. */
function balanceBefore(F){
  if (F.balanceBasis) return F.balanceBasis;
  const s = D(F).sanction, amt = s && s.amount;
  const rc = F.sap && F.sap.recalc, ps = F.sap && F.sap.payslip;
  if (rc && rc.rows && rc.rows.length){
    const col = KIND(F,'refundable') ? 'tempAdvance' : 'permanentAdvance';
    const row = rc.rows.slice().reverse().find(r=>amt && r[col] && Math.abs(r[col] - amt) <= 1);
    if (row) return { value: row.opening, posted:true,
      explanation:'This advance (Rs ' + fmt(amt) + ') is already posted in the SAP re-calculation report for ' + row.start + ' to ' + row.end +
                  ', so the pay slip balance is after it. The balance before it is the opening balance of that year, Rs ' + fmt(row.opening) + '.' };
    const last = rc.rows[rc.rows.length-1];
    return { value:last.closing, explanation:'Closing balance Rs ' + fmt(last.closing) + ' for ' + last.start + ' to ' + last.end + ' in the SAP re-calculation report. This advance is not yet posted.' };
  }
  if (ps && ps.gpfBalance !== null && ps.gpfBalance !== undefined)
    return { value:ps.gpfBalance, provisional:true, explanation:'GPF balance Rs ' + fmt(ps.gpfBalance) + ' on the pay slip for ' + ps.month + '. Without the re-calculation report it cannot be confirmed whether this advance is already deducted.' };
  return null;
}

check({ id:'ADV-LIMIT', group:'balance', ref:'GPF Rules 1.14 to 1.18 · R9 · B1-i', code:'B1-i', title:'Advance within the limit set by the GP Fund Rules',
  applies: F => KIND(F, ...ADVANCES) && D(F).sanction && D(F).sanction.present,
  run: F => {
    const s = D(F).sanction, L = ADV_LIMITS[s.limitClause], b = balanceBefore(F);
    if (!L) return { status:'conf', finding:'The clause under which Rs ' + fmt(s.amount) + ' was sanctioned (' + (s.rule||'not quoted') + ') could not be matched to a limit in the Rules.', remedy:'Identify the clause; the limit is then applied.', cure:{ kind:'verify', vid:'ADV-LIMIT' } };
    if (!b) return { status:'sap', finding:'Sanctioned Rs ' + fmt(s.amount) + ' under ' + L.src + '. The SAP balance is needed to test the limit.', cure:{ kind:'sap' } };
    const pay = (F.sap && F.sap.payslip && F.sap.payslip.basicPay) || s.basicPay || null;
    const byPct = Math.floor(b.value * L.pct / 100);
    let limit = byPct, byPay = null;
    if (L.months && pay){ byPay = pay * L.months; limit = L.combine === 'max' ? Math.max(byPct, byPay) : Math.min(byPct, byPay); }
    const office = Math.floor(b.value * PARAMS.officeCapPct / 100);
    const calc = { amount:s.amount, balance:b.value, rule:L.src, label:L.label, pct:L.pct, months:L.months||null, combine:L.combine||null, pay, byPct, byPay, ruleLimit:limit, office, officePct:PARAMS.officeCapPct };
    const ruleText = L.src + ' (' + L.label.toLowerCase() + ') allows ' + (L.months ? (pay ? L.combine === 'max' ? 'the greater of ' : 'the lesser of ' : '') : '') + L.pct + '% of the balance' +
      (L.months ? (pay ? ' and ' + L.months + ' months’ pay (Rs ' + fmt(pay) + ' a month)' : ' (months of pay not known, so the percentage alone is applied)') : '') + ': Rs ' + fmt(limit) + '.';
    const flag = limit !== office ? ' Flag: the office’s stated practice of ' + PARAMS.officeCapPct + '% gives Rs ' + fmt(office) + ' for this balance, which differs from the Rules; the Rules are applied and the difference is listed under Rules in force.' : '';
    const stated = (s.balanceStated && Math.abs(s.balanceStated - b.value) > 1) ? ' The sanction itself states a balance of Rs ' + fmt(s.balanceStated) + ', which does not reconcile to SAP.' : '';
    const age = (L.minAge && s.ageAtSanction) ? (s.ageAtSanction.y >= L.minAge ? ' Age ' + s.ageAtSanction.y + ' years ' + (s.ageAtSanction.m||0) + ' months at sanction; the rule needs ' + L.minAge + '.' : null) : '';
    if (age === null) return { status:'hard', calc, finding:L.src + ' needs the subscriber to be ' + L.minAge + ' or over; the subscriber was ' + s.ageAtSanction.y + ' at sanction.', remedy:'Obtain a sanction under the rule that applies to the subscriber’s age.' };
    const basis = ' Balance used: ' + b.explanation;
    if (s.amount > limit) return { status:'hard', calc, finding:'Rs ' + fmt(s.amount) + ' exceeds the limit. ' + ruleText + ' Excess Rs ' + fmt(s.amount - limit) + '.' + basis + stated + (s.amount <= office ? ' The office’s 80% practice would have passed it; the Rules govern.' : ''),
      remedy:'Reduce the sanction to Rs ' + fmt(limit) + ' or less' + (L.relaxable ? ', or record special reasons in writing (' + L.relaxable + ')' : '') + '.' };
    if (b.provisional) return { status:'conf', calc, finding:'Rs ' + fmt(s.amount) + ' is within the limit on the pay slip balance. ' + ruleText + basis + flag, remedy:'Upload the re-calculation report to confirm the balance basis.', cure:{ kind:'sap' } };
    if (s.amount > office) return { status:'adv', calc, finding:'Rs ' + fmt(s.amount) + ' is within the Rules. ' + ruleText + ' It is above the office’s stated ' + PARAMS.officeCapPct + '% practice (Rs ' + fmt(office) + '), so it is flagged for the office to confirm which applies.' + basis + stated + age,
      remedy:'None under the Rules. The office to confirm whether its 80% practice overrides ' + L.src + '.' };
    return { status:'ok', calc, finding:'Rs ' + fmt(s.amount) + ' is within the limit. ' + ruleText + basis + stated + age + flag };
  }});

check({ id:'ADV-ACTIVE', group:'balance', ref:'R12 · Rule 1.14(1)(c) proviso', code:'R12', title:'No other refundable advance outstanding',
  applies: F => KIND(F,'refundable'),
  run: F => {
    const s = D(F).sanction || {}, rc = F.sap && F.sap.recalc, p = F.sap && F.sap.payslip;
    if (!rc || !rc.rows || !rc.rows.length){
      if (!p) return { status:'sap', finding:'The SAP pay slip and re-calculation report are needed to see any advance still outstanding.', cure:{ kind:'sap' } };
      if (!p.loanBalance) return { status:'ok', finding:'The SAP pay slip shows no GPF advance outstanding.' };
      return { status:'conf', finding:'The SAP pay slip shows a GPF advance balance of Rs ' + fmt(p.loanBalance) + '. Without the re-calculation report it cannot be told whether this is the advance under examination.', cure:{ kind:'sap' } };
    }
    const rows = rc.rows;
    let idx = -1;
    for (let i = rows.length-1; i >= 0; i--) if (s.amount && rows[i].tempAdvance && Math.abs(rows[i].tempAdvance - s.amount) <= 1){ idx = i; break; }
    const before = rows.slice(0, idx >= 0 ? idx : rows.length);
    let drawn = 0, rec = 0, lastRec = null;
    before.forEach(r=>{ drawn += r.tempAdvance||0; rec += r.recTempAdvance||0; if (r.recTempAdvance) lastRec = r; });
    const posted = idx >= 0 ? ' The advance under examination is already posted in ' + rows[idx].start + ' to ' + rows[idx].end +
      (p && p.loanBalance ? '; the pay slip advance balance of Rs ' + fmt(p.loanBalance) + ' is this advance being recovered (Rs ' + fmt(s.amount) + ' less Rs ' + fmt(s.amount - p.loanBalance) + ').' : '.') : '';
    if (drawn - rec > 1) return { status:'hard', finding:'Earlier refundable advances of Rs ' + fmt(drawn) + ' show recoveries of only Rs ' + fmt(rec) + ' in SAP: Rs ' + fmt(drawn - rec) + ' still outstanding when this advance was sanctioned.' + posted,
      remedy:'The earlier advance must be fully recovered before a new one (Rule 1.14(1)(c) proviso). A new advance may be settled only after the month in which it reached zero.' };
    if (!drawn) return { status:'ok', finding:'No earlier refundable advance in SAP since ' + rows[0].start + '.' + posted };
    return { status:'ok', finding:'Earlier refundable advances of Rs ' + fmt(drawn) + ' were fully recovered, the last recovery in ' + lastRec.start + ' to ' + lastRec.end + '.' + posted };
  }});

/* ── Final payments ─────────────────────────────────────────────────────── */
check({ id:'FP-GPF10', group:'checklist', checklist:'A2-ii', ref:'A2-ii · B2-i', code:'B2-i', title:'G.P.F. Form 10, properly filled and signed',
  applies: F => KIND(F, ...FINALS),
  run: F => {
    const g = D(F).gpf10;
    if (!g || !g.present) return { status:'hard', finding:'G.P.F. Form 10 is not on file' + (KIND(F,'residual') ? ', and nothing in the case substitutes for it.' : '.'), remedy:'Submit Form 10 signed by the DDO and the subscriber or claimant' + (KIND(F,'residual') ? ', or the officer confirms that the Form 10 filed with the original final payment covers the residual.' : '.'),
      cure: docCure('G.P.F. Form 10', 'add-gpf10', [{k:'accountNo',label:'GP Fund account no.',type:'text',expect:F.personnelNo},{k:'signed',label:'Signed by subscriber or claimant',type:'yesno'},{k:'ddoSigned',label:'Signed by DDO',type:'yesno'}]) };
    const miss = (g.missing || []).slice();
    if (!miss.length) return { status:'ok', finding:'Form 10 at page ' + g.page + ', account no. ' + (g.accountNo||'') + ', signed.' + (g.note ? ' ' + g.note : ''), evidence:[ev(g.page,'Form 10', g.crop)] };
    const p = F.sap && F.sap.payslip;
    const sapCovers = p && miss.every(m=>/account|a\/c|personnel/i.test(m)) && (p.oldGpfNo || p.persNo);
    return { status: sapCovers ? 'adv' : 'hard', finding:'Form 10 at page ' + g.page + ' does not state: ' + miss.join(', ') + '.' + (sapCovers ? ' ' + (g.corroboration || 'The missing identifiers are held in SAP') + ', so this is noted only.' : ''),
             remedy:'Complete Form 10: ' + miss.join(', ') + '.', evidence:[ev(g.page,'Form 10', g.crop)],
             cure: docCure('Completed G.P.F. Form 10', 'gpf10-complete', miss.map((m,i)=>({k:'m'+i,label:m+' now filled in',type:'yesno'}))) };
  }});

check({ id:'FP-NOTIF', group:'checklist', checklist:'A2-iii', ref:'A2-iii', title:'Retirement, dismissal or obituary notification',
  applies: F => KIND(F, ...FINALS),
  run: F => {
    const n = D(F).notification;
    if (n && n.present) return { status:'ok', finding:(n.label||'Notification') + ' No. ' + (n.no||'(not stated)') + ' dated ' + (n.date||'(not stated)') + ', page ' + n.page + '.' + (n.note ? ' ' + n.note : ''), evidence:[ev(n.page, n.label||'Notification', n.crop)] };
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
    return { status:'ok', finding:'Change Form-06 at page ' + cf.page + ', signed by the DDO and ' + (cf.sigKind === 'thumb' ? 'thumbed' : 'signed') + ' by the ' + (KIND(F,'death') ? 'claimant' : 'subscriber') + '.' + (cf.note ? ' ' + cf.note : ''), evidence:[ev(cf.page,'Form 06', cf.crop)] };
  }});

check({ id:'FP-OLDAC', group:'identity', ref:'B2-vii', code:'B2-vii', title:'Old GP Fund account no. on the change form',
  applies: F => KIND(F, ...FINALS) && D(F).changeForm && D(F).changeForm.present,
  run: F => {
    const cf = D(F).changeForm, p = F.sap && F.sap.payslip, rc = F.sap && F.sap.recalc;
    const sapOld = p && p.oldGpfNo && digits(p.oldGpfNo).length > 3 ? p.oldGpfNo : null;
    if (cf.oldGpfNo && digits(cf.oldGpfNo).length > 3){
      if (sapOld && digits(sapOld) !== digits(cf.oldGpfNo)) return { status:'hard', finding:'Old A/c ' + cf.oldGpfNo + ' on the form; SAP pay slip Old # reads ' + sapOld + '.', remedy:'Reconcile the old account number.' };
      return { status:'ok', finding:'Old GP Fund A/c ' + cf.oldGpfNo + ' on the form' + (sapOld ? ', agreeing with SAP Old # ' + sapOld + '.' : '.') };
    }
    if (sapOld) return { status:'adv', finding:'The old account number is not written on the form (' + (cf.oldGpfNoState || 'blank') + '), but SAP holds it as ' + sapOld + '. Noted; the office settles it from SAP.', remedy:'None needed to process.' };
    if (!p) return { status:'sap', finding:'The old account number is not written on the form. The SAP pay slip may carry it.', cure:{ kind:'sap' } };
    const first = rc && rc.rows && rc.rows[0];
    if (first && !first.opening) return { status:'ok', finding:'Field 16 is ' + (cf.oldGpfNoState || 'blank') + ', but SAP holds no old number and the SAP ledger opens at nil in ' + first.start + ' to ' + first.end + ', so there is no manual-era account to quote.' };
    return { status:'conf', finding:'Field 16 is ' + (cf.oldGpfNoState || 'blank') + ' and SAP holds no old number' + (first ? ', but the SAP ledger opens with Rs ' + fmt(first.opening) + ', so a manual-era account may exist.' : '.'),
             remedy:'Confirm the manual-era account number from the AG ledger.', cure:{ kind:'verify', vid:'FP-OLDAC' } };
  }});

check({ id:'FP-SB', group:'checklist', checklist:'A2-vii', ref:'A2-vii · B2-viii', code:'B2-viii', title:'Original Service Book (non-gazetted)',
  applies: F => KIND(F,'final','death','dismissal') && F.gazetted === 'non-gazetted',
  run: F => {
    const sb = D(F).serviceBook;
    const cure = docCure('Service Book pages', 'add-servicebook', [{k:'dor',label:'Date of retirement or event entered',type:'yesno'},{k:'order',label:'Order entered',type:'yesno'},{k:'leave',label:'Leave account present',type:'yesno'}]);
    if (!sb || !sb.present){
      if (sb && sb.reportedAttached){
        const v = verified(F, 'FP-SB');
        if (v) return v.ok ? { status:'ok', finding:'Original Service Book received and entries checked by ' + v.by + (v.note ? ': ' + v.note : '.') } : { status:'hard', finding:'Original Service Book not received, or entries missing. ' + (v.note||''), remedy:'Produce the original Service Book.', cure };
        return { status:'conf', finding:sb.reportedAttached + ' It is not in the scanned case, so the entries (date of the event, the order, leave account) cannot be checked from the file.', remedy:'Confirm the original Service Book is on hand and check the entries.', cure:{ kind:'verify', vid:'FP-SB' } };
      }
      return { status:'hard', finding:'No Service Book is on file for a non-gazetted subscriber.', remedy:'Produce the original Service Book.', cure };
    }
    const e = sb.entries || {}, miss = [];
    if (!e.dor) miss.push('date of retirement'); if (!e.order) miss.push('order of retirement'); if (!e.leave) miss.push('leave account');
    if (!miss.length) return { status:'ok', finding:'Service Book carries the requisite entries.' };
    const v = verified(F, 'FP-SB');
    if (v) return v.ok ? { status:'ok', finding:'Entries checked on the original Service Book by ' + v.by + (v.note ? ': ' + v.note : '.') }
                       : { status:'hard', finding:'The original Service Book does not show: ' + miss.join(', ') + '. ' + (v.note||''), remedy:'Department to complete the Service Book entries.', cure };
    /* a scan that holds only some pages is not evidence that entries are missing from the original */
    return { status:'conf', finding:'Only ' + (sb.note || 'pages ' + (sb.pages||[]).join(', ')) + ' of the Service Book are in the scanned case, so the ' + miss.join(', ') + ' cannot be seen. That does not show they are missing from the original.',
             remedy:'Check the entries on the original Service Book and record the result. If they are missing, the department completes them (B2-viii).',
             evidence:(sb.pages||[]).map(p=>ev(p,'Service Book')), cure:{ kind:'verify', vid:'FP-SB' } };
  }});

/* ── Final payment already posted in the SAP report ──────────────────────
   The reports in this corpus were pulled after the office processed the
   cases, so SAP already shows the claim as a permanent advance. Treat a
   posting equal to the claim as the claim itself, have the section confirm
   the pay order, and raise what is left as a residual. */
function postedClaim(F){
  const rows = F.sap && F.sap.recalc && F.sap.recalc.rows, c = F.claim;
  if (!rows || !rows.length || !c || !c.amount) return null;
  const i = rows.findIndex(r=>r.permanentAdvance && Math.abs(r.permanentAdvance - c.amount) <= PARAMS.claimTolerance);
  return i < 0 ? null : { row:rows[i], last:rows[rows.length-1] };
}

check({ id:'FP-POSTED', group:'balance', ref:'R11', code:'R11', title:'Claim already posted in SAP',
  applies: F => KIND(F,'final','death','dismissal') && !!(F.sap && F.sap.recalc && F.claim),
  run: F => {
    const p = postedClaim(F), rc = F.sap.recalc;
    if (!p) return { status:'ok', finding:'SAP posts no permanent advance equal to the claim, so nothing has been paid against it yet.' };
    const v = verified(F, 'FP-POSTED');
    if (v) return verifiedResult(v, 'The SAP posting is this claim; pay order recorded.', 'The SAP posting is a separate earlier payment, so paying the claim would pay it twice.');
    return { status:'conf', finding:'SAP already posts a permanent advance of Rs ' + fmt(p.row.permanentAdvance) + ' in ' + p.row.start + ' to ' + p.row.end + ', equal to the claim (' + (F.claim.basis || 'Rs ' + fmt(F.claim.amount)) + '). The report was pulled after the office processed the case, so this is most likely the claim itself. If it were a separate earlier payment, paying the claim would pay it twice.',
             remedy:'Before payment, confirm from the SAP ledger or the GP Fund Payment Register that the posting is this claim, and record the pay order.',
             evidence: rc.page ? [ev(rc.page, 'Re-calculation report')] : [], cure:{ kind:'verify', vid:'FP-POSTED' } };
  }});

check({ id:'FP-RESIDUAL', group:'balance', ref:'B2-vi', code:'B2-vi', title:'Balance left in SAP after the claim',
  applies: F => KIND(F,'final','death','dismissal') && !!postedClaim(F),
  run: F => {
    const p = postedClaim(F), left = p.last.closing, rc = F.sap.recalc;
    if (!(left > 0)) return { status:'ok', finding:'Nothing is left in SAP after the posting.' };
    if (F.claim.residualNote) return { status:'na', finding:'Rs ' + fmt(left) + ' is left in SAP after the posting. ' + F.claim.residualNote };
    return { status:'adv', finding:'After the Rs ' + fmt(F.claim.amount) + ' posting, SAP still holds Rs ' + fmt(left) + (F.claim.residualMadeOf ? ': ' + F.claim.residualMadeOf : '') + '. A residual payment appears due to the ' + (KIND(F,'death') ? 'entitled family' : 'subscriber') + '.',
             remedy:'Section to process the residual on a residual claim.', evidence: rc.page ? [ev(rc.page, 'Re-calculation report')] : [] };
  }});

/* ── Death cases (heirs, affidavit, succession, OSD) ─────────────────── */
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
    return { status:'hard', finding: a.present ? (a.label||'The document') + ' at page ' + a.page + ' is not an affidavit for lawful widow. ' + (a.note||'') : 'No affidavit for lawful widow is on file.',
             remedy:'Produce the original affidavit for lawful widow.', evidence: a.page ? [ev(a.page, a.label||'Document')] : [], cure: docCure('Original affidavit for lawful widow', 'add-affidavit', [{k:'original',label:'Original, on stamp paper, attested',type:'yesno'}]) };
  }});

check({ id:'DEATH-SUCCESSION', group:'checklist', checklist:'A2-vi', ref:'A2-vi · R13', code:'A2-vi', title:'Succession certificate, or OSD post created',
  applies: F => KIND(F,'death') && D(F).death,
  run: F => {
    const d = D(F).death, p = F.sap && F.sap.payslip;
    const osdSap = p && p.osdPost && /yes|created|osd/i.test(String(p.osdPost));
    if (osdSap) return { status:'ok', finding:'The SAP pay slip shows an OSD post created (' + p.osdPost + '). A succession certificate is not required (R13).' };
    if (d.successionCert === 'granted') return { status:'ok', finding:'Succession certificate granted, page ' + d.successionPage + '.' };
    if (d.successionRequired === false) return { status:'ok', finding:'Not required: ' + (d.successionNote || 'one widow and heirs within the family.') };
    if (!p) return { status:'sap', finding:'Succession certificate: ' + (d.successionNote||'not on file') + '. If SAP shows an OSD post created, it is not required (R13). Pull the pay slip first.', cure:{ kind:'sap' } };
    if (d.osdAnnotation){
      const v = verified(F, 'DEATH-OSD');
      if (v) return v.ok ? { status:'ok', finding:'OSD post creation confirmed in SAP by ' + v.by + (v.note ? ': ' + v.note : '') + '. Succession certificate not required (R13).' }
                         : { status:'hard', finding:'SAP does not show an OSD post, and no succession certificate is on file. ' + (d.successionNote||''), remedy:'Produce the succession certificate granted by the court.',
                             cure: docCure('Succession certificate', 'add-succession', [{k:'granted',label:'Certificate granted by the court',type:'yesno'}]) };
      return { status:'conf', finding:d.osdAnnotation.where + ' is annotated "' + d.osdAnnotation.text + '", but the SAP pay slip in the case carries no OSD post indicator. ' + (d.successionNote||''),
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
  const missing = ((ch.schedule||{}).items || []).filter(it=>!copies.some(c=>String(c.sr) === String(it.sr)));
  return { ok: copies.length > 0 && !noStamp.length && ch.toVerified, noStamp, missing, copies, ch };
}
[['MC-DDO-CERT','A4-iii','R14','Manual deduction certificate by DDO, with bills and acquaintance roll (non-gazetted period)','non-gazetted'],
 ['MC-AG-CERT','A4-iv','R15','Manual deduction certificate by AG Office (gazetted period)','gazetted']].forEach(([id, item, r, title, period])=>{
  check({ id, group:'checklist', checklist:item, ref:item + ' · ' + r, code:item, title,
    applies: F => KIND(F,'missing_credits') && (F.gazetted === period || F.gazetted === 'mixed' || F.gazetted === 'unknown'),
    run: F => {
      const x = challanSubstitute(F);
      if (x.ch.certificate && x.ch.certificate[period]) return { status:'ok', finding:'Certificate on file.' };
      if (x.ok) return { status:'sub', finding:'No certificate, but every one of the ' + x.copies.length + ' challans attached carries the bank’s stamp and the covering letter carries the Treasury Office verification (page ' + x.ch.toPage + '). Accepted in place of the certificate (' + r + ')' +
                           (F.gazetted === 'unknown' ? ', whichever period type applies.' : '.') + (x.missing.length ? ' Schedule ' + x.missing.map(m=>'Sr. ' + m.sr).join(', ') + ' is not covered; see A4-v.' : ''),
                         evidence:[ev(x.ch.toPage,'Treasury verification', x.ch.toCrop)] };
      const why = [];
      if (x.noStamp.length) why.push('challan' + (x.noStamp.length>1?'s':'') + ' at page ' + x.noStamp.map(c=>c.page).join(', ') + ' carr' + (x.noStamp.length>1?'y':'ies') + ' no bank stamp');
      if (!x.ch.toVerified) why.push('the covering letter carries no Treasury Office verification');
      if (!x.copies.length) why.push('no challans are attached');
      return { status:'hard', finding:'No certificate, and the challans cannot yet stand in for it: ' + why.join('; ') + '.',
               remedy:'Produce challan copies carrying the bank’s stamp' + (!x.ch.toVerified ? ' and obtain Treasury Office verification on the covering letter' : '') + ', or the certificate itself.',
               cure: x.noStamp.length ? docCure('Challan copy with bank stamp', 'challan-stamp', [{k:'page',label:'Replaces challan at page',type:'select',options:x.noStamp.map(c=>String(c.page))},{k:'bankStamp',label:'Bank stamp present on the new copy',type:'yesno'}])
                                      : docCure('Treasury-verified covering letter', 'to-verified', [{k:'toVerified',label:'Treasury Office verification stamp present',type:'yesno'}]) };
    }});
});

check({ id:'MC-STAMP', group:'checklist', ref:'R14 · R15', code:'R14', title:'Bank stamps legible on each challan',
  applies: F => KIND(F,'missing_credits') && ((D(F).challans||{}).copies||[]).some(c=>c.stampFaint),
  run: F => D(F).challans.copies.filter(c=>c.stampFaint).map(c=>({ sub:'p'+c.page, status:'adv', doc:'Challan Sr. ' + c.sr + ' (page ' + c.page + ')',
    finding:'The bank stamp is present but too faint to read the bank, branch or date. ' + (c.stampNote||''), remedy:'Confirm against the original, or upload a clearer copy.', evidence:[ev(c.page,'Bank stamp', c.crop)],
    cure: docCure('Clearer copy of challan Sr. ' + c.sr, 'challan-stamp-clear', [{k:'page',label:'Challan page',type:'select',options:[String(c.page)]},{k:'legible',label:'Bank stamp and date now legible',type:'yesno'}]) })) });

check({ id:'MC-CHALLANS', group:'checklist', checklist:'A4-v', ref:'A4-v', code:'A4-v', title:'Challans verified by Treasury, as scheduled',
  applies: F => KIND(F,'missing_credits'),
  run: F => {
    const ch = D(F).challans || {}, copies = ch.copies || [], sch = ch.schedule || {};
    const attached = copies.reduce((a,c)=>a + (c.amount||0), 0);
    const missing = (sch.items || []).filter(it=>!copies.some(c=>String(c.sr) === String(it.sr)));
    if (!missing.length && (!sch.total || Math.abs(attached - sch.total) <= 1)) return { status:'ok', finding:copies.length + ' challans attached, total Rs ' + fmt(attached) + ', agreeing with the Treasury-verified schedule of Rs ' + fmt(sch.total) + '.' };
    return { status:'hard', calc:{ attached, scheduled:sch.total, variance:(sch.total||0) - attached },
      finding:'The schedule lists ' + (sch.items||[]).length + ' challans for Rs ' + fmt(sch.total) + ', verified by the Treasury; ' + copies.length + ' are attached for Rs ' + fmt(attached) + '. ' +
              (missing.length ? 'Missing: ' + missing.map(m=>'Sr. ' + m.sr + ' (' + m.period + ', Rs ' + fmt(m.amount) + (m.cheque ? ', cheque ' + m.cheque : '') + ')').join('; ') + '. ' : '') +
              'Variance Rs ' + fmt((sch.total||0) - attached) + ', exactly the missing challan' + (missing.length > 1 ? 's' : '') + '.',
      remedy:'Attach the paid copy of the missing challan with the bank’s stamp and the Treasury verification mark, or amend the schedule and the Treasury verification.',
      evidence: ch.schedulePage ? [ev(ch.schedulePage, 'Schedule of challans', ch.scheduleCrop)] : [],
      cure: missing.length ? docCure('Challan Form 32-A, Sr. ' + missing[0].sr, 'add-challan', [{k:'sr',label:'Schedule Sr.',type:'text',expect:String(missing[0].sr)},{k:'amount',label:'Amount (Rs)',type:'number',expect:String(missing[0].amount)},{k:'bankStamp',label:'Bank stamp present',type:'yesno'}]) : null };
  }});

check({ id:'MC-GAZ', group:'sap', ref:'A4-iii · A4-iv · R1', title:'BPS and gazetted status of the subscriber',
  applies: F => KIND(F,'missing_credits') && F.gazetted === 'unknown' && !(F.sap && F.sap.payslip && F.sap.payslip.bps),
  run: F => ({ status:'sap', finding:'Neither BPS nor gazetted status is stated in the case (' + (F.gazettedEvidence||'') + '). It does not block: the challans satisfy both R14 and R15. Record it from the SAP pay slip.', cure:{ kind:'sap' } }) });

/* ── Balance transfer ───────────────────────────────────────────────────── */
check({ id:'BT-PROFORMA', group:'checklist', checklist:'A3-i', ref:'A3-i · R1', code:'A3-i', title:'Proforma particulars',
  applies: F => KIND(F,'balance_transfer'),
  run: F => {
    const pf = D(F).proforma || {}, p = F.sap && F.sap.payslip, rc = F.sap && F.sap.recalc, out = [];
    const E = [ev(pf.page,'Proforma', pf.crop)];
    const persOnly = v => /personal|pers|p\s*#/i.test(v||'') || digits(v) === digits(F.personnelNo);
    out.push((pf.name && pf.father && pf.designation)
      ? { sub:'particulars', status:'ok', doc:'Name, father name, designation, personnel no.', finding:pf.name + ' s/o ' + pf.father + ', ' + pf.designation + ', personnel no. ' + F.personnelNo + '.', evidence:E }
      : { sub:'particulars', status:'hard', doc:'Name, father name, designation', finding:'Particulars missing from the proforma.', remedy:'Complete the proforma.', evidence:E });
    out.push(pf.periods ? { sub:'periods', status:'ok', doc:'Period of posting', finding:'Stated in column 7: ' + pf.periods + '.', evidence:[ev(pf.page,'Periods', pf.periodsCrop)] }
                        : { sub:'periods', status:'hard', doc:'Period of posting', finding:'The periods of posting are not stated.', remedy:'State the periods of posting.' });
    if (pf.newAc && persOnly(pf.newAc) && pf.daoConfirmed)
      out.push({ sub:'dao-ac', status:'ok', doc:'GP Fund A/c No. in the DAO (column 5)', finding:'Column 5 gives the personnel number, which keys the GP Fund account in SAP, and the respective DAO has confirmed it: "' + pf.daoConfirmed + '".', evidence:[ev(pf.page,'DAO confirmation', pf.daoCrop)] });
    else if (pf.newAc) out.push({ sub:'dao-ac', status:'ok', doc:'GP Fund A/c No. in the DAO (column 5)', finding:'Stated: ' + pf.newAc + '.' });
    else out.push({ sub:'dao-ac', status:'hard', doc:'GP Fund A/c No. in the DAO (column 5)', finding:'Not stated, and not confirmed by the DAO.', remedy:'State the account number and obtain DAO confirmation.',
                    cure: docCure('Completed proforma', 'proforma', [{k:'newAc',label:'New A/c no. (column 5)',type:'text'}]) });
    if (pf.oldAc && !persOnly(pf.oldAc) && digits(pf.oldAc).length > 3) out.push({ sub:'old-ac', status:'ok', doc:'Old GP Fund A/c No. (column 4)', finding:'Stated: ' + pf.oldAc + '.' });
    else if (!p) out.push({ sub:'old-ac', status:'sap', doc:'Old GP Fund A/c No. (column 4)', finding:'Column 4 repeats the personnel number. SAP carries any old manual account number (pay slip Old #, re-calculation report), so the section reads it from the extract before treating it as a department defect.', cure:{ kind:'sap' } });
    else if (p.oldGpfNo) out.push({ sub:'old-ac', status:'ok', doc:'Old GP Fund A/c No. (column 4)', finding:'Column 4 repeats the personnel number; SAP holds the old number as ' + p.oldGpfNo + '. Settled from SAP.' });
    else if (rc && rc.rows && rc.rows.length && !rc.rows[0].opening) out.push({ sub:'old-ac', status:'ok', doc:'Old GP Fund A/c No. (column 4)', finding:'SAP holds no old number and the ledger opens at nil in ' + rc.rows[0].start + ', so no manual-era account exists.' });
    else out.push({ sub:'old-ac', status:'hard', doc:'Old GP Fund A/c No. (column 4)', finding:'Column 4 repeats the personnel number and SAP does not supply an old account number.', remedy:'Department to state the old GP Fund account number allotted by AG Punjab, or "none allotted".',
                    cure: docCure('Department statement of old A/c no.', 'proforma', [{k:'oldAc',label:'Old A/c no.',type:'text'}]) });
    if (pf.lastDeduction) out.push({ sub:'last-ded', status:'ok', doc:'Treasury voucher and date of last deduction (column 6)', finding:'Stated: ' + pf.lastDeduction + '.' });
    else if (rc && rc.rows && rc.rows.length){ const last = rc.rows.slice().reverse().find(r=>r.subscription); out.push({ sub:'last-ded', status:'ok', doc:'Last fund deduction (column 6)', finding:'Column 6 is blank; SAP shows the last subscriptions posted in ' + (last ? last.start + ' to ' + last.end : 'the report') + '. Read from SAP.' }); }
    else out.push({ sub:'last-ded', status:'sap', doc:'Last fund deduction (column 6)', finding:'Column 6 is blank. The last GP Fund deduction is read from the SAP re-calculation report, which the section pulls itself.', cure:{ kind:'sap' } });
    if (rc && rc.rows && rc.rows.length){
      const recent = rc.rows.slice(-2).filter(r=>r.tempAdvance || r.permanentAdvance);
      out.push(recent.length ? { sub:'adv12', status:'conf', doc:'Advances in the last twelve months (column 7)', finding:'SAP shows advances in ' + recent.map(r=>r.start + ' to ' + r.end + ' (Rs ' + fmt((r.tempAdvance||0)+(r.permanentAdvance||0)) + ')').join('; ') + '. Carry any outstanding recovery with the transfer.', cure:{ kind:'verify', vid:'BT-ADV' } }
                             : { sub:'adv12', status:'ok', doc:'Advances in the last twelve months (column 7)', finding:'Nil per SAP.' });
    } else out.push({ sub:'adv12', status:'sap', doc:'Advances in the last twelve months (column 7)', finding:'No figure or nil entered; column 7 was used for the posting periods. Any advance or outstanding recovery is read from SAP before the balance is transferred.', cure:{ kind:'sap' } });
    return out;
  }});

/* ═══════════════════════════════════════════════════════════════════════
   CURES: how a confirmed upload changes the facts. The rules then decide.
   ═══════════════════════════════════════════════════════════════════════ */
const up = (file) => 'upload: ' + file;
const CURES = {
  'add-sanction': (F,v,f)=>{ F.docs.sanction = Object.assign(F.docs.sanction||{}, {present:true, page:up(f), orderNo:v.orderNo, date:v.date, amount:num(v.amount), rule:v.rule}); },
  'set-sanction-rule': (F,v)=>{ Object.assign(F.docs.sanction, {rule:v.rule || F.docs.sanction.rule, reason:v.reason || F.docs.sanction.reason}); },
  'sanction-qr': (F,v,f)=>{ F.qr = (F.qr||[]).filter(q=>q.id!=='sanction-upload');
    F.qr.push({id:'sanction-upload', page:up(f), doc:'uploaded QR-coded sanction', symbology:'QR code', decoded:true, payload:v.payload,
               compare:[{field:'Content', qrVal:v.payload||'(not entered)', docVal:'the printed sanction', docLabel:'sanction', match:yes(v.agrees)}]});
    F.docs.sanction.qrId = 'sanction-upload'; },
  'add-cnic': (F,v,f)=>{ F.docs.cnics = F.docs.cnics||[]; F.docs.cnics.push({page:up(f), whose:'subscriber', type:v.type||'smart', number:v.number, attested:false}); },
  'add-form': (F,v,f)=>{ const lab = KIND(F,'refundable') ? 'FORM PAY 05' : 'FORM PAY 06';
    F.docs.changeForm = Object.assign(F.docs.changeForm||{}, {present:true, label:lab, page:up(f), personalNo:v.personalNo, sigKind: yes(v.signed)?'signature':'none', ddoSigned: yes(v.ddoSigned)}); },
  'ddo-signed': (F,v)=>{ F.docs.changeForm.ddoSigned = yes(v.ddoSigned); },
  'form-signed': (F,v)=>{ F.docs.changeForm.sigKind = yes(v.signed) ? 'signature' : 'none'; },
  'form-signatures': (F,v)=>{ if (yes(v.ddoSigned)) F.docs.changeForm.ddoSigned = true; if (yes(v.signed) && (!F.docs.changeForm.sigKind || F.docs.changeForm.sigKind==='none')) F.docs.changeForm.sigKind = 'signature'; },
  'set-form-persno': (F,v)=>{ F.docs.changeForm.personalNo = v.personalNo; },
  'set-form-cnic': (F,v)=>{ F.docs.changeForm.cnic = v.cnic; },
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
  'challan-stamp-clear': (F,v)=>{ const c = F.docs.challans.copies.find(x=>String(x.page)===String(v.page)); if (c && yes(v.legible)) c.stampFaint = false; },
  'to-verified': (F,v)=>{ F.docs.challans.toVerified = yes(v.toVerified); },
  'add-challan': (F,v,f)=>{ F.docs.challans.copies.push({page:up(f), sr:v.sr, amount:num(v.amount), bankStamp:yes(v.bankStamp)}); },
  'proforma': (F,v)=>{ Object.assign(F.docs.proforma, {oldAc:v.oldAc || F.docs.proforma.oldAc, newAc:v.newAc || F.docs.proforma.newAc, lastDeduction:v.lastDeduction || F.docs.proforma.lastDeduction}); }
};
