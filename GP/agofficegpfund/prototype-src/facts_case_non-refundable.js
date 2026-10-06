/* Non-Refundable Advance: Mrs Rubina Tariq, PST, School Education Department */
defCase('non-refundable', {
  label:'Non-Refundable Advance', kind:'nonrefundable', family:'ADVANCE',
  sub:'Non-refundable advance at age 50 or over, Rule 1.16',
  subject:'Rubina Tariq, PST (BS-14)', dept:'School Education Department, GGHS R.A. Bazar, Lahore Cantt',
  personnelNo:'90000216', pages:7, diary:'987752 / 212877, 23-07-2026', gazetted:'non-gazetted',
  note:'Mrs Rubina Tariq, PST. Rs 490,955 under Rule 1.16. QR-coded sanction and smart CNIC both scan and agree. CNIC digits transposed on Form 6-B.',
  persNos:[{doc:'Sanction order',page:1,value:'90000216'},{doc:'FORM PAY 06',page:4,value:'90000216'},{doc:'SAP pay slip, August 2026',page:5,value:'90000216'},{doc:'GPF Final Re-calculation Report',page:7,value:'90000216'}],
  record:[
    ['Subscriber','Mrs Rubina Tariq w/o Tariq Ur Rehman, Primary School Teacher','Sanction · CNIC · SAP pay slip',0.97,1],
    ['Personnel no.','90000216','Sanction · Form 06 · pay slip · report',0.99,4],
    ['CNIC','00001-0000104-4 (smart card); Form 06 writes 00010-0000104-4','Card · QR codes · pay slip · Form 06',0.97,2],
    ['Date of birth, age at sanction','05-11-1974; 51 years 8 months on 14-07-2026','Sanction · CNIC · pay slip',0.98,1],
    ['Sanction','No. 113909/LHR/2026 dated 14-07-2026, Rs 490,955','Sanction order',0.98,1],
    ['Rule quoted','1.16, with FD notification FD-SR-1-2-1/2000 of 12-12-2002','Sanction order',0.96,1],
    ['Balance stated on sanction','Rs 613,694 (Rs 490,955 is exactly 80% of it)','Sanction order',0.95,1],
    ['GPF balance on pay slip','Rs 260,522, after this advance was posted','SAP pay slip, August 2026',0.98,5],
    ['Balance before the advance','Rs 743,677 at 30-06-2026','SAP re-calculation report',0.98,7],
    ['Office annotation on Form 06','490,955 less 12,274 (2.5%), net Rs 478,681','Form 06 foot',0.90,4]
  ],
  docs:{
    sanction:{ present:true, page:1, dept:'School Education Department', printedAuthority:'Chief Executive Officer (DEA) Lahore',
      orderNo:'113909/LHR/2026', date:'14-07-2026', rule:'Rule 1.16 of the Punjab GP Fund Rules 1978, with FD notification FD-SR-1-2-1/2000 of 12-12-2002', reason:'Age over 45 (born 05-11-1974)',
      amount:490955, balanceStated:613694, limitClause:'1.16', ageAtSanction:{y:51, m:8}, qrId:'sanction', crop:'non-refundable_p001_sanction_signatory_stamp.png' },
    changeForm:{ present:true, label:'FORM PAY 06', page:4, personalNo:'90000216', name:'Mrs. Rubina Tariq', cnic:'00010-0000104-4', cnicCrop:'non-refundable_p004_personal_no_and_cnic.png',
      sigKind:'signature', sigCrop:'non-refundable_p004_employee_specimen_signatures.png',
      ddoSigned:true, ddoStamp:'Senior Headmistress, Govt. Girls High School R.A. Bazar Lahore', ddoCrop:'non-refundable_p004_ddo_signature_stamp.png' },
    cnics:[ { page:2, whose:'subscriber', type:'smart', number:'00001-0000104-4', name:'Rubina Tariq', expiry:'08-08-2032', attested:true, attestedBy:'Senior Headmistress, GGHS R.A. Bazar',
      sigCrop:'non-refundable_p002_cnic_holder_signature.png', crop:'non-refundable_p002_cnic_number_issue.png' } ]
  },
  qr:[
    { id:'sanction', page:1, doc:'sanction order', symbology:'QR code', decoded:true, crop:'non-refundable_p001_sanction_qr.png',
      payload:'Rubina Tariq CNIC# 0000100001044 posted as a PST (BS-14), posted at GGHS  R.A. BAZAR, Tehsil CANTT, District LAHORE',
      compare:[ {field:'name', qrVal:'Rubina Tariq', docVal:'Mrs. Rubina Tariq', docLabel:'sanction', match:true},
                {field:'CNIC', qrVal:'0000100001044', docVal:'0000100001044', docLabel:'sanction', match:true},
                {field:'post', qrVal:'PST (BS-14)', docVal:'PST (BS-14)', docLabel:'sanction', match:true},
                {field:'school', qrVal:'GGHS R.A. Bazar, Lahore', docVal:'GGHS R.A. Bazar', docLabel:'sanction', match:true} ] },
    { id:'cnic-back', page:3, doc:'smart CNIC back', symbology:'QR code', decoded:true, payload:'50529399118600001000010441', crop:'non-refundable_p003_cnic_back_qr.png',
      compare:[ {field:'CNIC number', qrVal:'00001-0000104-4', docVal:'00001-0000104-4', docLabel:'card', match:true},
                {field:'card number', qrVal:'505293991186', docVal:'505293991186', docLabel:'number printed under the code', match:true} ] }
  ],
  signatures:[
    { id:'sanction', page:1, doc:'sanction order', role:'sanctioning', roleLabel:'Sanctioning signature', authority:'Chief Executive Officer, District Education Authority Lahore',
      signedBy:'Assistant Director (Admin)', forMarker:true, crop:'non-refundable_p001_sanction_signatory_stamp.png', bbox:[1660,1950,2330,2650] },
    { id:'form06-ddo', page:4, doc:'FORM PAY 06', role:'ddo', roleLabel:'DDO signature', authority:'Senior Headmistress, Govt. Girls High School R.A. Bazar Lahore',
      signedBy:'Senior Headmistress', forMarker:false, crop:'non-refundable_p004_ddo_signature_stamp.png' }
  ],
  custom:['NR-OFFICE-ANNOT']
});

CUSTOM_CHECKS['NR-OFFICE-ANNOT'] = { id:'NR-OFFICE-ANNOT', group:'balance', ref:'Section working', code:'OFF_LIST', title:'Office annotation of Rs 12,274 on Form 06',
  applies: F => true,
  run: F => {
    const v = verified(F, 'NR-OFFICE-ANNOT');
    if (v) return verifiedResult(v, 'Basis of the Rs 12,274 deduction confirmed in the section’s records.', 'Basis of the Rs 12,274 deduction not confirmed.');
    return { status:'conf', finding:'The accounts office wrote "490955/- 12274/-" and "Rs=478681/-" on Form 06. Rs 12,274 is 2.5% of Rs 490,955 and the "Other" box reads 2½, so this looks like the office’s own 2.5% deduction (probably Zakat). The SAP report posts the full Rs 490,955 with no adjustment. Not a department defect.',
      remedy:'Section to confirm the basis of the deduction.', evidence:[ev(4,'Office annotation','non-refundable_p004_office_annotations_12274.png')], cure:{ kind:'verify', vid:'NR-OFFICE-ANNOT' } };
  }};
