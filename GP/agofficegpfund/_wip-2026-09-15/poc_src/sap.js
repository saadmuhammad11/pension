/* ═══════════════════════════════════════════════════════════════════════
   SAP EXTRACTS
   MVP: the section pulls the pay slip and the GPF Final Re-calculation Report
   from SAP by personnel number and uploads them here. Later a connector fetches
   them directly. Both routes produce the same SapExtract object, so nothing
   downstream changes when the connector arrives.
   ═══════════════════════════════════════════════════════════════════════ */
const SAP_CONNECTOR = {
  mode: 'manual-upload',            // 'manual-upload' now; 'sap-connector' in phase 2
  status: 'Not configured',
  note: 'Phase 2: automatic retrieval from SAP by personnel number, through the connector described in the build specification.'
};

function num(v){
  if (v === null || v === undefined) return null;
  const s = String(v).replace(/[, ]/g,'').replace(/\/-$/,'').replace(/-$/,'');
  if (s === '' || isNaN(Number(s))) return null;
  return Number(s);
}
function fmt(n){
  if (n === null || n === undefined || isNaN(n)) return '';
  return Number(n).toLocaleString('en-PK', {maximumFractionDigits:0});
}

/* Text extract format (mirrors an SAP list export saved as text):
     SAP EXTRACT: PAY SLIP
     Personnel No: 90000227
     ...key: value lines...
     SAP EXTRACT: GPF FINAL RE-CALCULATION REPORT
     Personnel No: 90000227
     Start Date|End Date|Opening Balance|Monthly Subscription|Adjustments|Temp Advance|Rec of Temp Advance|Permanent Advance|Interest Applied|Closing Balance
     01.07.2025|30.06.2026|...
   Tabs or pipes are both accepted. JSON {payslip:{..}, recalc:{..}} is also accepted. */
const PAYSLIP_KEYS = {
  'personnel no':'persNo', 'pers no':'persNo', 'name':'name', 'designation':'designation', 'cnic':'cnic',
  'month':'month', 'bps':'bps', 'ddo code':'ddoCode', 'gpf no':'gpfNo', 'old gpf no':'oldGpfNo',
  'gpf balance':'gpfBalance', 'gpf subscription':'gpfSubscription',
  'gpf loan instalment':'loanInstalment', 'gpf loan balance':'loanBalance',
  'osd post':'osdPost', 'employment status':'status', 'bank':'bank'
};
const RECALC_COLS = ['start','end','opening','subscription','adjustments','tempAdvance','recTempAdvance','permanentAdvance','interest','closing'];

function parseSapText(text){
  const out = { payslip:null, recalc:null, warnings:[] };
  let section = null, cur = null;
  text.split(/\r?\n/).forEach(raw=>{
    const line = raw.trim();
    if (!line) return;
    const head = line.toUpperCase();
    if (head.startsWith('SAP EXTRACT:')){
      if (head.includes('PAY SLIP')){ section='payslip'; cur = out.payslip = {}; }
      else if (head.includes('RE-CALCULATION') || head.includes('RECALCULATION')){ section='recalc'; cur = out.recalc = {rows:[]}; }
      else { section=null; out.warnings.push('Unrecognised section: '+line); }
      return;
    }
    if (!section) return;
    const cells = line.split(/\t|\|/).map(c=>c.trim());
    if (section==='recalc' && cells.length >= 10){
      if (/start/i.test(cells[0])) return;                 // header row
      const r = {};
      RECALC_COLS.forEach((k,i)=>{ r[k] = i<2 ? cells[i] : num(cells[i]); });
      cur.rows.push(r);
      return;
    }
    const m = line.match(/^([^:]+):\s*(.*)$/);
    if (!m) return;
    const key = m[1].trim().toLowerCase(), val = m[2].trim();
    if (section==='payslip'){
      const k = PAYSLIP_KEYS[key];
      if (!k){ out.warnings.push('Ignored pay slip line: '+line); return; }
      cur[k] = ['gpfBalance','gpfSubscription','loanInstalment','loanBalance'].includes(k) ? num(val) : val;
    } else {
      if (key==='personnel no') cur.persNo = val;
      else if (key==='gpf reference no') cur.gpfRef = val;
      else if (key==='report date') cur.reportDate = val;
      else if (key==='name') cur.name = val;
    }
  });
  return out;
}

function parseSapFile(name, text){
  const t = text.trim();
  if (t.startsWith('{')){
    const j = JSON.parse(t);
    return { payslip:j.payslip||null, recalc:j.recalc||null, warnings:[] };
  }
  return parseSapText(t);
}

/* Validate an extract against the case before it is accepted. */
function checkSapAgainstCase(ex, F){
  const issues = [];
  const want = String(F.personnelNo||'').replace(/\D/g,'');
  [['pay slip',ex.payslip],['re-calculation report',ex.recalc]].forEach(([lab,part])=>{
    if (!part) return;
    const got = String(part.persNo||'').replace(/\D/g,'');
    if (!got) issues.push('The '+lab+' carries no personnel number.');
    else if (want && got !== want) issues.push('The '+lab+' is for personnel no. '+part.persNo+', not '+F.personnelNo+'. It belongs to a different employee.');
  });
  return issues;
}

/* Last row of the re-calculation report and derived positions. */
function recalcSummary(recalc){
  if (!recalc || !recalc.rows || !recalc.rows.length) return null;
  const rows = recalc.rows;
  const last = rows[rows.length-1];
  let tempDrawn=0, tempRec=0;
  rows.forEach(r=>{ tempDrawn += (r.tempAdvance||0); tempRec += (r.recTempAdvance||0); });
  return { last, tempDrawn, tempRec, tempOutstanding: tempDrawn - tempRec, rows };
}

/* A downloadable text template the section can fill from SAP screens. */
function sapTemplate(F){
  return 'SAP EXTRACT: PAY SLIP\nPersonnel No: '+(F.personnelNo||'')+
    '\nName: \nDesignation: \nCNIC: \nMonth: \nBPS: \nDDO Code: \nGPF No: \nOld GPF No: \nGPF Balance: \nGPF Subscription: '+
    '\nGPF Loan Instalment: \nGPF Loan Balance: \nOSD Post: \n\nSAP EXTRACT: GPF FINAL RE-CALCULATION REPORT\nPersonnel No: '+(F.personnelNo||'')+
    '\nGPF Reference No: \nReport Date: \n'+
    'Start Date|End Date|Opening Balance|Monthly Subscription|Adjustments|Temp Advance|Rec of Temp Advance|Permanent Advance|Interest Applied|Closing Balance\n';
}
