/* ═══════════════════════════════════════════════════════════════════════
   RULES ENGINE
   The reading stage produces FACTS. Plain rules turn facts into results.
   Nothing in here reads an image or calls a model. An upload changes the
   facts; the case is then re-evaluated from scratch and compared with the
   previous run, so a cured observation is closed by the same rule that
   raised it.

   Result status vocabulary
     ok    satisfied
     sub   satisfied by an accepted substitute (e.g. challans for a certificate)
     hard  not satisfied, the case cannot advance      (goes on the rejection form)
     adv   observation, does not block                  (advisory memorandum)
     conf  officer to verify (signature, specimen, thumb impression, QR online)
     sap   awaiting SAP extract, action for this section, not a department defect
     na    not applicable
   ═══════════════════════════════════════════════════════════════════════ */
const STLAB = {
  ok:['ok','Satisfied'], sub:['sub','Satisfied by substitute'], hard:['hard','Not satisfied'],
  adv:['adv','Observation'], conf:['conf','Officer to verify'], sap:['sap','Awaiting SAP extract'],
  na:['pend','Not applicable']
};
const ISSUE = s => s==='hard' || s==='adv';

function clone(o){ return JSON.parse(JSON.stringify(o)); }

/* Evaluate every applicable check against the facts. */
function evaluate(F){
  const out = [];
  const all = CHECKS.concat((F.custom||[]).map(c=>CUSTOM_CHECKS[c]).filter(Boolean));
  all.forEach(ch=>{
    let applies = false;
    try { applies = ch.applies(F); } catch(e){ applies = false; }
    if (!applies) return;
    let r;
    try { r = ch.run(F); } catch(e){ r = {status:'conf', finding:'The rule could not be evaluated on the facts available ('+e.message+'). Check by hand.'}; }
    if (!r) return;
    (Array.isArray(r) ? r : [r]).forEach(one=>{
      if (!one) return;
      out.push(Object.assign({
        id: ch.id, group: ch.group, ref: ch.ref, code: ch.code || ch.ref, title: ch.title,
        checklist: ch.checklist || null, doc: ch.title, evidence: [], cure: null
      }, one, { id: one.sub ? ch.id + ':' + one.sub : ch.id }));
    });
  });
  return out;
}

function lists(results){
  return {
    hard: results.filter(r=>r.status==='hard'),
    adv:  results.filter(r=>r.status==='adv'),
    obs:  results.filter(r=>ISSUE(r.status)).sort((x,y)=>(x.status==='hard'?0:1)-(y.status==='hard'?0:1)),
    conf: results.filter(r=>r.status==='conf'),
    sap:  results.filter(r=>r.status==='sap'),
    ok:   results.filter(r=>r.status==='ok' || r.status==='sub')
  };
}

/* Compare two runs of the same case. */
function diffRuns(prev, next){
  const pm = {}; prev.forEach(r=>pm[r.id]=r);
  const nm = {}; next.forEach(r=>nm[r.id]=r);
  const d = { resolved:[], raised:[], changed:[], stillOpen:[] };
  next.forEach(r=>{
    const p = pm[r.id];
    const was = p ? p.status : null;
    const openNow = ISSUE(r.status) || r.status==='conf' || r.status==='sap';
    const openBefore = was && (ISSUE(was) || was==='conf' || was==='sap');
    if (openBefore && !openNow) d.resolved.push({r, was});
    else if (!openBefore && openNow) d.raised.push({r, was});
    else if (openBefore && openNow && was !== r.status) d.changed.push({r, was});
    else if (openNow) d.stillOpen.push({r, was});
  });
  prev.forEach(p=>{
    if (!nm[p.id] && (ISSUE(p.status) || p.status==='conf' || p.status==='sap'))
      d.resolved.push({r:Object.assign({}, p, {status:'na'}), was:p.status});
  });
  return d;
}

/* ═══════════════════════════════════════════════════════════════════════
   DELEGATION OF POWERS INSIDE THIS OFFICE (who may dispose of what)
   ═══════════════════════════════════════════════════════════════════════ */
const OFFICERS = [
  { id:'da',  name:'Muhammad Adnan', desig:'Dealing Assistant, GP Fund-I', grade:'BS-16', level:1 },
  { id:'ao',  name:'Sadia Rehman',   desig:'Accounts Officer, GP Fund-I',  grade:'BS-18', level:2 },
  { id:'dag', name:'Fatima Hameed',  desig:'Deputy Accountant General (Funds)', grade:'BS-20', level:3 }
];
let OFFICER = OFFICERS[1];

function may(action, sev){
  const L = OFFICER.level;
  if (action==='uphold') return true;
  if (action==='refer')  return L <= 2;
  if (action==='correct') return L >= 2;
  if (action==='waive')  return sev==='hard' ? L >= 3 : L >= 2;
  if (action==='verify') return L >= 2;
  if (action==='upload') return true;
  return false;
}
function whoCan(action, sev){
  if (action==='correct') return 'the Accounts Officer or above';
  if (action==='verify')  return 'the Accounts Officer or above';
  if (action==='waive')   return sev==='hard' ? 'the Deputy Accountant General (Funds)' : 'the Accounts Officer or above';
  return '';
}

/* ═══════════════════════════════════════════════════════════════════════
   CASE STATE
   ═══════════════════════════════════════════════════════════════════════ */
const STATE = {};
function stamp(){
  const d = new Date(), p = n => String(n).padStart(2,'0');
  return p(d.getDate())+'-'+p(d.getMonth()+1)+'-'+d.getFullYear()+' '+p(d.getHours())+':'+p(d.getMinutes());
}
function newState(k, withoutSap){
  const F = clone(CASES[k]);
  if (withoutSap){ F.sap = null; F.persNos = (F.persNos||[]).filter(x=>!/SAP|Re-calculation/i.test(x.doc)); }
  return { k, F, withoutSap: !!withoutSap, version:1, results:[], prev:null, lastDiff:null,
           history:[], disp:{}, caseDisp:null, caseNote:'', audit:[], dak:{}, returns:0, issued:false, uploads:[] };
}
function st(k){ return STATE[k]; }
function logAudit(k, what, detail){
  STATE[k].audit.push({ at:stamp(), by:OFFICER.name, desig:OFFICER.desig, grade:OFFICER.grade, what, detail });
}

function runCase(k, reason){
  const s = STATE[k];
  const next = evaluate(s.F);
  if (s.results.length){
    s.prev = s.results;
    s.lastDiff = diffRuns(s.results, next);
    s.version += 1;
  }
  s.results = next;
  const L = lists(next);
  s.history.push({ v:s.version, at:stamp(), by:OFFICER.name, desig:OFFICER.desig, reason,
                   hard:L.hard.length, adv:L.adv.length, conf:L.conf.length, sap:L.sap.length,
                   resolved: s.lastDiff && s.version>1 ? s.lastDiff.resolved.length : 0,
                   raised: s.lastDiff && s.version>1 ? s.lastDiff.raised.length : 0 });
  /* dispositions on observations that no longer exist are kept, marked cured */
  Object.keys(s.disp).forEach(id=>{
    const r = next.find(x=>x.id===id);
    if (!r || !ISSUE(r.status)) s.disp[id].cured = true; else delete s.disp[id].cured;
  });
  return s.lastDiff;
}

/* live position of the case after dispositions */
function position(k){
  const s = STATE[k], L = lists(s.results);
  let hard=0, adv=0, waived=0, corrected=0, referred=0, open=0;
  L.obs.forEach(o=>{
    const d = s.disp[o.id];
    if (d && d.action==='waive'){ waived++; return; }
    if (d && d.action==='correct'){ corrected++; return; }
    if (d && d.action==='refer') referred++;
    if (o.status==='hard') hard++; else adv++;
    if (!d) open++;
  });
  return { hard, adv, waived, corrected, referred, open, total:L.obs.length,
           conf:L.conf.length, sap:L.sap.length, mayAdvance: hard===0 };
}
