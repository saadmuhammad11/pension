/* Missing Credits: Dr Subscriber D. Test, AP-II, on deputation at Government Engineering Academy Punjab */
defCase('missing-credits', {
  label:'Missing Credits, Challans', kind:'missing_credits', family:'MISSING_CREDITS',
  sub:'Missing credits for a deputation period, paid by challan',
  subject:'Dr Subscriber D. Test, AP-II (on deputation)', dept:'Government Engineering Academy Punjab, Niaz Beg, Lahore',
  personnelNo:'90000043', pages:7, diary:'Fd-2/K-851, 13-08-2026', gazetted:'unknown', gazettedEvidence:'designation "AP-II" and "Officers on Deputation" only',
  note:'Dr Subscriber D. Test, deputation 07-2025 to 04-2026. Seven challans scheduled and Treasury-verified for Rs 79,600; six attached. No SAP extracts in the case.',
  persNos:[{doc:'Covering letter schedule',page:1,value:'90000043'},{doc:'Challans Sr. 1 to 7 (six attached)',page:2,value:'90000043'}],
  record:[
    ['Subscriber','Dr Subscriber D. Test, AP-II (schedule spells "Subscribar D. Test, AP")','Schedule · challans',0.95,1],
    ['Personnel no.','90000043','Schedule · all six challans',0.98,2],
    ['Deputation period','01-07-2025 to 30-04-2026, 10 months at Rs 7,960','Covering letter',0.97,1],
    ['Covering letter','Administrative Officer GEA to Treasury Officer Lahore, 21-07-2026, "Verification of challans"','Covering letter',0.97,1],
    ['Treasury verification','"Verified Rs 79600/-, under head G06103", Deputy Treasury Officer Lahore','Covering letter endorsement',0.95,1],
    ['Challans scheduled','7, total Rs 79,600','Schedule',0.99,1],
    ['Challans attached','6 (Sr. 1, 2, 3, 5, 6, 7), total Rs 71,640','Pages 2 to 7',0.99,2],
    ['Missing challan','Sr. 4: November 2025, Rs 7,960, cheque 8073770058 of 17-12-2025, credited 02-01-2026','Schedule',0.96,1],
    ['Bank stamps','Present on all six; Sr. 1 too faint to read','Pages 2 to 7',0.90,2],
    ['BPS and gazetted status','Not stated anywhere in the case','',0.99,null]
  ],
  docs:{
    covering:{ present:true, page:1, author:'the Administrative Officer, Government Engineering Academy Punjab', nature:'Request to the Treasury Officer to verify the challans', crop:'missing-credits_p001_covering_letter_signatory_admin_officer.png' },
    challans:{
      period:'deputation period 01-07-2025 to 30-04-2026 (10 months at Rs 7,960)',
      toVerified:true, toPage:1, toCrop:'missing-credits_p001_treasury_verification_endorsement.png',
      schedulePage:1, scheduleCrop:'missing-credits_p001_schedule_7_challans.png',
      schedule:{ count:7, total:79600, items:[
        {sr:1, period:'July 2025', amount:7960, cheque:'8073758389'}, {sr:2, period:'August 2025', amount:7960, cheque:'8073758395'},
        {sr:3, period:'September to October 2025', amount:15920, cheque:'8073770051'}, {sr:4, period:'November 2025', amount:7960, cheque:'8073770058'},
        {sr:5, period:'December 2025 to January 2026', amount:15920, cheque:'8073770064'}, {sr:6, period:'February to March 2026', amount:15920, cheque:'8073770076'},
        {sr:7, period:'April 2026', amount:7960, cheque:'8073770086'} ] },
      copies:[
        {page:2, sr:1, amount:7960, bankStamp:true, stampFaint:true, crop:'missing-credits_p002_bank_stamp.png',
         stampNote:'Only "...BANK OF PAKISTAN" and "...BANKING" can be made out. The Treasury "Challan verified Rs 7960/-" mark dated 22-08-2025 agrees with the schedule.'},
        {page:3, sr:2, amount:7960, bankStamp:true, stampText:'NBP Islamic Banking Johar Town, 09 OCT 2025', crop:'missing-credits_p003_bank_stamp.png'},
        {page:4, sr:3, amount:15920, bankStamp:true, stampText:'NBP Islamic Banking Johar Town, 25 NOV 2025', crop:'missing-credits_p004_bank_stamp.png'},
        {page:5, sr:5, amount:15920, bankStamp:true, stampText:'NBP Aitemaad Johar Town, clearing, 16 FEB 2026', crop:'missing-credits_p005_bank_stamp.png'},
        {page:6, sr:6, amount:15920, bankStamp:true, stampText:'NBP Aitemaad Johar Town, clearing, 29 APR 2026', crop:'missing-credits_p006_bank_stamp_clearing.png'},
        {page:7, sr:7, amount:7960, bankStamp:true, stampText:'NBP Aitemaad Johar Town, 15 JUL 2026', crop:'missing-credits_p007_bank_stamp.png'} ]
    }
  },
  signatures:[
    { id:'treasury', page:1, doc:'Treasury verification on the covering letter', role:'certifying', roleLabel:'Treasury verification', authority:'Treasury Office, Lahore',
      signedBy:'Deputy Treasury Officer, Lahore', forMarker:false, crop:'missing-credits_p001_treasury_verification_endorsement.png', bbox:[420,2280,1480,2920] }
  ],
  custom:['MC-NAME']
});

CUSTOM_CHECKS['MC-NAME'] = { id:'MC-NAME', group:'identity', ref:'R1', title:'Name spelling against SAP',
  applies: F => true,
  run: F => {
    const p = F.sap && F.sap.payslip;
    if (!p || !p.name) return { status:'sap', finding:'The schedule spells the name "Dr. Subscribar D. Test, AP"; all six challans spell it "Dr. Subscriber D. Test, AP-II". The personnel number is the same throughout. Match against the SAP master name.', cure:{ kind:'sap' } };
    const ok = /subscrib[ae]r\s*d\.?\s*test/i.test(p.name);
    return ok ? { status:'ok', finding:'SAP names personnel no. ' + p.persNo + ' as ' + p.name + '. Both spellings refer to this subscriber.' }
              : { status:'hard', finding:'SAP names personnel no. ' + p.persNo + ' as ' + p.name + ', not Subscriber D. Test.', remedy:'Department to confirm the identity of the subscriber.' };
  }};
