/* Residual Payment: Mst Shabnam, Head Nurse (BS-17), Punjab Institute of Mental Health */
defCase('residual', {
  label:'Residual Payment', kind:'residual', family:'FINAL_PAYMENT',
  sub:'Residual GP Fund payment after final payment drawn',
  subject:'Shabnam, Head Nurse (BS-17)', dept:'Punjab Institute of Mental Health, Lahore',
  personnelNo:'90000687', pages:6, diary:'206984 / 982288', gazetted:'gazetted',
  note:'Mst Shabnam, retired 07-11-2024. Rs 31,408 residual. The SAP report now in the case shows a debit balance and a possible double posting. No Form 10.',
  persNos:[{doc:'FORM PAY 06',page:1,value:'90000687'},{doc:'Application',page:2,value:'90000687'},{doc:'SAP payroll register, October 2024',page:5,value:'90000687'},{doc:'GPF Final Re-calculation Report',page:6,value:'90000687'}],
  record:[
    ['Subscriber','Mst Shabnam w/o Abid Javed, Head Nurse (BS-17), gazetted','Form 06 · CNIC · SAP register',0.97,1],
    ['Personnel no.','90000687','Form 06 · application · SAP',0.99,1],
    ['CNIC','00001-0000106-4 (smart card, lifetime); front only','Form 06 · CNIC · notification',0.97,4],
    ['Retirement','07-11-2024 on superannuation, Notification SO(NC)10-1/15 of 03-09-2024','Notification',0.97,3],
    ['Claimed','Rs 31,408 residual, handwritten on Form 06','Form 06',0.95,1],
    ['GPF balance, October 2024 register','Rs 340,330, before the final payment','SAP payroll register',0.97,5],
    ['Report, 2024-25 row','Adjustment 31,408; permanent advance 712,068; interest 20,807; closing 340,330 debit','SAP re-calculation report',0.93,6],
    ['Form 10','Not in the case','',0.99,null],
    ['Zakat','"No Zakat deducted (Christian)" written on Form 06','Form 06',0.90,1]
  ],
  docs:{
    covering:{ present:true, page:2, author:'the subscriber', nature:'Subscriber’s application to the AG for residual payment' },
    gpf10:{ present:false },
    notification:{ present:true, page:3, label:'Retirement notification', no:'SO(NC)10-1/15', date:'03-09-2024', note:'Retirement w.e.f. 07-11-2024 on superannuation. Attested by the Office Superintendent, PIMH.' },
    cnics:[ { page:4, whose:'subscriber', type:'smart', number:'00001-0000106-4', name:'Shabnam', expiry:'lifetime', attested:true, attestedBy:'Office Superintendent, PIMH',
      sigCrop:'residual_p004_cnic_holder_signature.png', crop:'residual_p004_cnic_front_only.png' } ],
    changeForm:{ present:true, label:'FORM PAY 06', page:1, personalNo:'90000687', name:'Shabnam', cnic:'00001-0000106-4',
      sigKind:'signature', sigCrop:'residual_p001_employee_specimen_signatures.png', ddoSigned:true, ddoStamp:'Executive Director, Punjab Institute of Mental Health', ddoCrop:'residual_p001_ddo_signature_stamp.png',
      oldGpfNo:'', oldGpfNoState:'blank', note:'The printed form number is under a blank pink note; the heading "Permanent Loan Details" identifies Form 06.' }
  },
  qr:[
    { id:'notif-barcode', page:3, doc:'retirement notification', symbology:'1-D barcode', decoded:false, why:'bars merged in the photocopy', crop:'residual_p003_barcode.png',
      readable:'"*0000100001064R 2884*", whose CNIC part agrees with the notification', remedy:'Upload a clean copy of the notification, or confirm it with the SHC&ME Department.' },
    { id:'cnic-back', page:4, doc:'smart CNIC', symbology:'QR code', notSupplied:'Only the front of the smart CNIC is copied; the back, which carries the QR code, is not in the case.', remedy:'Upload a copy of the back of the CNIC.' }
  ],
  signatures:[
    { id:'form06-ddo', page:1, doc:'FORM PAY 06', role:'ddo', roleLabel:'DDO signature', authority:'Executive Director, Punjab Institute of Mental Health, Lahore',
      signedBy:'Executive Director, Punjab Institute of Mental Health', forMarker:false, crop:'residual_p001_ddo_signature_stamp.png', bbox:[250,2600,850,3150] }
  ],
  custom:['RES-RECON']
});

CUSTOM_CHECKS['RES-RECON'] = { id:'RES-RECON', group:'balance', ref:'B2-vi · R11', code:'B2-vi', title:'Residual reconciles with the SAP re-calculation report',
  applies: F => true,
  run: F => {
    const rc = F.sap && F.sap.recalc;
    if (!rc || !rc.rows || !rc.rows.length) return { status:'sap', finding:'Rs 31,408 residual claimed. The SAP re-calculation report is needed to reconcile it.', cure:{ kind:'sap' } };
    const last = rc.rows[rc.rows.length-1];
    const v = verified(F, 'RES-RECON');
    if (v) return verifiedResult(v, 'Residual reconciled in SAP.', 'Residual could not be reconciled in SAP.');
    if (F.sap.source === 'upload' && last.closing > 0)
      return Math.abs(last.closing - 31408) <= 1 ? { status:'ok', finding:'The uploaded report closes at Rs ' + fmt(last.closing) + ' in credit, equal to the residual claimed.' }
                                                 : { status:'hard', finding:'The uploaded report closes at Rs ' + fmt(last.closing) + '; Rs 31,408 is claimed.', remedy:'Reconcile the claim with SAP.' };
    return { status:'conf', calc:{ claim:31408, expected:last.closing, basis:'closing balance for ' + last.start + ' to ' + last.end },
      finding:'The report does not show the residual at credit. Rs 31,408 appears as the 2024-25 adjustment, but the 2024-25 closing is printed Rs 340,330 debit. Every earlier row follows opening + subscription + adjustment - advances + recoveries + interest; this row only does if the interest of Rs 20,807 is left out. The permanent advance of Rs 712,068 equals exactly 2 x 340,330 + 31,408, which fits a double posting of the final payment. Paying on this report risks paying against a debit, or paying twice.',
      remedy:'Before payment, the section pulls the SAP ledger postings for 2024-25, corrects any double posting, and uploads the corrected report on the SAP extracts step.',
      evidence:[ev(6,'Report, last rows','residual_p006_recalc_last_rows.png')], cure:{ kind:'verify', vid:'RES-RECON' } };
  }};
