/* ═══════════════════════════════════════════════════════════════════════
   UI: navigation, shared helpers, page viewer, intake, initial processing
   ═══════════════════════════════════════════════════════════════════════ */
let sel = null;
const $ = id => document.getElementById(id);
function esc(s){ return String(s===undefined||s===null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function vd(status, label){ const v = STLAB[status] || STLAB.na; return '<span class="vd '+v[0]+'">'+esc(label||v[1])+'</span>'; }
function plural(n, one, many){ return n + ' ' + (n===1 ? one : (many || one+'s')); }

function go(n){
  document.querySelectorAll('.screen').forEach(s=>s.classList.remove('on'));
  $('s'+n).classList.add('on');
  $('stepwrap').style.display = (n==='doa' || n==='rules') ? 'none' : '';
  document.querySelectorAll('.step').forEach(s=>{
    const i = +s.dataset.s;
    s.classList.toggle('active', i===n);
    s.classList.toggle('done', typeof n==='number' && i<n);
  });
  $('casetag').innerHTML = sel && STATE[sel] ? '<b>'+esc(CASES[sel].label)+'</b> · '+esc(CASES[sel].subject)+' · version '+STATE[sel].version : '';
  window.scrollTo({top:0});
}

/* officer switcher */
OFFICERS.forEach(o=>{ const opt=document.createElement('option'); opt.value=o.id; opt.textContent=o.desig+'  ·  '+o.grade; $('who').appendChild(opt); });
$('who').value='ao';
$('who').onchange=()=>{ OFFICER = OFFICERS.find(o=>o.id===$('who').value); repaint(); };
function repaint(){
  const on = document.querySelector('.screen.on'); if (!on) return;
  const id = on.id;
  if (id==='s4' && sel) renderExam(sel);
  if (id==='s5' && sel) renderDisposal(sel);
  if (id==='sdoa') renderDoa();
}

/* ── page viewer ───────────────────────────────────────────────────────── */
function pageSrc(F, p){ return 'pages/' + F.slug + '/p' + String(p).padStart(3,'0') + '.jpg'; }
function openModal(title, html){ $('mtitle').textContent = title; $('mbody').innerHTML = html; $('modal').classList.add('on'); }
$('mclose').onclick = ()=> $('modal').classList.remove('on');
$('modal').onclick = e=>{ if (e.target.id==='modal') $('modal').classList.remove('on'); };
document.addEventListener('keydown', e=>{ if (e.key==='Escape') $('modal').classList.remove('on'); });

window.viewPage = function(k, p, bbox, label){
  const s = STATE[k] || { F:CASES[k] }, F = s.F;
  if (typeof p === 'string' && p.indexOf('upload:') === 0){
    const name = p.slice(7).trim(), u = (s.uploads||[]).find(x=>x.name===name);
    if (u && u.url && /^image\//.test(u.type)) openModal('Uploaded: '+name, '<img src="'+u.url+'" style="max-width:100%">');
    else openModal('Uploaded: '+name, '<p class="src">'+(u ? esc(u.type||'file')+', '+fmtSize(u.size)+', SHA-256 '+esc(u.hash) : 'Uploaded document')+'</p><p>The file is held with the case. PDF uploads open in the document store in production.</p>');
    return;
  }
  const meta = (F.pageIndex||[]).find(x=>x.p===p) || {};
  let h = '<div class="src" style="margin-bottom:8px">'+esc(meta.title||'')+(label ? ' · highlighted: '+esc(label) : '')+'</div>'+
          '<div class="pgwrap"><img id="pgimg" src="'+pageSrc(F,p)+'" alt="page '+p+'">';
  if (bbox){ h += '<div class="pgbox" id="pgbox" style="display:none"></div>'; }
  h += '</div>';
  openModal(F.label+', page '+p, h);
  if (bbox){
    const img = $('pgimg');
    const place = ()=>{
      const dims = (F.pageDims||{})[p]; if (!dims) return;
      const sx = img.clientWidth / dims[0], sy = img.clientHeight / dims[1];
      const b = $('pgbox'); b.style.display='block';
      b.style.left = (bbox[0]*sx)+'px'; b.style.top=(bbox[1]*sy)+'px';
      b.style.width = ((bbox[2]-bbox[0])*sx)+'px'; b.style.height=((bbox[3]-bbox[1])*sy)+'px';
    };
    if (img.complete) place(); else img.onload = place;
  }
};
function pglink(k, p, label, bbox){
  if (p===undefined || p===null || p==='') return '';
  const lab = (typeof p === 'string' && p.indexOf('upload:')===0) ? 'uploaded document' : 'p'+p;
  return '<span class="pglink" onclick=\'viewPage('+JSON.stringify(k)+','+JSON.stringify(p)+','+JSON.stringify(bbox||null)+','+JSON.stringify(label||'')+')\'>'+esc(lab)+'</span>';
}
function evBox(k, e){
  const img = e.crop ? '<img src="evidence/'+esc(CASES[k].slug)+'/'+esc(e.crop)+'" alt="" onclick=\'viewPage('+JSON.stringify(k)+','+JSON.stringify(e.page)+','+JSON.stringify(e.bbox||null)+','+JSON.stringify(e.label||'')+')\'>'
                     : '<div class="noimg">no crop</div>';
  return '<div class="evbox">'+img+'<div class="evcap"><b>'+esc(e.label||'')+'</b> '+pglink(k, e.page, e.label, e.bbox)+'</div></div>';
}
function fmtSize(b){ return b > 1048576 ? (b/1048576).toFixed(1)+' MB' : Math.max(1, Math.round(b/1024))+' KB'; }

/* ── uploads: every file is hashed and kept with the case ──────────────── */
async function hashFile(file){
  try{
    const buf = await file.arrayBuffer();
    const h = await crypto.subtle.digest('SHA-256', buf);
    return Array.from(new Uint8Array(h)).map(b=>b.toString(16).padStart(2,'0')).join('');
  } catch(e){ return 'unavailable in this browser context'; }
}
function pickFile(accept){
  return new Promise(res=>{
    const inp = $('filepick'); inp.value=''; inp.accept = accept || '';
    inp.onchange = ()=> res(inp.files && inp.files[0] ? inp.files[0] : null);
    inp.click();
  });
}
async function registerUpload(k, file, against){
  const s = STATE[k];
  const u = { name:file.name, size:file.size, type:file.type || 'application/octet-stream', hash: await hashFile(file),
              url: /^image\//.test(file.type) ? URL.createObjectURL(file) : null, against, at:stamp(), by:OFFICER.name };
  s.uploads.push(u);
  logAudit(k, 'Document uploaded', file.name+' ('+fmtSize(file.size)+', SHA-256 '+u.hash.slice(0,16)+'...) against: '+against);
  return u;
}

/* ── screen 1: intake ──────────────────────────────────────────────────── */
function corpusHeadline(){
  let hard=0, adv=0, sapIn=0, qrRead=0, qrAll=0, conf=0;
  ORDER.forEach(k=>{
    const r = evaluate(CASES[k]), L = lists(r);
    hard += L.hard.length; adv += L.adv.length; conf += L.conf.length;
    if (CASES[k].sap && CASES[k].sap.payslip && CASES[k].sap.recalc) sapIn++;
    (CASES[k].qr||[]).forEach(q=>{ qrAll++; if (q.decoded) qrRead++; });
  });
  return { hard, adv, sapIn, qrRead, qrAll, conf };
}
function renderIntake(){
  const H = corpusHeadline();
  let h = '<h1 class="pagetitle">GP Fund case intake</h1>'+
    '<p class="pagesub">Pre-audit against Office Circular No. G.P. Fund-I (Coord)/TR/127 dated 21.12.2023, the Punjab GP Fund Rules 1978, and the office’s clarifications of 15-09-2026.</p>'+
    '<div class="kpis">'+
      '<div class="kpi"><div class="kv">'+ORDER.length+'</div><div class="kl">cases supplied, all eight case types</div></div>'+
      '<div class="kpi"><div class="kv">'+H.sapIn+' / '+ORDER.length+'</div><div class="kl">cases that arrived with the SAP pay slip and re-calculation report</div></div>'+
      '<div class="kpi"><div class="kv">'+H.hard+'</div><div class="kl">hard stops across the eight cases, as submitted</div></div>'+
      '<div class="kpi"><div class="kv">'+H.qrRead+' / '+H.qrAll+'</div><div class="kl">QR codes read from the scans and checked</div></div>'+
    '</div>'+
    '<div class="notice gold"><b>What changed after the office’s review.</b> Covering letters are accepted as they come. Unattested CNIC copies and pay slips are noted, not objected to. '+
    'SAP extracts are marked on the checklist when present and can be uploaded straight after initial processing when not. Every open item can be cured by uploading a document against it, and the case is re-checked.</div>'+
    '<div class="card"><h3>Select a case</h3><p class="hint">The pages are read on this machine and nothing leaves it.</p><div class="caselist" id="caselist"></div></div>'+
    '<div class="card" id="casemeta" style="display:none"></div>'+
    '<div class="actionbar"><button class="btn" id="run" disabled>Run initial processing</button><span class="src" id="runhint">Select a case to begin.</span></div>';
  $('s1body').innerHTML = h;
  ORDER.forEach(k=>{
    const F = CASES[k], d = document.createElement('div');
    d.className = 'caseopt' + (sel===k ? ' sel' : ''); d.dataset.k = k;
    d.innerHTML = '<div style="flex:1"><div class="cn">'+esc(F.label)+'</div><div class="cm">'+esc(F.note)+'</div></div><div class="pgcount">'+F.pages+' pp</div>';
    d.onclick = ()=> selectCase(k);
    $('caselist').appendChild(d);
  });
  if (sel) selectCase(sel);
  $('run').onclick = startRun;
}
function selectCase(k){
  sel = k;
  document.querySelectorAll('.caseopt').forEach(x=>x.classList.toggle('sel', x.dataset.k===k));
  const F = CASES[k], hasSap = !!(F.sap && (F.sap.payslip || F.sap.recalc));
  const m = $('casemeta'); m.style.display='block';
  m.innerHTML = '<h3>Case detected &amp; dak particulars</h3><p class="hint">Case type is bound from the documents present, before any checking begins.</p>'+
    '<table><tr><th>Case</th><th>Pages</th><th>Case type</th><th>Subscriber</th><th>Personnel no.</th><th>SAP pages in the case</th></tr>'+
    '<tr><td class="fv">'+esc(F.label)+'</td><td>'+F.pages+'</td><td>'+esc(F.sub)+'</td><td>'+esc(F.subject)+'</td><td class="mono">'+esc(F.personnelNo||'not stated')+'</td>'+
    '<td>'+(hasSap ? [F.sap.payslip?'pay slip p'+F.sap.payslip.page:'', F.sap.recalc?'re-calculation report p'+F.sap.recalc.page:''].filter(Boolean).join(', ') : '<span class="blank">none</span>')+'</td></tr></table>'+
    '<div class="dispform" style="margin-top:14px"><div class="row2">'+
      '<div><label for="dkno">Diary / token no.</label><input id="dkno" type="text" value="'+esc(F.diary||'')+'"></div>'+
      '<div><label for="dkdate">Date of receipt in this office</label><input id="dkdate" type="text" placeholder="dd-mm-yyyy"></div></div>'+
      '<div class="row2"><div><label for="dkmark">Marked to</label><input id="dkmark" type="text" value="GP Fund-I, Dealing Assistant"></div>'+
      '<div><label for="dkret">Return count on this case so far</label><select id="dkret"><option value="0">0, first submission</option><option value="1">1, already returned once</option></select></div></div>'+
      (hasSap ? '<label class="chk"><input type="checkbox" id="nosap"> <span>Treat this case as received <b>without</b> its SAP pages, to see the SAP extract upload in use</span></label>' : '')+
    '</div>';
  $('run').disabled = false;
  $('runhint').textContent = 'In production, about four minutes on one DGX Spark for a case this size.';
}

/* ── screen 2: initial processing ─────────────────────────────────────── */
const STAGES = [
  ['Ingest and sort the pages','Split, straighten and clean each page. A page that cannot be made legible is flagged, not guessed at.','Image handling. No AI.'],
  ['Read each page','Text, layout and reading order, in Urdu and English alike.','AI reads'],
  ['Identify each document','Every page given its type from its layout and content, never from the file name.','AI reads'],
  ['Lift the fields','Each document type has its own field list. Every value carries a confidence and the page it came from.','AI reads'],
  ['Scan QR codes and barcodes','Every code on every page decoded and its content compared with the printed document.','Decoder. No AI.'],
  ['Settle the case type','Case type fixed from the documents present, and the governing checklist attached.','Rules decide'],
  ['Mark the checklist','Each required document marked present, absent or defective. SAP extracts found in the case are marked off.','Rules decide'],
  ['Compare the documents','Personal numbers, names, CNICs, dates and amounts checked against each other and against SAP.','Rules decide'],
  ['Check the signatories','Every signature for or on behalf of an authority looked up in the delegation of authority register.','Rules decide, officer confirms'],
  ['Test the balance and advances','80% limit, advances outstanding, and the claim against the re-calculation report.','Rules decide'],
  ['Match to the circular and office rules','Every failure matched to its standardised rejection reason or office clarification.','Rules decide'],
  ['Draft the observations','One sheet: document, defect, clause, remedy and severity.','Drafted by AI, checked against the rules']
];
function startRun(){
  const k = sel, withoutSap = $('nosap') ? $('nosap').checked : false;
  STATE[k] = newState(k, withoutSap);
  const s = STATE[k];
  s.dak = { no:$('dkno').value || '(not entered)', date:$('dkdate').value || '(not entered)', marked:$('dkmark').value || '(not entered)' };
  s.returns = parseInt($('dkret').value,10) || 0;
  logAudit(k, 'Case taken up for pre-audit', 'Diary '+s.dak.no+', received '+s.dak.date+', marked to '+s.dak.marked+'. Prior returns: '+s.returns+'.'+(withoutSap ? ' Received without SAP extracts.' : ''));
  go(2);
  const F = s.F;
  $('s2body').innerHTML = '<h1 class="pagetitle">Initial processing</h1><p class="pagesub">Reading '+F.pages+' pages. '+esc(F.label)+' for '+esc(F.subject)+'.</p>'+
    '<div class="pbar"><div class="pipe" id="pipe"></div></div><div class="card"><div id="stagelist"></div></div>'+
    '<div class="notice grey">Every stage runs inside this office, on its own servers. The AI reads the papers. The rules decide the outcome. Nothing is sent outside.</div>';
  STAGES.forEach((sg,i)=>{
    const d = document.createElement('div'); d.className='stage pend'; d.id='st'+i;
    d.innerHTML = '<div class="sic">'+(i+1)+'</div><div><div class="sn">'+sg[0]+'</div><div class="sd">'+sg[1]+'</div><div class="smodel">'+sg[2]+'</div></div>';
    $('stagelist').appendChild(d);
  });
  let i = 0;
  const tick = ()=>{
    if (i>0){ const p=$('st'+(i-1)); p.className='stage ok'; p.querySelector('.sic').textContent='✓'; }
    if (i>=STAGES.length){
      $('pipe').style.width='100%';
      runCase(k, 'Initial processing');
      const L = lists(s.results);
      logAudit(k, 'Initial processing completed by the module', plural(L.hard.length,'hard stop')+', '+plural(L.adv.length,'observation')+', '+plural(L.conf.length,'verification task')+', '+plural(L.sap.length,'SAP item')+'.');
      setTimeout(()=>{ renderSap(k); go(3); }, 420); return;
    }
    $('st'+i).className='stage run'; $('pipe').style.width=((i/STAGES.length)*100)+'%';
    i++; setTimeout(tick, 260+i*24);
  };
  tick();
}

$('lnkCases').onclick = ()=>{ renderIntake(); go(1); };
