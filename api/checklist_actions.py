"""The officer's hand on the checklist: naming a document the reader missed, and waiving an item.

The engine's checklist says, for each paper the SOP requires, whether it found it. It can be
wrong in the one direction that matters most to a department: it reports a paper MISSING that
is in the bundle, on a page it could not identify ("pages_unaccounted") or took for something
else. Returning a case for a paper the department filed is the error the office most wants to
avoid, so the officer who can see the page can say what it is:

*   ``NAME``       a page the reader could not identify or could not read is this document, in
                   the officer's own words ("Succession certificate", "Nikah nama"). Where the
                   officer also says it is one of the checklist's papers, that item becomes
                   PRESENT, "named by <officer> on p.N". Only such pages can be named: a paper
                   the reader reported NOT FOUND is not renamed into existence -- it is found
                   on a page, or waived.
*   ``IDENTIFY``   kept for entries recorded before 23 Sep 2026 (an item placed on pages).
*   ``WAIVE``      this requirement is not needed for this case, or its defect does not stop it,
                   on a written ground. The item becomes WAIVED and no longer holds the case.
*   ``CLEAR``      take back the officer's last action on an item (or on a named document);
                   the engine's own reading applies again.

The engine's checklist is never rewritten. The officer's actions are kept in
``checklist_actions.jsonl`` beside the report, append-only like the decisions and the finding
dispositions, and laid over the engine's reading whenever the report is served
(``apply``). The engine's own counts stay in ``checklist["engine"]`` for the audit.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

LOG = "checklist_actions.jsonl"
ACTIONS = ("IDENTIFY", "NAME", "WAIVE", "CLEAR")
MIN_GROUND = 15

#: What the office calls an item the officer has dealt with.
IDENTIFIED = "PRESENT"
WAIVED = "WAIVED"


class ChecklistActionError(ValueError):
    """Not recordable. Never written to the log."""


def history(run_dir: str | Path) -> list[dict]:
    path = Path(run_dir) / LOG
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"unreadable": line[:200]})
    return out


def nameable_pages(report: dict) -> list[int]:
    """Pages an officer may name: not identified, identified only as "other", or not readable."""
    pages = set(report.get("pages_unaccounted") or [])
    for p in report.get("pages") or []:
        if isinstance(p, dict) and (p.get("document_type") in (None, "", "OTHER") or p.get("needs_human")):
            pages.add(int(p.get("page")))
    for f in report.get("flags") or []:
        if f.get("class") == "EXTRACT-LOWCONF":
            pages |= {int(e["page"]) for e in (f.get("evidence") or {}).get("asserted") or []}
    return sorted(pages)


def _key(entry: dict) -> str:
    if entry.get("name_id"):
        return f"name:{entry['name_id']}"
    return entry.get("item_id") or ""


def current(run_dir: str | Path) -> dict[str, dict]:
    """The action in force per item (and per named document); CLEAR removes it."""
    out: dict[str, dict] = {}
    for e in history(run_dir):
        if "unreadable" in e:
            continue
        k = _key(e)
        if e.get("action") == "CLEAR":
            out.pop(k, None)
        else:
            out[k] = e
    return out


def record(run_dir: str | Path, *, run_id: str, report: dict, action: str, officer: str,
           role: str, item_id: str | None = None, pages: list | None = None,
           document_name: str = "", ground: str = "", name_id: str | None = None) -> dict:
    from api.roles import RoleError, require
    if action not in ACTIONS:
        raise ChecklistActionError(f"unknown action {action!r}; expected one of {list(ACTIONS)}")
    officer = (officer or "").strip()
    if not officer:
        raise ChecklistActionError("the officer must be named; a checklist entry has an author")
    try:
        require(role or None, "decide_case")
    except RoleError as exc:
        raise ChecklistActionError(str(exc)) from None

    items = {i["id"]: i for i in (report.get("checklist") or {}).get("items") or []}
    total_pages = int(report.get("pages") or 0) if not isinstance(report.get("pages"), list) \
        else len(report["pages"])
    clean_pages = sorted({int(p) for p in (pages or []) if str(p).strip().lstrip("-").isdigit()})
    if total_pages:
        bad = [p for p in clean_pages if p < 1 or p > total_pages]
        if bad:
            raise ChecklistActionError(f"the bundle has {total_pages} pages; there is no page {bad[0]}")
    ground = (ground or "").strip()
    document_name = " ".join((document_name or "").split())[:120]

    if action in ("IDENTIFY", "WAIVE") or (action == "CLEAR" and item_id and not name_id):
        if item_id not in items:
            raise ChecklistActionError(f"this case's checklist has no item {item_id!r}")
    if action == "IDENTIFY" and not clean_pages:
        raise ChecklistActionError("name the page or pages the document is on")
    if action == "NAME":
        if not clean_pages:
            raise ChecklistActionError("name the page or pages the document is on")
        if len(document_name) < 3:
            raise ChecklistActionError("write the document's name, as the office would call it")
        allowed = set(nameable_pages(report))
        wrong = [p for p in clean_pages if p not in allowed]
        if wrong:
            raise ChecklistActionError(
                f"p.{wrong[0]} was identified by the reader; only a page it could not identify or "
                f"could not read can be named")
        if item_id is not None and item_id not in items:
            raise ChecklistActionError(f"this case's checklist has no item {item_id!r}")
        name_id = name_id or f"{clean_pages[0]}-{datetime.now():%H%M%S}"
    if action == "CLEAR" and not item_id and not name_id:
        raise ChecklistActionError("say which item or named document to clear")
    if action == "WAIVE" and len(ground) < MIN_GROUND:
        raise ChecklistActionError(
            f"waiving {item_id} ({items[item_id].get('requirement')}) lets the case go on without "
            f"that paper. A written ground of at least {MIN_GROUND} characters is required, and "
            f"it is recorded against your name.")

    entry = {
        "run_id": run_id, "action": action, "item_id": item_id, "name_id": name_id,
        "pages": clean_pages, "document_name": document_name
        or (items[item_id]["requirement"] if item_id in items and action == "IDENTIFY" else ""),
        "ground": ground, "officer": officer, "role": role,
        "at": datetime.now().isoformat(timespec="seconds"),
        # What the engine had said, copied for the audit (the report is rebuilt on recompute).
        "engine_status": items[item_id].get("status") if item_id in items else None,
        "requirement": items[item_id].get("requirement") if item_id in items else None,
    }
    path = Path(run_dir) / LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def apply(report: dict, run_dir: str | Path) -> dict:
    """The report with the officer's checklist actions laid over the engine's reading."""
    actions = current(run_dir)
    if not actions or not report.get("checklist"):
        return {**report, "nameable_pages": nameable_pages(report)}
    out = copy.deepcopy(report)
    cl = out["checklist"]
    cl["engine"] = {k: cl.get(k) for k in ("result", "missing", "defective", "present",
                                            "satisfied", "result_line")}
    claimed: set[int] = set()
    for item in cl.get("items") or []:
        a = actions.get(item["id"])
        if not a:
            continue
        item["engine_status"] = item["status"]
        item["officer_action"] = {k: a.get(k) for k in ("action", "officer", "role", "at", "ground",
                                                         "pages", "document_name")}
        if a["action"] == "IDENTIFY":
            item["status"] = IDENTIFIED
            item["located"] = sorted(set(item.get("located") or []) | set(a["pages"]))
            item["reason"] = f"identified by {a['officer']} on p.{', '.join(map(str, a['pages']))}"
            claimed |= set(a["pages"])
        elif a["action"] == "WAIVE":
            item["status"] = WAIVED
            item["reason"] = f"waived by {a['officer']}: {a['ground']}"

    named = [a for k, a in actions.items() if k.startswith("name:")]
    by_id = {i["id"]: i for i in cl.get("items") or []}
    for a in named:
        claimed |= set(a["pages"])
        item = by_id.get(a.get("item_id") or "")
        if item is not None and item["status"] in ("MISSING", "DEFECTIVE") and not item.get("officer_action"):
            item["engine_status"] = item["status"]
            item["status"] = IDENTIFIED
            item["located"] = sorted(set(item.get("located") or []) | set(a["pages"]))
            item["reason"] = (f"named \"{a['document_name']}\" by {a['officer']} on "
                              f"p.{', '.join(map(str, a['pages']))}")
            item["officer_action"] = {k: a.get(k) for k in ("action", "officer", "role", "at", "ground",
                                                             "pages", "document_name")}
            item["officer_action"]["name_id"] = a["name_id"]
    for page in out.get("pages") or []:
        for a in named:
            if isinstance(page, dict) and page.get("page") in a["pages"]:
                page["officer_named"] = a["document_name"]
    out["named_documents"] = [{"name_id": a["name_id"], "name": a["document_name"], "pages": a["pages"],
                               "item_id": a.get("item_id"), "officer": a["officer"], "at": a["at"]}
                              for a in named]
    out["nameable_pages"] = [p for p in nameable_pages(report) if p not in claimed]
    if out.get("pages_unaccounted"):
        out["pages_unaccounted"] = [p for p in out["pages_unaccounted"] if p not in claimed]

    items = cl.get("items") or []
    cl["present"] = sum(1 for i in items if i["status"] == "PRESENT")
    cl["missing"] = sum(1 for i in items if i["status"] == "MISSING")
    cl["defective"] = sum(1 for i in items if i["status"] == "DEFECTIVE")
    cl["waived"] = sum(1 for i in items if i["status"] == WAIVED)
    na = sum(1 for i in items if i["status"] in ("NOT_APPLICABLE", "NOT_REQUIRED", "FOUND_NOT_REQUIRED"))
    cl["satisfied"] = cl["present"] + na + cl["waived"]
    cl["result"] = "COMPLETE" if cl["missing"] == 0 else "INCOMPLETE"
    touched = sum(1 for i in items if i.get("officer_action"))
    if cl["result"] == "COMPLETE":
        cl["result_line"] = (f"CHECKLIST COMPLETE - {cl['satisfied']}/{cl['required']}, no missing "
                             f"document ({touched} item(s) settled by the officer).")
    else:
        names = ", ".join(i["id"] for i in items if i["status"] == "MISSING")
        cl["result_line"] = f"CHECKLIST INCOMPLETE - {cl['missing']} missing ({names})."
    return out
