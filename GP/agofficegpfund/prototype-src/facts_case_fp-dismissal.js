/* Final Payment, Dismissal from Service: Subscriber C. Test, Traffic Warden No. 2709/TW */
defCase('fp-dismissal', {
  label:'Final Payment, Dismissal from Service', kind:'dismissal', family:'FINAL_PAYMENT',
  sub:'Final payment after dismissal from service',
  subject:'Subscriber C. Test, Traffic Warden (BS-14)', dept:'City Traffic Police, Chief Traffic Officer, Lahore',
  personnelNo:'90000834', pages:9, diary:'983415 / 208238, 21-05-2026', gazetted:'non-gazetted',
  note:'Subscriber C. Test, dismissed 30-12-2023. Every circular document except the Service Book is in the scan. E-stamp verified on the Punjab portal; the punishment order QR cannot be read.',
  persNos:[{doc:'FORM PAY 06',page:1,value:'90000834'},{doc:'Application (GPF-10)',page:2,value:'90000834'},{doc:'SAP pay slip, December 2023',page:7,value:'90000834'},{doc:'GPF Final Re-calculation Report',page:9,value:'90000834'}],
  record:[
    ['Subscriber','Subscriber C. Test s/o Father C. Test, Traffic Warden No. 2709/TW','Form 06 · application · CNIC · e-stamp',0.97,1],
    ['Personnel no.','90000834','Form 06 · application · SAP',0.99,1],
    ['CNIC','00001-0000105-9 (smart card, front only)','Form 06 · Urdu application · CNIC copy',0.97,6],
    ['Dismissal','30-12-2023, Order 1823-33/PA-STO/S of the Senior Traffic Officer, Saddar Division','Punishment order · application',0.93,4],
    ['Forwarding','CTO Lahore No. 7082/CTO/Acctt dated 04-05-2026','Application',0.96,2],
    ['E-stamp affidavit','PB-LHR-50661BB59AF39C23, dated 22-04-2026; verified on the Punjab e-Stamp portal','E-stamp · portal',0.99,6],
    ['SAP pay slip, December 2023','GPF balance Rs 445,013; earlier advance Rs 390,000, repaid Rs 169,000, balance Rs 221,000','SAP pay slip',0.97,7],
    ['SAP posting','Permanent advance Rs 451,065 in 2023-24 (the final payment)','SAP re-calculation report',0.96,9],
    ['Section working on Form 06','451,065 less Zakat 11,276, plus 16,900 interest: net Rs 456,689','Form 06 (office hand)',0.88,1],
    ['Thumb impressions','Beside the subscriber’s signatures on Form 06 and the affidavit; they accompany signatures, so R7 does not arise','Form 06 · affidavit',0.95,1]
  ],
  docs:{
    covering:{ present:true, page:2, author:'the Chief Traffic Officer, Lahore', nature:'Forwarding No. 7082/CTO/Acctt dated 04-05-2026 on the application' },
    gpf10:{ present:true, page:2, accountNo:'90000834 (personnel no.)', missing:[], note:'Item 2(i) reads "Rs nil" while the December 2023 SAP pay slip shows a subscription of Rs 3,900; not a B2-i ground.' },
    notification:{ present:true, page:4, label:'Punishment order, dismissal from service', no:'1823-33/PA-STO/S', date:'30-12-2023',
      note:'Signed by Signatory C. Test, Senior Traffic Officer, Saddar Division, Lahore; attested by the Accountant, City Traffic Police.' },
    cnics:[ { page:6, whose:'subscriber', type:'smart', number:'00001-0000105-9', name:'Subscriber C. Test', expiry:'07-08-2033', attested:false,
      crop:'fp-dismissal_p006_cnic_front_copy.png', sigCrop:'fp-dismissal_p006_cnic_holder_signature_area.png' } ],
    changeForm:{ present:true, label:'FORM PAY 06', page:1, personalNo:'90000834', name:'Subscriber C. Test', cnic:'00001-0000105-9', sigKind:'signature', ddoSigned:true,
      ddoStamp:'Chief Traffic Officer, Lahore', ddoCrop:'fp-dismissal_p001_ddo_signature_cto_stamp.png', oldGpfNo:'', oldGpfNoState:'carrying only the AG token T.NO 983415',
      note:'The handwriting across the form (both computations, "31-12-2023") is the AG office’s own working, not a department entry.' },
    serviceBook:{ present:false, reportedAttached:'The CTO’s forwarding note says the original service roll is attached.' }
  },
  qr:[
    { id:'estamp', page:6, doc:'e-stamp affidavit', symbology:'QR code', decoded:true, route:'online', host:'es.punjab-zameen.gov.pk', crop:'fp-dismissal_p006_estamp_qr.png',
      payload:'Url: https://es.punjab-zameen.gov.pk/eStampCitizenPortal/GeneratePDF/Stamp_Receipt?id=PB-LHR-50661BB59AF39C23',
      compare:[ {field:'stamp id', qrVal:'PB-LHR-50661BB59AF39C23', docVal:'PB-LHR-50661BB59AF39C23', docLabel:'portal record', match:true} ],
      portal:{ ok:true, checkedOn:'15-09-2026', result:'e-stamp PB-LHR-50661BB59AF39C23 found and valid, Rs 100, "certificate or other document", issued 22-04-2026 and usable to 29-04-2026, applicant Subscriber C. Test, CNIC 00001-0000105-9, father Father C. Test. The affidavit is dated 22-04-2026, within validity, and name, CNIC and father name agree with the case.' } },
    { id:'order-qr', page:4, doc:'punishment order', symbology:'QR code', decoded:false, why:'modules degraded by photocopying', crop:'fp-dismissal_p004_qr_punishment_order.png',
      remedy:'Scan the QR code on the original order, or obtain the department’s verification, and upload it.' },
    { id:'cnic-back', page:6, doc:'smart CNIC', symbology:'QR code', notSupplied:'Only the front of the smart CNIC is copied, on the e-stamp affidavit; the back, which carries the QR code, is not in the case.', remedy:'Upload a copy of the back of the CNIC.' }
  ],
  signatures:[
    { id:'form06-ddo', page:1, doc:'FORM PAY 06', role:'ddo', roleLabel:'DDO signature', authority:'Chief Traffic Officer, Lahore',
      signedBy:'Chief Traffic Officer, Lahore', forMarker:false, crop:'fp-dismissal_p001_ddo_signature_cto_stamp.png' }
  ],
  claim:{ amount:451065, basis:'the balance on Form 06 before the section’s zakat and interest working', residualNote:'It is the 2023-24 interest, which the interest check covers.' },
  custom:['DIS-APPEAL','DIS-CREDITS','DIS-INTEREST']
});

CUSTOM_CHECKS['DIS-APPEAL'] = { id:'DIS-APPEAL', group:'checklist', ref:'Rule 1.13(6) Explanation 1', code:'OFF_LIST', title:'No appeal pending against the dismissal',
  applies: F => true,
  run: F => {
    const v = verified(F, 'DIS-APPEAL');
    if (v) return verifiedResult(v, 'No appeal or review pending against the dismissal.', 'An appeal or review is pending; the balance is held until final orders.');
    return { status:'conf', finding:'Under Rule 1.13(6) Explanation 1, a dismissed subscriber who has appealed is not paid until final orders. The affidavit of 22-04-2026 says he does not wish to rejoin and has deposited his other dues, but does not say expressly that no appeal is pending.',
      remedy:'Decide whether the affidavit is enough, or obtain a department certificate that no appeal or review is pending.', cure:{ kind:'verify', vid:'DIS-APPEAL' } };
  }};

CUSTOM_CHECKS['DIS-CREDITS'] = { id:'DIS-CREDITS', group:'balance', ref:'B2-vi · B2-ii', code:'B2-vi', title:'Possible missing credits in 2013-14',
  applies: F => !!(F.sap && F.sap.recalc),
  run: F => {
    const v = verified(F, 'DIS-CREDITS');
    if (v) return verifiedResult(v, 'The 2013-14 shortfall is explained (leave without pay, suspension or absence).', 'Missing credits confirmed; to be processed first.');
    return { status:'conf', finding:'The 2013-14 subscription is Rs 6,860, about five months at Rs 1,372, against Rs 16,464 (twelve months) in the years either side: about seven months (Rs 9,604) not credited, unless he was on leave without pay or suspended. 2016-17 does not split into whole months, and 2023-24 carries an unexplained adjustment of Rs 6,052.',
      remedy:'Check the Service Book for leave without pay or suspension in 2013-14. If deductions were made but not credited, treat as a missing-credit claim (R14).', evidence:[ev(9,'Re-calculation report')], cure:{ kind:'verify', vid:'DIS-CREDITS' } };
  }};

CUSTOM_CHECKS['DIS-INTEREST'] = { id:'DIS-INTEREST', group:'balance', ref:'R11 · Rule 1.13(4)', code:'R11', title:'Interest in the section’s working against SAP',
  applies: F => !!(F.sap && F.sap.recalc),
  run: F => {
    const v = verified(F, 'DIS-INTEREST');
    if (v) return verifiedResult(v, 'Interest reconciled and one clean computation recorded.', 'Interest not reconciled.');
    return { status:'conf', finding:'The section’s working on Form 06 adds interest of Rs 16,900; SAP credits Rs 17,968 for 2023-24, a difference of Rs 1,068. The 2024-25 row shows interest of Rs 2,239 not carried to the closing balance. Under Rule 1.13(4) interest stops six months after the balance became payable when the claim is late. This is the section’s own working, not a department defect.',
      remedy:'Reconcile interest, explain the Rs 6,052 adjustment and record one clean, initialled computation.', evidence:[ev(1,'Section working','fp-dismissal_p001_office_computation_sheet.png')], cure:{ kind:'verify', vid:'DIS-INTEREST' } };
  }};
