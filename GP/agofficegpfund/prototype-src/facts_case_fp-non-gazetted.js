/* Final Payment, Non-Gazetted: Subscriber A. Test, Driver, Highway Mechanical Division Lahore */
defCase('fp-non-gazetted', {
  label:'Final Payment, Non-Gazetted', kind:'final', family:'FINAL_PAYMENT',
  sub:'Final payment on superannuation, non-gazetted',
  subject:'Subscriber A. Test, Driver (BS-05/06)', dept:'Highway Mechanical Division, Lahore (C&W)',
  personnelNo:'90000374', pages:9, diary:'214465 / 989082, 11-08-2026', gazetted:'non-gazetted',
  note:'Subscriber A. Test, Driver, retired 09-06-2026. SAP pay slip and report in the case. Service Book pages lack the retirement entries; SAP shows an unexplained posting of Rs 74,178.',
  persNos:[{doc:'GPF-10 (account no.)',page:1,value:'90000374'},{doc:'FORM PAY 06',page:5,value:'90000374'},{doc:'SAP pay slip, June 2026',page:8,value:'90000374'},{doc:'GPF Final Re-calculation Report',page:9,value:'90000374'}],
  record:[
    ['Subscriber','Subscriber A. Test s/o Father A. Test, Driver','GPF-10 · office order · CNIC · SAP',0.98,1],
    ['Personnel no. / GP Fund A/c','90000374','GPF-10 · Form 06 · Service Book · SAP',0.99,1],
    ['Old GP Fund A/c','017-00-171471 (SAP Old # 01700171471); not on the GPF-10','Form 06 · Service Book · pay slip',0.97,5],
    ['CNIC','00001-0000102-9 (old-style card, attested)','CNIC · Form 06 · pay slip',0.97,3],
    ['Retirement','09-06-2026 (A.N.), Office Order 402/E/HMC of 03-06-2026','Office order',0.99,2],
    ['Scale','BS-05 on the office order; 06 on Form 06 and the SAP pay slip','Office order · Form 06 · pay slip',0.93,2],
    ['DDO code','LO5361 (previous version misread it as 405361)','Form 06 · pay slip',0.95,5],
    ['SAP balance, June 2026 pay slip','Rs 74,178 (principal, before 2025-26 interest)','SAP pay slip',0.98,8],
    ['SAP closing 30-06-2026','Rs 82,332','SAP re-calculation report',0.98,9],
    ['SAP posting 2026-27','Permanent advance Rs 74,178, leaving Rs 8,154','SAP re-calculation report',0.96,9],
    ['Service Book','Cover and particulars page only','Pages 6 and 7',0.95,6]
  ],
  docs:{
    covering:{ present:true, page:1, author:'the Executive Engineer, Highway Mechanical Division, Lahore', nature:'Pre-printed forwarding endorsement at the foot of the GPF-10' },
    gpf10:{ present:true, page:1, accountNo:'90000374', missing:['old GP Fund A/c number'], crop:'fp-non-gazetted_p001_gpf10_name_dor_account.png',
      corroboration:'The old number 017-00-171471 is on Form 06, the Service Book cover and the SAP pay slip (Old # 01700171471)' },
    notification:{ present:true, page:2, label:'Retirement office order', no:'402/E/HMC', date:'03-06-2026', crop:'fp-non-gazetted_p002_office_order_402_body.png',
      note:'Driver (BS-05), retired w.e.f. 09-06-2026 (A.N.) on superannuation; attested by the Executive Engineer HMD Lahore.' },
    cnics:[ { page:3, whose:'subscriber', type:'old', number:'00001-0000102-9', name:'Subscriber A. Test', expiry:'lifetime', attested:true, attestedBy:'Executive Engineer, HMD Lahore' } ],
    changeForm:{ present:true, label:'FORM PAY 06', page:5, personalNo:'90000374', name:'Subscriber A. Test', cnic:'00001-0000102-9', sigKind:'signature', ddoSigned:true,
      ddoStamp:'Executive Engineer, Highway Mechanical Division, Lahore', oldGpfNo:'017-00-171471',
      note:'100% of balance ticked. "For the month of 08/2026" is the processing month of the entry, not a deduction month.' },
    serviceBook:{ present:true, pages:[6,7], entries:{ dor:false, order:false, leave:false }, note:'cover No. 3194307 and the particulars page only' }
  },
  qr:[ { id:'cnic-barcode', page:4, doc:'old-style CNIC back', symbology:'PDF417 barcode', decoded:false, why:'halftone photocopy',
         remedy:'Verify CNIC 00001-0000102-9 through NADRA Verisys, or upload a clear scan of the back of the card.' } ],
  signatures:[
    { id:'gpf10-ddo', page:1, doc:'GPF-10 forwarding', role:'ddo', roleLabel:'DDO signature', authority:'Executive Engineer, Highway Mechanical Division, Lahore',
      signedBy:'Executive Engineer, Highway Mechanical Division', forMarker:false, crop:'fp-non-gazetted_p001_gpf10_ddo_ee_signature_stamp.png', bbox:[1300,2270,2150,2740] }
  ],
  claim:{ amount:74178, basis:'100% of the balance on Form 06, Rs 74,178 on the June 2026 SAP pay slip', residualMadeOf:'the 2025-26 interest (Rs 8,154), credited after the June pay slip was drawn' },
  custom:['NG-ADJUST','NG-PERIOD','NG-SCALE']
});

CUSTOM_CHECKS['NG-ADJUST'] = { id:'NG-ADJUST', group:'balance', ref:'B2-vi', code:'B2-vi', title:'Adjustments and possible missing credits in the re-calculation report',
  applies: F => !!(F.sap && F.sap.recalc),
  run: F => {
    const v = verified(F, 'NG-ADJUST');
    if (v) return verifiedResult(v, 'Adjustments explained; no missing credits.', 'Missing credits confirmed; to be processed with missing-credit documents first.');
    return { status:'conf', finding:'(a) Adjustment of Rs 670 in 2004-05. (b) Adjustment of Rs 1,420 less in 2025-26, one month’s subscription. (c) Temporary advances of Rs 49,600 against recoveries of Rs 49,100: Rs 500 not credited back. (d) 1998-99 subscription Rs 550 against Rs 600 in the years either side. Every row is arithmetically consistent.',
      remedy:'Confirm whether these are genuine adjustments or missing credits. If missing credits, they are processed first with a DDO certificate or bank-stamped, Treasury-verified challans (R14).', cure:{ kind:'verify', vid:'NG-ADJUST' } };
  }};

CUSTOM_CHECKS['NG-PERIOD'] = { id:'NG-PERIOD', group:'checklist', ref:'B2-ii', code:'B2-ii', title:'Subscription period against service',
  applies: F => !!(F.sap && F.sap.recalc),
  run: F => {
    const v = verified(F, 'NG-PERIOD');
    if (v) return verifiedResult(v, 'Subscription period reconciled with the date of appointment.', 'Subscription period does not reconcile with service.');
    return { status:'conf', finding:'SAP credits subscriptions from 1988-89 (Rs 75, about three months) to June 2026. The pay slip prints 38 years 10 months of service, which points to appointment around August 1987. The Service Book pages supplied do not show the date of first appointment.',
      remedy:'Reconcile the start of subscription with the date of appointment in the Service Book.', cure:{ kind:'verify', vid:'NG-PERIOD' } };
  }};

CUSTOM_CHECKS['NG-SCALE'] = { id:'NG-SCALE', group:'identity', ref:'Outside the list', code:'OFF_LIST', title:'Scale on the retirement order',
  applies: F => true,
  run: F => ({ status:'ok', finding:'Noted only: the retirement order describes the subscriber as Driver (BS-05); Form 06 and the SAP pay slip give 06. It does not affect a GP Fund final payment, which is computed from SAP balances, and it is not on the circular’s list, so it is not raised.',
    evidence:[ev(2,'Office order'), ev(8,'SAP pay slip')] }) };
