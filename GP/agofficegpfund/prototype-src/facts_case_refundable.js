/* Refundable Advance: Constable Barkat Ali, Punjab Police */
defCase('refundable', {
  label:'Refundable Advance', kind:'refundable', family:'ADVANCE',
  sub:'Refundable advance for house repair, Rule 1.14(1)(a)(iv)',
  subject:'Barkat Ali, Constable (BS-07)', dept:'Punjab Police, Office of the DIG Operations, Lahore',
  personnelNo:'90000227', pages:6, diary:'214253 / 988890, 10-08-2026', gazetted:'non-gazetted',
  note:'Constable Barkat Ali. Rs 58,000 for house repair, signed for the DIG Operations by SP Headquarters. Pay slip and re-calculation report already in the case.',
  nameNote:'The English spelling on the card is "Barkit"; the Urdu name is the same.',
  nameVariants:['Barkit Ali'],
  persNos:[{doc:'Sanction order',page:1,value:'90000227'},{doc:'FORM PAY 05',page:4,value:'90000227'},{doc:'SAP pay slip, August 2026',page:5,value:'90000227'},{doc:'GPF Final Re-calculation Report',page:6,value:'90000227'}],
  record:[
    ['Subscriber','Barkat Ali s/o Liaqat Ali, Constable No. 7156','Sanction · CNIC · SAP pay slip',0.97,1],
    ['Personnel no.','90000227','Sanction · Form 05 · pay slip · report',0.99,4],
    ['CNIC','00001-0000101-3 (smart card, valid to 05-11-2030)','CNIC front and back · QR · pay slip',0.98,2],
    ['Sanction','No. 1463/GPF-Ops dated 07-08-2026, Rs 58,000','Sanction order',0.98,1],
    ['Rule quoted','1.14(1)(a)(iv)(d)(i): house repair, limit 24 months’ pay or 80% of balance','Sanction order',0.95,1],
    ['Recovery','29 instalments of Rs 2,000','Sanction · Form 05',0.96,1],
    ['Basic pay','Rs 19,040 on the sanction; Rs 22,890 on the August 2026 SAP pay slip','Sanction · pay slip',0.92,5],
    ['GPF balance on pay slip','Rs 19,194, after this advance was posted','SAP pay slip, August 2026',0.97,5],
    ['Balance before the advance','Rs 79,899 at 01-07-2026','SAP re-calculation report',0.98,6],
    ['Advance posted in SAP','Rs 58,000 in 2026-27, Rs 2,000 recovered, balance Rs 56,000','Report · pay slip',0.97,6],
    ['Payroll unit in SAP','LO0056 DIG Special Protection Unit (sanction and Form 05: DIG Operations, DDO LO5313)','Pay slip · Form 05',0.90,5]
  ],
  docs:{
    sanction:{ present:true, page:1, dept:'Punjab Police', printedAuthority:'Deputy Inspector General of Police, Operations, Lahore',
      orderNo:'1463/GPF-Ops', date:'07-08-2026', rule:'Rule 1.14(1)(a)(iv)(d)(i) of the Punjab GP Fund Rules 1978', reason:'Repair of house',
      amount:58000, balanceStated:null, basicPay:19040, limitClause:'1.14(1)(d)(i)', qrId:null, crop:'refundable_p001_sanction_order_text.png' },
    changeForm:{ present:true, label:'FORM PAY 05', page:4, personalNo:'90000227', name:'Barkat Ali', cnic:'',
      sigKind:'signature', sigCrop:'refundable_p004_form05_employee_specimen_signatures.png',
      ddoSigned:true, ddoStamp:'SP Headquarters for DIG Operations, Lahore', ddoCrop:'refundable_p004_form05_ddo_signatory_stamp.png' },
    cnics:[ { page:2, whose:'subscriber', type:'smart', number:'00001-0000101-3', name:'Barkit Ali', expiry:'05-11-2030', attested:false,
      sigCrop:'refundable_p002_cnic_holder_signature.png', crop:'refundable_p002_cnic_front_details.png' } ]
  },
  qr:[ { id:'cnic-back', page:3, doc:'smart CNIC back', symbology:'QR code', decoded:true, payload:'10826129086900001000010131', crop:'refundable_p003_cnic_back_qr.png',
    compare:[ {field:'CNIC number', qrVal:'00001-0000101-3', docVal:'00001-0000101-3', docLabel:'card', match:true},
              {field:'card number', qrVal:'108261290869', docVal:'108261290869', docLabel:'number printed under the code', match:true} ] } ],
  signatures:[
    { id:'sanction', page:1, doc:'sanction order', role:'sanctioning', roleLabel:'Sanctioning signature', authority:'Deputy Inspector General of Police, Operations, Lahore',
      signedBy:'SP Headquarters', forMarker:true, crop:'refundable_p001_sanction_signatory_for_dig.png', bbox:[1395,2165,2225,2480] },
    { id:'form05-ddo', page:4, doc:'FORM PAY 05', role:'ddo', roleLabel:'DDO signature', authority:'Deputy Inspector General of Police, Operations, Lahore',
      signedBy:'SP Headquarters', forMarker:true, crop:'refundable_p004_form05_ddo_signatory_stamp.png' }
  ],
  custom:['REF-PAYROLL-UNIT']
});

CUSTOM_CHECKS['REF-PAYROLL-UNIT'] = { id:'REF-PAYROLL-UNIT', group:'identity', ref:'R4 · B1-ii (outside the list, justified)', code:'OFF_LIST',
  title:'Sanctioning office and SAP payroll unit',
  applies: F => !!(F.sap && F.sap.payslip),
  run: F => {
    const v = verified(F, 'REF-PAYROLL-UNIT');
    if (v) return verifiedResult(v, 'Subscriber’s unit at the sanction date confirmed, and DIG Operations Lahore was competent.', 'The sanctioning office was not the competent authority for the unit on whose payroll the subscriber is borne.');
    return { status:'conf', finding:'The sanction and Form 05 place the subscriber under the DIG Operations Lahore (DDO LO5313, Constable No. 7156). The SAP pay slip for August 2026 places him under LO0056 DIG Special Protection Unit (Buckle 6033/SC). Identity is not in doubt; the competence of the sanctioning authority depends on which establishment he is borne on.',
      remedy:'Confirm the subscriber’s unit and DDO at the sanction date. Justification for raising: B1-ii requires sanction by the authority competent under delegation.',
      evidence:[ev(5,'SAP pay slip header','refundable_p005_payslip_left_header_ddo.png'), ev(4,'Form 05 DDO code','refundable_p004_form05_ddo_personal_no_name.png')],
      cure:{ kind:'verify', vid:'REF-PAYROLL-UNIT' } };
  }};
