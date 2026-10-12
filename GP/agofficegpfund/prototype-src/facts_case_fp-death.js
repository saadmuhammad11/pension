/* Final Payment, Death Case: Subscriber B. Test, Sweeper (BS-02), Govt. Associate College (W) Mustafabad */
defCase('fp-death', {
  label:'Final Payment, Death Case', kind:'death', family:'FINAL_PAYMENT',
  sub:'Final payment on death in service, claim by the widow',
  subject:'Subscriber B. Test (deceased), Sweeper (BS-02)', dept:'Govt. Associate College (W) Mustafabad, Lahore (Education)',
  personnelNo:'90000417', pages:13, diary:'20064, 24-02-2026', gazetted:'non-gazetted',
  note:'Subscriber B. Test, Sweeper, died 03-04-2024. The Rs 92,482 claim reconciles to SAP. The widow thumbs; no affidavit for lawful widow, no Service Book, CNIC copies missing for two heirs, and Form 06 carries a personnel number one digit off.',
  persNos:[{doc:'GPF-10 (account no.)',page:1,value:'90000417'},{doc:'FORM PAY 06',page:12,value:'30890417'},{doc:'SAP pay slip, November 2023',page:11,value:'90000417'},{doc:'GPF Final Re-calculation Report',page:13,value:'90000417'}],
  record:[
    ['Deceased subscriber','Subscriber B. Test s/o Father B. Test, Sweeper (BS-02)','GPF-10 · obituary · NADRA · SAP',0.98,1],
    ['Personnel no. / GP Fund A/c','90000417; Form 06 reads 30890417','GPF-10 · SAP · report · Form 06',0.93,12],
    ['CNIC','00001-0000107-1 (old card, attested; the faded copy reads ...071-1, NADRA documents and SAP give ...676-1)','CNIC · NADRA certificates · pay slip',0.95,5],
    ['Death','03-04-2024 in service; first entry into service 02-11-2008','Obituary No. 1612/GACWM · NADRA death certificate',0.98,2],
    ['Claimant','Mst Claimant B. Test, widow, 00001-0000103-8 (smart card)','CNIC · FRC · Form 06',0.96,6],
    ['Legal heirs (NADRA FRC)','Widow; son Son B. Test (born 17-08-2002); daughter Daughter B. Test (born 28-09-2005, 18 since 28-09-2023)','FRC · decline certificate · court application',0.95,4],
    ['Claimed','Rs 92,482 on Form 06','Form 06',0.97,12],
    ['SAP basis of the claim','Closing 30-06-2025 Rs 87,182 plus five months at Rs 1,060','Re-calculation report',0.97,13],
    ['SAP posting','Permanent advance Rs 92,482 in 2025-26, leaving Rs 9,131','Re-calculation report',0.97,13],
    ['Advances','Rs 36,000 (2019-20) fully recovered; Rs 78,000 (2023-24) with Rs 60,000 unrecovered, already netted','Report · pay slip',0.95,13],
    ['OSD post','Form 06 annotated "(Death case) OSD post created"; NADRA decline lists "Creation The OSD Post"; pay slip on file predates the death','Form 06 · decline certificate',0.90,12],
    ['Succession','NADRA decline (a minor heir) and a court application; no grant','Pages 3, 7, 8',0.95,3]
  ],
  docs:{
    covering:{ present:true, page:1, author:'the Principal, Govt. Associate College (W) Mustafabad', nature:'Revised GPF-10 issued under Memo No. 667/GACWM dated 24-07-2025 with the printed forwarding line' },
    gpf10:{ present:true, page:1, accountNo:'90000417', crop:'fp-death_p001_item3_family_list_blank.png',
      missing:['item 3(ii), the family members entitled under Rule 1.34, the rule and their applications'] },
    notification:{ present:true, page:2, label:'Obituary notification', no:'1612/GACWM', date:'06-04-2024', note:'Death on 03-04-2024; the NADRA death registration certificate agrees.' },
    cnics:[
      { page:5, whose:'deceased subscriber', type:'old', number:'00001-0000107-1', name:'Subscriber B. Test', attested:true, attestedBy:'Principal, GAC (W) Mustafabad', crop:'fp-death_p005_cnic_subscriber_front.png' },
      { page:6, whose:'widow', type:'smart', number:'00001-0000103-8', name:'Claimant B. Test', attested:true, attestedBy:'Principal, GAC (W) Mustafabad', crop:'fp-death_p006_cnic_widow_front.png', sigCrop:'fp-death_p006_cnic_widow_holder_signature_box.png' } ],
    changeForm:{ present:true, label:'FORM PAY 06', page:12, personalNo:'30890417', name:'Subscriber B. Test', sigKind:'thumb', ddoSigned:true,
      ddoStamp:'Principal, Govt. Associate College (W) Mustafabad', ddoCrop:'fp-death_p012_ddo_signature_stamp.png', crop:'fp-death_p012_loan_details_amount.png',
      oldGpfNo:'', oldGpfNoState:'written as what seems to read "-nil-"', note:'Payee noted as the widow, Mst Claimant B. Test; amount Rs 92,482; annotated "(Death case) OSD post created".' },
    serviceBook:{ present:false },
    death:{
      widowClaim:true,
      heirs:[ { name:'Claimant B. Test', relation:'widow', cnicCopy:true },
              { name:'Son B. Test', relation:'son, born 17-08-2002', cnicCopy:false },
              { name:'Daughter B. Test', relation:'daughter, born 28-09-2005, 18 since 28-09-2023', cnicCopy:false } ],
      affidavit:{ present:true, original:false, page:9, label:'The undertaking on Rs 100 stamp paper',
        note:'It covers liability for Government dues, is worded for family pension, is undated, and the claimant has not signed it. The NADRA FRC and the court application support her status but are not the affidavit.' },
      successionRequired:false,
      successionNote:'one widow, and the heirs (widow, son, daughter) are all family, so circular A.2(vi) does not require a certificate. The case holds a NADRA decline, given because an heir was a minor, and a court application with no grant.',
      osdAnnotation:{ page:12, where:'Form 06 page 12', text:'(Death case) OSD post created', crop:'fp-death_p012_osd_post_annotation.png' }
    }
  },
  claim:{ amount:92482, expected:92482, page:12, basis:'SAP closing balance at 30-06-2025 of Rs 87,182 plus five months at Rs 1,060',
    residualMadeOf:'the 2025-26 interest (Rs 8,071) and one further month’s subscription (Rs 1,060), neither in the claim' },
  qr:[
    { id:'decline-qr', page:3, doc:'NADRA succession decline certificate', symbology:'QR code', decoded:true, route:'online', host:'id.nadra.gov.pk', crop:'fp-death_p003_qr_decline_cert.png',
      payload:'https://id.nadra.gov.pk/e-succession_certificate?300101007531',
      compare:[ {field:'document number', qrVal:'300101007531', docVal:'300101007531', docLabel:'certificate and its Code 39 barcode', match:true} ],
      portal:{ ok:false, checkedOn:'15-09-2026', result:'NADRA refused the request from outside its network, HTTP 403' } },
    { id:'frc-qr', page:4, doc:'NADRA family registration certificate', symbology:'QR code', decoded:true, route:'online', host:'id.nadra.gov.pk', crop:'fp-death_p004_qr_frc.png',
      payload:'https://id.nadra.gov.pk/e-frc/verifyFrcApplication?505295769494',
      compare:[ {field:'Code 39 document no.', qrVal:'EA80580288', docVal:'EA80580288', docLabel:'certificate', match:true} ],
      portal:{ ok:false, checkedOn:'15-09-2026', result:'NADRA refused the request from outside its network, HTTP 403' } },
    { id:'widow-cnic-qr', page:6, doc:'widow’s smart CNIC back', symbology:'QR code', decoded:true, payload:'50459132685600001000010381', crop:'fp-death_p006_qr_smart_cnic_widow.png',
      compare:[ {field:'CNIC number', qrVal:'00001-0000103-8', docVal:'00001-0000103-8', docLabel:'card', match:true} ] },
    { id:'death-cert-qr', page:10, doc:'NADRA death registration certificate', symbology:'QR code', decoded:true, route:'online', host:'crms.nadra.gov.pk', crop:'fp-death_p010_qr_death_registration.png',
      payload:'https://crms.nadra.gov.pk/verify?TrackingID=OxyaJaOyf6Rl2ZxYviapTA==', compare:[],
      portal:{ ok:false, checkedOn:'15-09-2026', result:'the CRMS server refused the connection' } },
    { id:'old-cnic-barcode', page:5, doc:'deceased’s old CNIC back', symbology:'PDF417 barcode', decoded:false, why:'faded photocopy' }
  ],
  signatures:[
    { id:'gpf10-ddo', page:1, doc:'GPF-10', role:'ddo', roleLabel:'DDO signature', authority:'Principal, Govt. Associate College (W) Mustafabad, Lahore',
      signedBy:'Principal, Govt. Associate College (W) Mustafabad', forMarker:false, crop:'fp-death_p001_ddo_signature_stamp.png' }
  ],
  thumbs:[
    { id:'gpf10', page:1, doc:'GPF-10', whose:'The claimant (not named at the mark; presumably the widow)', crop:'fp-death_p001_thumb_gpf10.png' },
    { id:'form06', page:12, doc:'FORM PAY 06, three impressions in the specimen signature block', whose:'The claimant (not named; the form names the widow as payee)', crop:'fp-death_p012_employee_specimen_thumbs.png' }
  ],
  custom:['DEATH-PERSNO','DEATH-CLAIM','DEATH-POSTDEATH','DEATH-PERIOD']
});

CUSTOM_CHECKS['DEATH-PERSNO'] = { id:'DEATH-PERSNO', group:'identity', ref:'R6 · identity', code:'R6', title:'Personnel number on Form 06',
  applies: F => true,
  run: F => {
    const v = verified(F, 'DEATH-PERSNO');
    if (v) return verifiedResult(v, 'Personnel number on the original Form 06 confirmed as 90000417.', 'Form 06 carries the wrong personnel number (30890417); a corrected Form 06 is needed before posting.');
    return { status:'conf', finding:'Form 06 reads 30890417: the third box holds a closed double-loop 8, unlike the 9 beside it. SAP, the GPF-10 and the re-calculation report all give 90000417, and the name, grade and DDO code match, so the form concerns the right person but carries a number one digit off. Posting against 30890417 would reach the wrong account.',
      remedy:'Check the original. If it reads 30890417, the department sends a corrected Form 06 (upload it here).', evidence:[ev(12,'Personnel number boxes','fp-death_p012_personal_number_boxes.png')], cure:{ kind:'verify', vid:'DEATH-PERSNO' } };
  }};

CUSTOM_CHECKS['DEATH-CLAIM'] = { id:'DEATH-CLAIM', group:'balance', ref:'R11', code:'R11', title:'Claim against the SAP re-calculation report',
  applies: F => true,
  run: F => {
    const rows = F.sap && F.sap.recalc && F.sap.recalc.rows, p = F.sap && F.sap.payslip;
    if (!rows || !rows.length) return { status:'sap', finding:'The claim of Rs 92,482 cannot be tested without the GPF Final Re-calculation Report.', remedy:'Pull the report for personnel no. 90000417.', cure:{ kind:'sap' } };
    const base = rows.find(r=>/30\.06\.2025/.test(r.end));
    const sub = (p && p.gpfSubscription) || 1060;
    if (!base) return { status:'conf', finding:'The report has no row closing on 30-06-2025 to test the claim against.', cure:{ kind:'verify', vid:'DEATH-CLAIM' } };
    const expected = base.closing + 5 * sub;
    if (expected === F.claim.amount) return { status:'ok', finding:'Rs ' + fmt(F.claim.amount) + ' claimed = SAP closing balance at 30-06-2025 of Rs ' + fmt(base.closing) + ' + five months at Rs ' + fmt(sub) + '. The unrecovered Rs 60,000 of the 2023-24 advance is already netted in the SAP balance.', evidence:[ev(13,'Re-calculation report','fp-death_p013_recalc_table.png')] };
    return { status:'hard', code:'B2-vi', finding:'Rs ' + fmt(F.claim.amount) + ' claimed, but the SAP closing balance at 30-06-2025 plus five months gives Rs ' + fmt(expected) + '.', remedy:'Department to correct the claim to the SAP figure.', evidence:[ev(13,'Re-calculation report')] };
  }};

CUSTOM_CHECKS['DEATH-POSTDEATH'] = { id:'DEATH-POSTDEATH', group:'balance', ref:'B2-vi · R14', code:'B2-vi', title:'Subscriptions after the death',
  applies: F => !!(F.sap && F.sap.recalc),
  run: F => {
    const v = verified(F, 'DEATH-POSTDEATH');
    if (v) return verifiedResult(v, 'Post-death subscriptions and interest checked against the SAP pay history.', 'Post-death credits are not reconciled; to be corrected before payment.');
    return { status:'conf', finding:'SAP credits no subscription in 2024-25 and six months (Rs 6,360) in 2025-26, after the death on 03-04-2024, and the forms note "1060/- 03/26". This fits pay drawn against the OSD post. The Rules say nothing on subscriptions after death, and interest may be capped under Rule 1.13(4) once the balance became payable.',
      remedy:'Check the SAP pay history for the OSD post and confirm which post-death credits and interest are admissible (open item GPF-O17).', evidence:[ev(13,'Re-calculation report','fp-death_p013_recalc_last_rows.png')], cure:{ kind:'verify', vid:'DEATH-POSTDEATH' } };
  }};

CUSTOM_CHECKS['DEATH-PERIOD'] = { id:'DEATH-PERIOD', group:'checklist', ref:'B2-ii', code:'B2-ii', title:'Subscription period against service',
  applies: F => !!(F.sap && F.sap.recalc),
  run: F => {
    const v = verified(F, 'DEATH-PERIOD');
    if (v) return verifiedResult(v, 'Subscription period reconciled with service.', 'Subscription period does not reconcile with service.');
    return { status:'conf', finding:'Service began on 02-11-2008, but SAP subscriptions start in 2009-10 with only Rs 650. That may be the first-year exemption, low early rates or missing credits. The Service Book is not on file to check.',
      remedy:'Compare with the Service Book once it is produced.', cure:{ kind:'verify', vid:'DEATH-PERIOD' } };
  }};
