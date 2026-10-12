/* Balance Transfer: Subscriber H. Test, Director Public Relations Faisalabad */
defCase('balance-transfer', {
  label:'Balance Transfer', kind:'balance_transfer', family:'BALANCE_TRANSFER',
  sub:'Transfer of GP Fund balances, Lahore postings to DAO Faisalabad',
  subject:'Subscriber H. Test, Director', dept:'Office of the Director Public Relations, Faisalabad',
  personnelNo:'90000847', pages:1, diary:'14580 / 243780 / 988477, 03-08-2026', gazetted:'unknown',
  note:'Subscriber H. Test, Director PR Faisalabad. One-page proforma. The DAO has confirmed P# 90000847 as the GP Fund account; old account and last deduction to come from SAP.',
  persNos:[{doc:'Proforma column 4',page:1,value:'90000847'},{doc:'Proforma column 5',page:1,value:'90000847'},{doc:'DAO Faisalabad endorsement',page:1,value:'90000847'}],
  record:[
    ['Subscriber','Subscriber H. Test s/o Father H. Test, Director','Proforma columns 1 to 3',0.97,1],
    ['Office','Office of the Director Public Relations, Faisalabad','Proforma header',0.97,1],
    ['Old A/c no. (column 4)','"Personal No:- 90000847", the personnel number','Proforma',0.99,1],
    ['New A/c no. in DAO (column 5)','"Personal No:- 90000847", confirmed by DAO Faisalabad','Proforma · DAO endorsement',0.98,1],
    ['Last deduction (column 6)','Blank','Proforma',0.99,1],
    ['Column 7','Used for the posting periods; no advance figure or nil','Proforma',0.95,1],
    ['Posting periods','Lahore 24-04-1999 to 03-2009; 03-2011 to 03-2013; 10-2018 to 08-2019; 03-2021 to 03-2025','Proforma column 7',0.93,1],
    ['DAO endorsement','No. DAO/FSD/HM/212 dated 13-05-2026, forwarded to AG Punjab, "GP Fund A/C No: P# 90000847 Is Hereby Confirmed"','Proforma',0.92,1],
    ['DDO signature','Present; no office stamp, name or date','Proforma',0.95,1]
  ],
  docs:{
    covering:{ present:true, page:1, author:'the Director Public Relations Faisalabad and the DAO Faisalabad', nature:'Handwritten forwarding on the proforma and DAO endorsement', crop:'balance-transfer_p001_hod_forwarding_note.png' },
    proforma:{ page:1, name:'Subscriber H. Test', father:'Father H. Test', designation:'Director', oldAc:'Personal No:- 90000847', newAc:'Personal No:- 90000847',
      daoConfirmed:'The GP Fund A/C No: P# 90000847 Is Hereby Confirmed', lastDeduction:'',
      periods:'Lahore 24-04-1999 to March 2009, March 2011 to March 2013, October 2018 to August 2019, March 2021 to March 2025',
      crop:'balance-transfer_p001_particulars_name_father_designation.png', periodsCrop:'balance-transfer_p001_col7_period_of_posting.png', daoCrop:'balance-transfer_p001_dao_endorsement_stamp_signature.png' }
  },
  signatures:[
    { id:'ddo', page:1, doc:'proforma', role:'ddo', roleLabel:'DDO signature', authority:'Director Public Relations, Faisalabad',
      signedBy:'unidentified signatory (no stamp, name or date)', forMarker:false, crop:'balance-transfer_p001_ddo_signature_no_stamp.png', bbox:[2036,1347,2635,1602] },
    { id:'dao', page:1, doc:'DAO endorsement', role:'certifying', roleLabel:'DAO confirmation', authority:'District Accounts Office, Faisalabad',
      signedBy:'District Accounts Officer, Faisalabad', forMarker:false, crop:'balance-transfer_p001_dao_endorsement_stamp_signature.png', bbox:[1527,1168,2215,1677] }
  ]
});
