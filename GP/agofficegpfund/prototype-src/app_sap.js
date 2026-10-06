/* ═══════════════════════════════════════════════════════════════════════
   SCREEN 3: SAP extracts, straight after initial processing
   ═══════════════════════════════════════════════════════════════════════ */
function sapPartCard(k, title, part, kind){
  const s = STATE[k], F = s.F;
  let body;
  if (part && F.sap.source === 'case')
    body = vd('ok','Found in the case')+' <span class="src">page</span> '+pglink(k, part.page, title)+'<div class="src" style="margin-top:4px">Marked on the checklist. No upload needed.</div>';
  else if (part)
    body = vd('ok','Uploaded from SAP')+'<div class="src" style="margin-top:4px">'+esc(F.sap.file)+'</div>';
  else
    body = vd('sap','Awaiting SAP extract')+'<div class="src" style="margin-top:4px">Pull from SAP against personnel no. <b class="mono">'+esc(F.personnelNo||'')+'</b>.</div>';
  return '<div class="card" style="margin-bottom:0"><h3>'+title+'</h3>'+body+'</div>';
}

function sapFiguresTable(k){
  const F = STATE[k].F, p = F.sap && F.sap.payslip, rc = F.sap && F.sap.recalc;
  let h = '';
  if (p){
    const rows = [['Personnel no.',p.persNo],['Name',p.name],['Designation',p.designation],['CNIC',p.cnic],['Month',p.month],['BPS',p.bps],
      ['GPF no.',p.gpfNo],['Old GPF no.',p.oldGpfNo],['GPF balance',p.gpfBalance!=null?'Rs '+fmt(p.gpfBalance):''],['GPF subscription',p.gpfSubscription!=null?'Rs '+fmt(p.gpfSubscription):''],
      ['GPF advance instalment',p.loanInstalment!=null?'Rs '+fmt(p.loanInstalment):''],['GPF advance balance',p.loanBalance!=null?'Rs '+fmt(p.loanBalance):''],['OSD post',p.osdPost]]
      .filter(r=>r[1]!==undefined && r[1]!==null && r[1]!=='');
    h += '<h4>Pay slip</h4><table class="compact">'+rows.map(r=>'<tr><td style="width:190px">'+r[0]+'</td><td class="fv mono">'+esc(r[1])+'</td></tr>').join('')+'</table>';
  }
  if (rc && rc.rows && rc.rows.length){
    const rows = rc.rows.slice(-5);
    h += '<h4>GPF Final Re-calculation Report'+(rc.rows.length>5?', last five periods of '+rc.rows.length:'')+'</h4><div class="tscroll"><table class="num compact"><tr>'+
      ['Period','Opening','Subscription','Adjust.','Temp adv.','Rec. temp','Perm. adv.','Interest','Closing'].map((c,i)=>'<th'+(i?' class="n"':'')+'>'+c+'</th>').join('')+'</tr>'+
      rows.map(r=>'<tr><td class="nowrap">'+esc(r.start)+' to '+esc(r.end)+'</td>'+['opening','subscription','adjustments','tempAdvance','recTempAdvance','permanentAdvance','interest','closing']
        .map(c=>'<td class="n mono">'+(r[c]?fmt(r[c]):'0')+'</td>').join('')+'</tr>').join('')+'</table></div>';
  }
  return h;
}

function renderSap(k){
  const s = STATE[k], F = s.F, have = F.sap || {};
  let h = '<h1 class="pagetitle">SAP extracts</h1>'+
    '<p class="pagesub">Straight after initial processing. The pay slip and the GPF Final Re-calculation Report come from SAP. Where the department has already sent them they are marked off; where not, the section pulls them by personnel number and uploads them here.</p>';
  if (s.lastDiff && s.lastReason && /SAP/.test(s.lastReason)) h += diffBanner(k);

  /* personnel numbers found in the case */
  const pn = F.persNos || [];
  h += '<div class="card"><h3>Personnel number</h3><p class="hint">Read from the case documents. This is the key for the SAP lookup.</p>'+
       '<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap"><div class="kv mono" style="font-size:24px">'+esc(F.personnelNo||'not found')+'</div>'+
       (F.personnelNo ? '<button class="abtn" onclick="navigator.clipboard && navigator.clipboard.writeText(\''+esc(F.personnelNo)+'\')">Copy</button>' : '')+'</div>'+
       (pn.length ? '<table class="compact" style="margin-top:10px"><tr><th>Document</th><th>Reads</th><th>Page</th></tr>'+pn.map(x=>'<tr><td>'+esc(x.doc)+'</td><td class="mono">'+esc(x.value)+'</td><td>'+pglink(k,x.page)+'</td></tr>').join('')+'</table>' : '')+
       '</div>';

  h += '<div class="cols" style="margin-bottom:15px">'+sapPartCard(k,'SAP pay slip',have.payslip,'payslip')+sapPartCard(k,'GPF Final Re-calculation Report',have.recalc,'recalc')+'</div>';

  const missing = !(have.payslip && have.recalc);
  if (true){
    h += '<div class="card"><h3>'+(missing ? 'Pull from SAP and upload' : 'Upload a fresh SAP extract')+'</h3>'+
      '<p class="hint">In SAP, open the pay slip and the GPF Final Re-calculation Report for personnel no. <b class="mono">'+esc(F.personnelNo||'')+'</b> and save them. '+
      'A text or spreadsheet export is read directly. A PDF or scan is accepted too; the officer then keys the figures, which in production the reading stage lifts.</p>'+
      '<div class="drop" id="sapdrop"><b>Choose the SAP extract file</b><br>.txt, .csv or .json exports are read directly. PDF and images are accepted.</div>'+
      '<div class="actionbar" style="margin-top:12px">'+
        (F.sapSample ? '<button class="btn ghost small" id="sapsample">Use the extract saved for this prototype</button>' : '')+
        '<button class="btn ghost small" id="saptemplate">Show the extract layout</button>'+
        '<button class="btn ghost small" disabled title="'+esc(SAP_CONNECTOR.note)+'">Fetch from SAP automatically</button>'+
        '<span class="src">SAP connector: '+esc(SAP_CONNECTOR.status)+'. '+esc(SAP_CONNECTOR.note)+'</span>'+
      '</div><div id="sapmsg"></div></div>';
  }
  const figs = sapFiguresTable(k);
  if (figs) h += '<div class="card"><h3>Figures in use</h3><p class="hint">What the rules will use from SAP'+(F.sap && F.sap.source==='case' ? ', as read from the pages in the case.' : '.')+'</p>'+figs+'</div>';

  const L = lists(s.results);
  h += '<div class="notice slate">'+(L.sap.length ? '<b>'+plural(L.sap.length,'check')+' still wait'+(L.sap.length===1?'s':'')+' for SAP data:</b> '+L.sap.map(r=>esc(r.title)).join('; ')+'. You can continue and upload later.'
                                          : '<b>Nothing is waiting for SAP data.</b>')+'</div>';
  h += '<div class="actionbar"><button class="btn" id="toexam">Continue to examination</button></div>';
  $('s3body').innerHTML = h;

  $('toexam').onclick = ()=>{ renderExam(k); go(4); };
  if ($('sapdrop')){
    $('sapdrop').onclick = async ()=>{ const f = await pickFile('.txt,.csv,.json,.pdf,.png,.jpg,.jpeg'); if (f) handleSapFile(k, f); };
    const dz = $('sapdrop');
    dz.ondragover = e=>{ e.preventDefault(); dz.classList.add('over'); };
    dz.ondragleave = ()=> dz.classList.remove('over');
    dz.ondrop = e=>{ e.preventDefault(); dz.classList.remove('over'); if (e.dataTransfer.files[0]) handleSapFile(k, e.dataTransfer.files[0]); };
    if ($('sapsample')) $('sapsample').onclick = ()=> applySapText(k, F.sapSample, 'SAP_EXTRACT_'+F.personnelNo+'.txt (saved sample)');
    $('saptemplate').onclick = ()=> openModal('SAP extract layout', '<p class="src">A text export in this layout is read directly. Tabs or pipes separate the report columns.</p><code class="esp">'+esc(sapTemplate(F))+'</code>');
  }
}

async function handleSapFile(k, file){
  await registerUpload(k, file, 'SAP extracts');
  if (/\.(txt|csv|json)$/i.test(file.name) || /^text\//.test(file.type)){
    const text = await file.text();
    applySapText(k, text, file.name);
  } else {
    sapManualForm(k, file.name);
  }
}

function applySapText(k, text, fileName){
  const s = STATE[k], F = s.F;
  let ex;
  try { ex = parseSapFile(fileName, text); } catch(e){ $('sapmsg').innerHTML = '<div class="notice red" style="margin-top:12px">The file could not be read: '+esc(e.message)+'</div>'; return; }
  if (!ex.payslip && !ex.recalc){ $('sapmsg').innerHTML = '<div class="notice red" style="margin-top:12px">No pay slip or re-calculation report section was found in '+esc(fileName)+'. Use the extract layout.</div>'; return; }
  const issues = checkSapAgainstCase(ex, F);
  if (issues.length){ $('sapmsg').innerHTML = '<div class="notice red" style="margin-top:12px"><b>Not accepted.</b> '+issues.map(esc).join(' ')+'</div>'; logAudit(k,'SAP extract rejected', fileName+': '+issues.join(' ')); return; }
  F.sap = { payslip: ex.payslip || (F.sap && F.sap.payslip) || null, recalc: ex.recalc || (F.sap && F.sap.recalc) || null, source:'upload', file:fileName };
  logAudit(k, 'SAP extract accepted', fileName+(ex.payslip?', pay slip':'')+(ex.recalc?', re-calculation report ('+ex.recalc.rows.length+' periods)':''));
  reprocess(k, 'SAP extract uploaded: '+fileName);
  renderSap(k);
}

function sapManualForm(k, fileName){
  const F = STATE[k].F;
  const fld = (id, lab, v) => '<div><label for="'+id+'">'+lab+'</label><input type="text" id="'+id+'" value="'+esc(v||'')+'"></div>';
  $('sapmsg').innerHTML = '<div class="dispform" style="margin-top:12px"><div class="notice blue" style="margin-bottom:12px">'+esc(fileName)+' is a PDF or image. In production the reading stage lifts these figures; in this prototype, key them from the extract.</div>'+
    '<div class="row3">'+fld('m_pers','Personnel no.',F.personnelNo)+fld('m_month','Pay slip month','')+fld('m_bal','GPF balance (Rs)','')+'</div>'+
    '<div class="row3">'+fld('m_old','Old GPF no.','')+fld('m_loan','GPF advance balance (Rs)','')+fld('m_osd','OSD post (yes / no)','')+'</div>'+
    '<div class="row3">'+fld('m_start','Last report period from','')+fld('m_end','to','')+fld('m_close','Closing balance (Rs)','')+'</div>'+
    '<button class="abtn on" id="m_go">Accept figures and re-check the case</button></div>';
  $('m_go').onclick = ()=>{
    const g = id => $(id).value.trim();
    const ex = { payslip:{ persNo:g('m_pers'), month:g('m_month'), gpfBalance:num(g('m_bal')), oldGpfNo:g('m_old'), loanBalance:num(g('m_loan')), osdPost:g('m_osd') },
                 recalc: g('m_close') ? { persNo:g('m_pers'), rows:[{start:g('m_start'), end:g('m_end'), closing:num(g('m_close'))}] } : null };
    const issues = checkSapAgainstCase(ex, F);
    if (issues.length){ alert(issues.join(' ')); return; }
    F.sap = { payslip:ex.payslip, recalc:ex.recalc || (F.sap && F.sap.recalc) || null, source:'upload', file:fileName+' (figures keyed by '+OFFICER.name+')' };
    logAudit(k, 'SAP figures keyed from uploaded extract', fileName);
    reprocess(k, 'SAP extract uploaded: '+fileName);
    renderSap(k);
  };
}

/* shared: re-run the rules and remember why */
function reprocess(k, reason){
  const s = STATE[k];
  s.lastReason = reason;
  const d = runCase(k, reason);
  const L = lists(s.results);
  logAudit(k, 'Case reprocessed, version '+s.version, reason+'. Now '+plural(L.hard.length,'hard stop')+', '+plural(L.adv.length,'observation')+', '+plural(L.conf.length,'verification task')+', '+plural(L.sap.length,'SAP item')+
    (d ? '. Resolved '+d.resolved.length+', newly raised '+d.raised.length+'.' : '.'));
  $('casetag').innerHTML = '<b>'+esc(CASES[k].label)+'</b> · '+esc(CASES[k].subject)+' · version '+s.version;
  return d;
}

function diffBanner(k){
  const s = STATE[k], d = s.lastDiff;
  if (!d) return '';
  const li = x => '<li>'+esc(x.r.doc || x.r.title)+': '+vd(x.was||'na', (STLAB[x.was]||STLAB.na)[1])+' now '+vd(x.r.status)+'</li>';
  const mixed = d.raised.length > 0;
  return '<div class="diff'+(mixed?' mixed':'')+'"><h4>Reprocessed, version '+s.version+': '+esc(s.lastReason||'')+'</h4>'+
    (d.resolved.length ? '<div><b>'+plural(d.resolved.length,'item')+' now satisfied</b><ul>'+d.resolved.map(li).join('')+'</ul></div>' : '<div>No open item was cleared by this change.</div>')+
    (d.raised.length ? '<div style="margin-top:6px"><b>'+plural(d.raised.length,'item')+' newly raised</b><ul>'+d.raised.map(li).join('')+'</ul></div>' : '')+
    (d.changed.length ? '<div style="margin-top:6px"><b>'+plural(d.changed.length,'item')+' changed</b><ul>'+d.changed.map(li).join('')+'</ul></div>' : '')+
    '</div>';
}
