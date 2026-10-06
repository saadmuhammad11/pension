"""The case pages an examination item rests on, for the officer to open and check. 30 Sep 2026.

A rule attaches evidence where it cut a crop or quoted a page, but most items that compare two
papers attached nothing: "Applicant on the form is the subscriber" compares the change form, the
SAP pay slip and the CNIC, and showed no page at all. The case facts already say where every
paper is (``F.docs.<paper>.page``, ``F.sap.payslip.page`` ...), so each item is given the pages
of the papers it names or compares. Display only: nothing here changes what a rule decides.

An item about a paper that is NOT in the case ("Change Form-06 is not attached") gets no page for
it -- there is none -- only the pages of the other papers it names.
"""
from __future__ import annotations

import re

#: Paper -> (how the officer calls it, the words that name it in an item).
PAPERS: dict[str, tuple[str, str]] = {
    "payslip": ("SAP pay slip", r"pay ?slip|sap extract|sap pay|personnel no|pers\.? no"),
    "recalc": ("SAP re-calculation report", r"re-?calculation|recalc|ledger|closing balance|\bbalance\b"),
    "sanction": ("Sanction order", r"sanction"),
    "changeForm": ("Application form", r"form pay ?0?5|\bform ?5\b|form 6-?b|change form|form-?0?6|\bthe form\b|on the form|personal number|old gp fund a/?c"),
    "cnics": ("CNIC copy", r"cnic|identity card|smart card|\bcard\b"),
    "gpf10": ("GPF-10", r"gpf-?10|form 10\b"),
    "notification": ("Notification", r"notification|obituary"),
    "covering": ("Covering letter", r"covering|forwarding"),
}
#: Items whose wording does not name every paper they compare.
BY_ID: dict[str, tuple[str, ...]] = {
    "ADV-APPLICANT": ("changeForm", "payslip", "cnics"),
    "ADV-PERSNO": ("changeForm", "payslip"),
    "SAP-IDENTITY": ("payslip", "recalc"),
    "ADV-LIMIT": ("sanction", "payslip", "recalc"),
    "ADV-ACTIVE": ("recalc", "payslip"),
    "ADV-FORM-CNIC": ("changeForm", "cnics"),
}


def _pages_of(F: dict, paper: str) -> list[int]:
    if paper in ("payslip", "recalc"):
        node = ((F.get("sap") or {}).get(paper) or {})
        return [node["page"]] if isinstance(node.get("page"), int) else []
    node = (F.get("docs") or {}).get(paper)
    nodes = node if isinstance(node, list) else [node]
    return [n["page"] for n in nodes if isinstance(n, dict) and isinstance(n.get("page"), int)]


def reference_pages(item: dict, F: dict) -> list[dict]:
    """``[{"page": n, "label": ..., "reference": True}]``, the pages of the papers ``item`` rests on."""
    text = " ".join(str(item.get(k) or "") for k in ("title", "doc", "finding"))
    low = text.lower()
    papers = list(BY_ID.get(item.get("id") or "", ()))
    for key, (_label, words) in PAPERS.items():
        if key not in papers and re.search(words, low):
            papers.append(key)
    out: list[dict] = []
    seen: set[int] = set()
    for key in papers:
        for page in _pages_of(F, key):
            if page not in seen:
                seen.add(page); out.append({"page": page, "label": f"{PAPERS[key][0]} · page {page}", "reference": True})
    # A page the finding itself quotes ("the copy ... at page 5").
    for m in re.finditer(r"\bpages? (\d{1,3})\b", low):
        page = int(m.group(1))
        if page not in seen:
            seen.add(page); out.append({"page": page, "label": f"Page {page}", "reference": True})
    return out
