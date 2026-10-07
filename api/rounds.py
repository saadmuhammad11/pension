"""Submission rounds: what the AG asked for, what came back, and what the check of it did. 30 Sep 2026.

A case the Accountant General sends back -- returned, documents requested, or returned by the
verification itself for missing papers -- comes back as the next round. This module keeps the
record of every round (migration 0008):

*   ``case_rounds``          one row per round: opened, submitted, closed. Final once closed.
*   ``case_round_requests``  what the AG asked the department for, item by item, and the remark.
                             Append-only.
*   ``case_round_checks``    one row per verification run in a round: FULL or INCREMENTAL, the
                             run it reused, what each stage ran and reused, the findings, how
                             each requested item stands, and what changed against the earlier
                             round. Final once the run has finished.

The bookkeeping rides on the history rows (``api.workflow.record_event``), inside the same
transaction, under a savepoint: a fault here is logged and never blocks the decision itself.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from api import db

log = logging.getLogger(__name__)

SEND_BACK = frozenset({"RETURN", "REQUEST_DOCS", "AUTO_RETURN", "GPF_RETURN"})
CLOSING = SEND_BACK | {"APPROVE", "REJECT", "AUTO_APPROVE"}


# -- the hook -----------------------------------------------------------------------------
def on_event(conn: sqlite3.Connection, case_id: str, action: str, entry: dict, payload: dict | None,
             actor: Any) -> None:
    """Keep the round records in step with one history row. Caller holds the transaction."""
    conn.execute("SAVEPOINT rounds")
    try:
        _on_event(conn, case_id, action, entry, payload or {}, actor)
        conn.execute("RELEASE SAVEPOINT rounds")
    except Exception:                                   # noqa: BLE001 -- bookkeeping never blocks a decision
        conn.execute("ROLLBACK TO SAVEPOINT rounds")
        conn.execute("RELEASE SAVEPOINT rounds")
        log.exception("round bookkeeping failed for %s on case %s", action, case_id)


def _on_event(conn, case_id, action, entry, payload, actor) -> None:
    case = conn.execute("SELECT id, submission_no FROM cases WHERE id = ?", (case_id,)).fetchone()
    if case is None:
        return
    n = int(case["submission_no"])
    by = getattr(actor, "id", None)
    if action == "CREATE":
        ensure_round(conn, case_id, 1, via="CREATE", by=by, at=entry["at"])
    elif action in ("ADD_DOCS", "REPLACE_DOC"):
        ensure_round(conn, case_id, n, via=action, by=by, at=entry["at"])
    elif action == "FORWARD":
        ensure_round(conn, case_id, n, via="ADD_DOCS", by=by, at=entry["at"])
        conn.execute("UPDATE case_rounds SET submitted_at = ?, submitted_by = ? "
                     "WHERE case_id = ? AND submission_no = ? AND closed_at IS NULL",
                     (entry["at"], by, case_id, n))
    if action in SEND_BACK:
        conn.execute(
            "INSERT INTO case_round_requests(id, case_id, from_submission_no, for_submission_no, event_id, "
            "action, items_json, remark, requested_by, requested_by_name, run_id, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (db.new_id(), case_id, n, n + 1, entry["id"], action,
             json.dumps(request_items(action, payload), ensure_ascii=False), entry.get("remark") or "",
             by, getattr(actor, "display_name", None) or ("System (AI verification)" if actor is None else None),
             entry.get("run_id"), entry["at"]))
    if action in CLOSING:
        ensure_round(conn, case_id, n, via="BACKFILL", by=None, at=entry["at"])
        conn.execute("UPDATE case_rounds SET closed_at = ?, closed_action = ? "
                     "WHERE case_id = ? AND submission_no = ? AND closed_at IS NULL",
                     (entry["at"], action, case_id, n))


def ensure_round(conn: sqlite3.Connection, case_id: str, n: int, *, via: str, by: str | None,
                 at: str | None = None) -> None:
    conn.execute("INSERT OR IGNORE INTO case_rounds(id, case_id, submission_no, opened_at, opened_by, opened_via) "
                 "VALUES (?, ?, ?, ?, ?, ?)", (db.new_id(), case_id, n, at or db.now(), by, via))


def request_items(action: str, payload: dict) -> list[dict]:
    """The items of a send-back, in one shape whoever sent it.

    The AG's own return names them (``items`` in the request body: checklist item ids, or a
    document and pages in the officer's words); the automatic return carries the checklist
    lines it found missing or defective.
    """
    out: list[dict] = []
    for it in payload.get("items") or []:
        if not isinstance(it, dict):
            continue
        if it.get("id"):
            out.append({"kind": "CHECKLIST", "id": str(it["id"]), "requirement": it.get("requirement") or "",
                        "status": it.get("status") or "", "note": str(it.get("note") or "")[:500]})
        elif it.get("label") or it.get("pages"):
            pages = sorted({int(p) for p in it.get("pages") or [] if str(p).isdigit()})
            out.append({"kind": "DOCUMENT", "label": str(it.get("label") or "")[:200], "pages": pages,
                        "note": str(it.get("note") or "")[:500]})
    if not out and action == "AUTO_RETURN" or (not out and payload.get("missing_checklist")):
        for m in payload.get("missing_checklist") or []:
            out.append({"kind": "CHECKLIST", "id": m.get("id"), "requirement": m.get("requirement") or "",
                        "status": m.get("status") or "MISSING", "note": ""})
    return out


# -- a verification in a round ------------------------------------------------------------------
def base_run_for(conn: sqlite3.Connection, case: sqlite3.Row) -> sqlite3.Row | None:
    """The earlier round's finished pension run a resubmission reuses, or None (a full run).

    Round 1 has none, a GP Fund case has none (its reading is the GP Fund module's), and a
    round whose earlier rounds never finished a check has none.
    """
    from api.case_runs import GPF_RUN_PREFIX
    from api.runs import ARTIFACTS
    if int(case["submission_no"]) <= 1:
        return None
    if (case["product"] if "product" in case.keys() else "PENSION") == "GPF":
        return None
    for row in conn.execute(
            "SELECT * FROM case_runs WHERE case_id = ? AND submission_no < ? AND state = 'done' "
            "ORDER BY submission_no DESC, finished_at DESC", (case["id"], case["submission_no"])):
        if row["run_id"].startswith(GPF_RUN_PREFIX):
            continue
        if (ARTIFACTS / f"run-{row['run_id']}" / "case_report.json").exists():
            return row
    return None


def gpf_base_run_for(conn: sqlite3.Connection, case: sqlite3.Row) -> sqlite3.Row | None:
    """A GP Fund resubmission's earlier finished examination. The reuse itself happens in the
    GP Fund module (its per-case page cache); this names the round it reuses, for the record."""
    from api.case_runs import GPF_RUN_PREFIX
    if int(case["submission_no"]) <= 1 or (case["product"] if "product" in case.keys() else "PENSION") != "GPF":
        return None
    return conn.execute(
        "SELECT * FROM case_runs WHERE case_id = ? AND submission_no < ? AND state = 'done' AND run_id LIKE ? "
        "ORDER BY submission_no DESC, finished_at DESC LIMIT 1",
        (case["id"], case["submission_no"], GPF_RUN_PREFIX + "%")).fetchone()


def check_finished_gpf(conn: sqlite3.Connection, run_row: sqlite3.Row, state: str, error: str | None,
                       issues: dict, job_view: dict | None) -> None:
    """Close the record of a GP Fund examination: pages read and reused, and the requested items."""
    row = conn.execute("SELECT * FROM case_round_checks WHERE case_id = ? AND run_id = ? AND finished_at IS NULL",
                       (run_row["case_id"], run_row["run_id"])).fetchone()
    if row is None:
        return
    result = (job_view or {}).get("result") or {}
    total = int(result.get("pagesTotal") or (job_view or {}).get("total") or 0)
    reused = list(result.get("reusedPages") or [])
    steps = {"mode": row["mode"], "pages_total": total, "pages_read": total - len(reused),
             "pages_reused": len(reused), "reused_pages": reused,
             "duration_s": (job_view or {}).get("elapsed"),
             "steps": {"read": {"run": total - len(reused), "reused": len(reused)},
                       "checks": {"run": "all", "note": "the case is assembled and every rule applied over all pages"}}}
    missing = {m.get("id") for m in issues.get("missing_checklist") or []}
    resolution = []
    for req in conn.execute("SELECT * FROM case_round_requests WHERE case_id = ? AND for_submission_no = ? ORDER BY at",
                            (row["case_id"], row["submission_no"])).fetchall():
        for it in json.loads(req["items_json"] or "[]"):
            res = ("STILL_MISSING" if it.get("id") in missing else "RESOLVED") if it.get("kind") == "CHECKLIST" \
                else "FOR_OFFICER"
            resolution.append({**it, "request_id": req["id"], "requested_at": req["at"], "action": req["action"],
                               "resolution": res})
    conn.execute("UPDATE case_round_checks SET finished_at = ?, state = ?, duration_s = ?, steps_json = ?, "
                 "resolution_json = ?, issues_json = ?, error = ? WHERE id = ? AND finished_at IS NULL",
                 (db.now(), state, steps["duration_s"], json.dumps(steps), json.dumps(resolution, ensure_ascii=False),
                  json.dumps(issues, ensure_ascii=False, default=str), error, row["id"]))


def check_started(conn: sqlite3.Connection, case: sqlite3.Row, run_id: str, *, mode: str,
                  base: sqlite3.Row | None, user: Any, documents: list[dict]) -> None:
    """Open the record of one verification run. A re-check of the same papers (same run id) in
    the same round that has not finished is the same record."""
    open_row = conn.execute("SELECT id FROM case_round_checks WHERE case_id = ? AND run_id = ? AND finished_at IS NULL",
                            (case["id"], run_id)).fetchone()
    if open_row:
        return
    ensure_round(conn, case["id"], int(case["submission_no"]), via="ADD_DOCS", by=None)
    conn.execute(
        "INSERT INTO case_round_checks(id, case_id, submission_no, run_id, mode, base_run_id, base_submission_no, "
        "started_by, started_at, state, documents_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?)",
        (db.new_id(), case["id"], case["submission_no"], run_id, mode,
         base["run_id"] if base is not None else None, base["submission_no"] if base is not None else None,
         getattr(user, "id", None), db.now(), json.dumps(_documents_of_round(conn, case), ensure_ascii=False)))


def _documents_of_round(conn: sqlite3.Connection, case: sqlite3.Row) -> list[dict]:
    n = int(case["submission_no"])
    rows = conn.execute("SELECT id, submission_no, seq, filename, sha256, replaces_document_id, superseded_in_submission "
                        "FROM case_documents WHERE case_id = ? ORDER BY submission_no, seq", (case["id"],)).fetchall()
    out = []
    for r in rows:
        if r["superseded_in_submission"] is not None and r["superseded_in_submission"] <= n:
            status = "SUPERSEDED"
        elif r["submission_no"] == n and n > 1:
            status = "REPLACEMENT" if r["replaces_document_id"] else "NEW"
        else:
            status = "EARLIER"
        out.append({"id": r["id"], "filename": r["filename"], "submission_no": r["submission_no"],
                    "sha256": r["sha256"], "status": status, "replaces": r["replaces_document_id"]})
    return out


def check_finished(conn: sqlite3.Connection, run_row: sqlite3.Row, state: str, error: str | None) -> dict | None:
    """Close the record of a finished run: steps, findings, requested items, changes. Idempotent.

    For an incremental run the officer's decisions on the earlier round -- clearances of
    findings that are unchanged, checklist waivers and pages named -- are carried into this
    run first, so the outcome and the gate see them. Returns the record, or None.
    """
    from pipeline import carryover
    from api.runs import ARTIFACTS, RUNS
    row = conn.execute("SELECT * FROM case_round_checks WHERE case_id = ? AND run_id = ? AND finished_at IS NULL",
                       (run_row["case_id"], run_row["run_id"])).fetchone()
    if row is None:
        return None
    run_dir = ARTIFACTS / f"run-{run_row['run_id']}"
    live = RUNS.get(run_row["run_id"])
    steps = carryover.summarise(run_dir, started_at=getattr(live, "started_at", None) or row["started_at"],
                                finished_at=getattr(live, "finished_at", None) or db.now())
    report = _report(run_dir) if state == "done" else None
    carried: dict = {}
    changes: dict = {}
    resolution: list[dict] = []
    if report is not None:
        carry = carryover.load(run_dir)
        base_dir = ARTIFACTS / f"run-{row['base_run_id']}" if row["base_run_id"] else None
        base_report = _report(base_dir) if base_dir else None
        if carry and base_dir and base_report:
            carried = carry_decisions(base_dir, run_dir, base_report, report, carry)
            changes = compare_findings(base_report, report, carry)
        from api.checklist_actions import apply
        resolution = resolve_requests(conn, row, apply(report, run_dir), carry)
    from api.case_runs import open_issues
    issues = open_issues(_applied(report, run_dir)) if report is not None else open_issues(None)
    duration = steps.get("duration_s")
    conn.execute(
        "UPDATE case_round_checks SET finished_at = ?, state = ?, duration_s = ?, steps_json = ?, findings_json = ?, "
        "resolution_json = ?, changes_json = ?, carried_json = ?, issues_json = ?, error = ? "
        "WHERE id = ? AND finished_at IS NULL",
        (db.now(), state, duration, json.dumps(steps, ensure_ascii=False, default=str),
         json.dumps(_finding_snapshot(report), ensure_ascii=False),
         json.dumps(resolution, ensure_ascii=False), json.dumps(changes, ensure_ascii=False),
         json.dumps(carried, ensure_ascii=False), json.dumps(issues, ensure_ascii=False, default=str),
         error, row["id"]))
    return {"steps": steps, "resolution": resolution, "changes": changes, "carried": carried}


def _report(run_dir: Path | None) -> dict | None:
    from api.artefacts import report_dict
    return report_dict(run_dir) if run_dir else None


def _applied(report: dict | None, run_dir: Path) -> dict | None:
    if report is None:
        return None
    from api.checklist_actions import apply
    return apply(report, run_dir)


def _finding_snapshot(report: dict | None) -> list[dict]:
    return [{"id": f.get("id"), "severity": f.get("severity"), "class": f.get("class"), "title": f.get("title"),
             "blocks_ppo": f.get("blocks_ppo"), "evidence": f.get("evidence")}
            for f in (report or {}).get("flags") or []]


# -- comparing a round with the one before ---------------------------------------------------
_PAGE_WORD = re.compile(r"\bpp?\.\s*\d+(?:\s*[-–]\s*\d+)?", re.I)


def finding_key(flag: dict, page_to_new: dict[int, int] | None = None) -> tuple:
    """What makes two findings the same finding across rounds: its class, its title without
    page numbers, and the pages it cites -- under the new round's numbering."""
    ev = flag.get("evidence") or {}

    def pages(side: str) -> tuple:
        out = []
        for e in ev.get(side) or []:
            p = e.get("page")
            if page_to_new is not None:
                p = page_to_new.get(p)
                if p is None:
                    return ("withdrawn",)
            out.append((e.get("doc"), p))
        return tuple(sorted(out, key=str))

    title = _PAGE_WORD.sub("p.#", str(flag.get("title") or "")).strip().lower()
    return (flag.get("class"), title, pages("asserted"), pages("contradicted_by"))


def compare_findings(base_report: dict, report: dict, carry: dict) -> dict:
    """New, cleared and unchanged findings against the earlier round."""
    from pipeline import carryover
    fwd = carryover.forward_map(carry)
    new_pages = set(carry.get("new_pages") or [])
    before = {finding_key(f, fwd): f for f in base_report.get("flags") or []}
    now = {finding_key(f): f for f in report.get("flags") or []}

    def brief(f: dict) -> dict:
        ev = f.get("evidence") or {}
        cited = sorted({e.get("page") for side in ("asserted", "contradicted_by") for e in ev.get(side) or []
                        if e.get("page") is not None})
        return {"id": f.get("id"), "severity": f.get("severity"), "class": f.get("class"),
                "title": f.get("title"), "pages": cited,
                "from_new_documents": bool(set(cited) & new_pages)}

    return {
        "new": [brief(f) for k, f in now.items() if k not in before],
        "cleared": [brief(f) for k, f in before.items() if k not in now],
        "unchanged": [brief(f) for k, f in now.items() if k in before],
    }


def carry_decisions(base_dir: Path, run_dir: Path, base_report: dict, report: dict, carry: dict) -> dict:
    """Carry the officer's decisions on the earlier round into this run. Idempotent.

    *   a disposition of a finding that is unchanged (``finding_key``) -- recorded again on this
        run under the new finding id, with the original officer, ground and date, marked carried;
    *   a checklist waiver, as it stood;
    *   a page the officer named, where that page is carried (under its new number).

    Nothing is carried for a finding that changed or is new, or for a page the department
    replaced: those are for the officer to look at afresh.
    """
    from api import checklist_actions, dispositions
    from pipeline import carryover
    fwd = carryover.forward_map(carry)
    base_run_id = carry.get("base_run_id")
    marker = run_dir / "carried_decisions.json"
    if marker.exists():
        try:
            return json.loads(marker.read_text())
        except ValueError:
            pass
    out = {"dispositions": [], "checklist": []}

    before = dispositions.current(base_dir)
    by_key = {finding_key(f, fwd): f for f in base_report.get("flags") or []}
    now_by_key = {finding_key(f): f for f in report.get("flags") or []}
    entries = []
    from rules.flags import finding_fingerprint
    for key, flag in now_by_key.items():
        old = by_key.get(key)
        d = before.get(old["id"]) if old else None
        if not d:
            continue
        # The exact finding, not merely one of the same class on the same pages (H8): a changed
        # figure, date or name is a new finding for the officer to decide afresh.
        if finding_fingerprint(old) != finding_fingerprint(flag):
            continue
        if d.get("fingerprint") and d["fingerprint"] != finding_fingerprint(old):
            continue
        entries.append({**{k: d.get(k) for k in ("action", "officer", "role", "ground")},
                        "run_id": run_dir.name.removeprefix("run-"), "flag_id": flag["id"],
                        "at": db.now(), "flag_severity": flag.get("severity"), "flag_class": flag.get("class"),
                        "flag_title": flag.get("title"), "flag_finding": flag.get("finding"),
                        "blocks_ppo": flag.get("blocks_ppo"), "fingerprint": finding_fingerprint(flag),
                        "carried_from": {"run_id": base_run_id, "flag_id": old["id"], "at": d.get("at")}})
        out["dispositions"].append({"flag_id": flag["id"], "from_flag_id": old["id"], "action": d.get("action"),
                                    "officer": d.get("officer")})
    if entries:
        with (run_dir / dispositions.DISPOSITIONS_LOG).open("a", encoding="utf-8") as fh:
            for e in entries:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")

    items_now = {i["id"] for i in (report.get("checklist") or {}).get("items") or []}
    rows = []
    for key, e in checklist_actions.current(base_dir).items():
        if e.get("item_id") and e["item_id"] not in items_now:
            continue
        pages = e.get("pages") or []
        if pages and any(p not in fwd for p in pages):
            continue                               # named on a page the department withdrew
        rows.append({**e, "pages": [fwd[p] for p in pages], "run_id": run_dir.name.removeprefix("run-"),
                     "at": db.now(), "carried_from": {"run_id": base_run_id, "at": e.get("at"),
                                                      "pages": pages}})
        out["checklist"].append({"action": e.get("action"), "item_id": e.get("item_id"),
                                 "pages": [fwd[p] for p in pages], "officer": e.get("officer")})
    if rows:
        with (run_dir / checklist_actions.LOG).open("a", encoding="utf-8") as fh:
            for e in rows:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    marker.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def resolve_requests(conn: sqlite3.Connection, check_row: sqlite3.Row, report: dict,
                     carry: dict | None) -> list[dict]:
    """How each item the AG asked this round for stands after its verification."""
    reqs = conn.execute("SELECT * FROM case_round_requests WHERE case_id = ? AND for_submission_no = ? ORDER BY at",
                        (check_row["case_id"], check_row["submission_no"])).fetchall()
    if not reqs:
        return []
    items = {i["id"]: i for i in (report.get("checklist") or {}).get("items") or []}
    new_pages = set((carry or {}).get("new_pages") or []) if carry else None
    out: list[dict] = []
    for req in reqs:
        for it in json.loads(req["items_json"] or "[]"):
            entry = {**it, "request_id": req["id"], "requested_at": req["at"], "action": req["action"]}
            if it.get("kind") == "CHECKLIST":
                now = items.get(it.get("id"))
                status = (now or {}).get("status")
                located = (now or {}).get("located") or (now or {}).get("pages") or []
                entry["now"] = status
                entry["located"] = located
                if now is None or status in ("NOT_APPLICABLE", "NOT_REQUIRED", "FOUND_NOT_REQUIRED"):
                    entry["resolution"] = "NO_LONGER_REQUIRED"
                elif status in ("PRESENT", "WAIVED"):
                    entry["resolution"] = "RESOLVED" if status == "PRESENT" else "WAIVED"
                    if new_pages is not None:
                        entry["on_new_pages"] = bool(set(located) & new_pages)
                elif status == "DEFECTIVE":
                    entry["resolution"] = "STILL_DEFECTIVE"
                else:
                    entry["resolution"] = "STILL_MISSING"
            else:
                entry["resolution"] = "FOR_OFFICER"      # named in the officer's words: the officer judges it
            out.append(entry)
    return out


# -- reading ---------------------------------------------------------------------------------
def history(conn: sqlite3.Connection, case_id: str, *, for_department: bool) -> list[dict]:
    """Every round of a case, oldest first. A department sees what was asked of it and what it
    sent; the findings and what the check did are the AG's (decision of 28 Sep 2026)."""
    rounds = conn.execute("SELECT * FROM case_rounds WHERE case_id = ? ORDER BY submission_no", (case_id,)).fetchall()
    docs = conn.execute("SELECT id, submission_no, seq, filename, bytes, uploaded_at, replaces_document_id, "
                        "superseded_in_submission FROM case_documents WHERE case_id = ? ORDER BY submission_no, seq",
                        (case_id,)).fetchall()
    out = []
    for r in rounds:
        n = r["submission_no"]
        reqs = conn.execute("SELECT * FROM case_round_requests WHERE case_id = ? AND for_submission_no = ? ORDER BY at",
                            (case_id, n)).fetchall()
        entry = {
            "submission_no": n, "opened_at": r["opened_at"], "opened_via": r["opened_via"],
            "submitted_at": r["submitted_at"], "closed_at": r["closed_at"], "closed_action": r["closed_action"],
            "requests": [{"action": q["action"], "items": json.loads(q["items_json"] or "[]"), "remark": q["remark"],
                          "by": q["requested_by_name"], "at": q["at"]} for q in reqs],
            "documents": [{"id": d["id"], "filename": d["filename"], "bytes": d["bytes"], "uploaded_at": d["uploaded_at"],
                           "replaces": d["replaces_document_id"],
                           "superseded_in_submission": d["superseded_in_submission"]}
                          for d in docs if d["submission_no"] == n],
        }
        if not for_department:
            checks = conn.execute("SELECT * FROM case_round_checks WHERE case_id = ? AND submission_no = ? "
                                  "ORDER BY started_at", (case_id, n)).fetchall()
            entry["checks"] = [{
                "run_id": c["run_id"], "mode": c["mode"], "base_run_id": c["base_run_id"],
                "base_submission_no": c["base_submission_no"], "started_at": c["started_at"],
                "finished_at": c["finished_at"], "state": c["state"], "duration_s": c["duration_s"],
                "documents": json.loads(c["documents_json"] or "[]"), "steps": json.loads(c["steps_json"] or "{}"),
                "findings": json.loads(c["findings_json"] or "[]"),
                "resolution": json.loads(c["resolution_json"] or "[]"),
                "changes": json.loads(c["changes_json"] or "{}"), "carried": json.loads(c["carried_json"] or "{}"),
                "error": c["error"]} for c in checks]
        else:
            # Only the department's side of it: whether what was asked for is now on file.
            last = conn.execute("SELECT resolution_json FROM case_round_checks WHERE case_id = ? AND submission_no = ? "
                                "AND finished_at IS NOT NULL ORDER BY started_at DESC LIMIT 1", (case_id, n)).fetchone()
            entry["requested_items"] = [{"id": x.get("id"), "label": x.get("label") or x.get("requirement"),
                                         "on_file": x.get("resolution") in ("RESOLVED", "WAIVED", "NO_LONGER_REQUIRED")}
                                        for x in json.loads(last["resolution_json"] or "[]")] if last else []
        out.append(entry)
    return out


# -- existing cases ----------------------------------------------------------------------------
def backfill(conn: sqlite3.Connection) -> int:
    """Round records for cases that predate them, from their history and runs. Idempotent.

    Only inserts: a round, request or check already recorded is left alone, and nothing in the
    existing tables is changed. Every backfilled check is a FULL run, which is what it was.
    """
    from api.case_runs import open_issues
    from api.runs import ARTIFACTS
    added = 0
    with db.transaction(conn):
        for case in conn.execute("SELECT id, submission_no, created_at, created_by FROM cases").fetchall():
            cid = case["id"]
            events = conn.execute("SELECT * FROM case_events WHERE case_id = ? ORDER BY seq", (cid,)).fetchall()
            have_rounds = {r[0] for r in conn.execute("SELECT submission_no FROM case_rounds WHERE case_id = ?", (cid,))}
            have_reqs = {r[0] for r in conn.execute("SELECT event_id FROM case_round_requests WHERE case_id = ?", (cid,))}
            n = 1
            state: dict[int, dict] = {1: {"opened_at": case["created_at"], "opened_by": case["created_by"],
                                          "via": "BACKFILL"}}
            for e in events:
                payload = json.loads(e["payload_json"] or "{}")
                if e["action"] == "ADD_DOCS" and payload.get("submission_no"):
                    k = int(payload["submission_no"])
                    if k > n:
                        n = k
                        state.setdefault(n, {"opened_at": e["at"], "opened_by": e["actor_id"], "via": "BACKFILL"})
                elif e["action"] == "FORWARD":
                    state.setdefault(n, {"opened_at": e["at"], "opened_by": e["actor_id"], "via": "BACKFILL"})
                    state[n].setdefault("submitted_at", e["at"])
                    state[n]["submitted_by"] = e["actor_id"]
                if e["action"] in SEND_BACK and e["id"] not in have_reqs:
                    conn.execute(
                        "INSERT INTO case_round_requests(id, case_id, from_submission_no, for_submission_no, event_id, "
                        "action, items_json, remark, requested_by, requested_by_name, run_id, at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (db.new_id(), cid, n, n + 1, e["id"], e["action"],
                         json.dumps(request_items(e["action"], payload), ensure_ascii=False), e["remark"],
                         e["actor_id"], e["actor_name"] or "System (AI verification)", e["run_id"], e["at"]))
                    added += 1
                if e["action"] in CLOSING:
                    state.setdefault(n, {"opened_at": e["at"], "opened_by": None, "via": "BACKFILL"})
                    state[n].setdefault("closed_at", e["at"])
                    state[n].setdefault("closed_action", e["action"])
            n = max(n, int(case["submission_no"]))
            for k in range(1, n + 1):
                if k in have_rounds:
                    continue
                s = state.get(k, {"opened_at": case["created_at"], "opened_by": None, "via": "BACKFILL"})
                # A round the case is still in is not closed, even if an earlier send-back is on it.
                closed = s.get("closed_at") if k < int(case["submission_no"]) or s.get("closed_action") in (
                    "APPROVE", "REJECT", "AUTO_APPROVE") else None
                conn.execute(
                    "INSERT INTO case_rounds(id, case_id, submission_no, opened_at, opened_by, opened_via, "
                    "submitted_at, submitted_by, closed_at, closed_action) VALUES (?, ?, ?, ?, ?, 'BACKFILL', ?, ?, ?, ?)",
                    (db.new_id(), cid, k, s["opened_at"], s.get("opened_by"), s.get("submitted_at"),
                     s.get("submitted_by"), closed, s.get("closed_action") if closed else None))
                added += 1
            have_checks = {r[0] for r in conn.execute("SELECT run_id FROM case_round_checks WHERE case_id = ?", (cid,))}
            for run in conn.execute("SELECT * FROM case_runs WHERE case_id = ? ORDER BY started_at", (cid,)).fetchall():
                if run["run_id"] in have_checks:
                    continue
                finished = run["finished_at"] if run["state"] in ("done", "failed") else None
                rep = _report(ARTIFACTS / f"run-{run['run_id']}") if run["state"] == "done" else None
                conn.execute(
                    "INSERT INTO case_round_checks(id, case_id, submission_no, run_id, mode, started_by, started_at, "
                    "finished_at, state, findings_json, issues_json, steps_json) "
                    "VALUES (?, ?, ?, ?, 'FULL', ?, ?, ?, ?, ?, ?, ?)",
                    (db.new_id(), cid, run["submission_no"], run["run_id"], run["started_by"], run["started_at"],
                     finished, run["state"] if finished else "running", json.dumps(_finding_snapshot(rep)),
                     json.dumps(open_issues(rep), default=str) if finished else "{}",
                     json.dumps({"mode": "FULL", "backfilled": True})))
                added += 1
    return added
