/* ═══════════════════════════════════════════════════════════════════════
   CASE FACTS
   What the reading stage lifted from each of the eight cases (corpus of
   15-09-2026). The prototype ships these as fixtures; in production they are
   produced by stages 1 to 5 with a confidence and page region per field.
   Page index, page sizes and SAP figures come from GEN (generated).
   ═══════════════════════════════════════════════════════════════════════ */
const CASES = {};
function defCase(slug, f){
  const g = GEN[slug] || {};
  CASES[slug] = Object.assign({
    slug, key: slug,
    pageDims: g.pageDims || {},
    pageIndex: (g.pageIndex || []).map(x=>({ p:x.p, title:x.title })),
    sap: g.sap ? clone(g.sap) : null,
    sapSample: g.sapSample || null,
    verifications: {}, custom: [], qr: [], signatures: [], thumbs: [], docs: {}
  }, f);
}
