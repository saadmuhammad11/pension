"""A case's AI check: bundle its documents, run the pipeline, and read the outcome back.

The pipeline is untouched. A check is one ``api.runs.start_run`` call over a zip of the case's
current documents, namespaced by the case id so two departments' identical papers are two
runs. The pipeline thread writes its artefacts as it always has and never touches the
database; :func:`sync_run_states` -- called on a timer and on every case read -- notices a run
that has finished, copies the handful of figures the queue needs into ``case_runs`` and moves
the case on by the outcome (decision of 28 Sep 2026, narrowed 7 Oct 2026): documents missing ->
returned to the department with the list; otherwise -> under review at the AG. Nothing is
approved by the system: a clean verification, the officer's last clearance and a GP Fund
examination that passed all wait for an officer's own decision (business decision M1, 7 Oct
2026). :func:`settle` only records that nothing is left outstanding.
"""
from __future__ import annotations

import io
import os
import json
from datetime import datetime
import threading
import time
import zipfile
from pathlib import Path

from api import db, gpf_bridge, rounds, workflow
from api.artefacts import report_dict
from api.runs import RUNS, adopt_from_disk, disk_shortfall, past_deadline, prune_registry, start_run, sweep_disk

#: A GP Fund examination is a reading job of the GP Fund module, not a pipeline run; its id on
#: case_runs carries this prefix so the reconciler knows whom to ask.
GPF_RUN_PREFIX = "gpf-"

#: Where a case's uploaded documents live: artifacts/cases/<case_id>/s<submission>/<seq>-<name>.
#: Deliberately not under artifacts/uploads/, which adopt_from_disk globs for run files.
CASE_FILES = db.ROOT / "artifacts" / "cases"


def document_dir(case_id: str, submission_no: int) -> Path:
    return CASE_FILES / case_id / f"s{submission_no}"


def bundle_bytes(conn: db.Connection, case_id: str) -> tuple[bytes, list[dict]]:
    """A zip of every document on the case, in upload order, with fixed timestamps.

    Fixed timestamps and names make the bytes a function of the content alone, so re-checking
    an unchanged set of papers produces the same run id and resumes from its artefacts rather
    than spending the GPU again (api.runs.start_run). ``pipeline.bundle`` sorts members
    naturally, so the ``NN-`` prefix keeps the officer's order.
    """
    # A document the department replaced stays on file but is no longer part of the case
    # (api.v2 replace_document). Every document filed before 30 Sep 2026 has the column NULL,
    # so an existing case bundles byte for byte as it did.
    rows = conn.execute(
        "SELECT * FROM case_documents WHERE case_id = ? AND superseded_in_submission IS NULL "
        "ORDER BY submission_no, seq", (case_id,)
    ).fetchall()
    if not rows:
        raise workflow.WorkflowError(422, "the case has no documents to check")
    missing = [r["filename"] for r in rows if not Path(r["stored_path"]).is_file()]
    if missing:
        raise workflow.WorkflowError(410, f"these documents are no longer on the server: {', '.join(missing)}; "
                                          "attach them again")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for i, row in enumerate(rows, start=1):
            data = Path(row["stored_path"]).read_bytes()
            info = zipfile.ZipInfo(f"{i:02d}-{row['filename']}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            zf.writestr(info, data)
    return buf.getvalue(), [dict(r) for r in rows]


def documents_sha(conn: db.Connection, case_id: str) -> str:
    """One hash for the set of documents on the case now (their sha256s, in order)."""
    import hashlib
    rows = conn.execute("SELECT sha256 FROM case_documents WHERE case_id = ? AND superseded_in_submission IS NULL "
                        "ORDER BY submission_no, seq", (case_id,)).fetchall()
    return hashlib.sha256("\n".join(r["sha256"] or "" for r in rows).encode()).hexdigest()


#: Cases whose verification this process is starting now: between RUN_CHECK (status AI_CHECKING,
#: no current run) and the run row. The sweep leaves them alone however long the start takes -- a
#: GP Fund start renders and uploads every page first -- and, after a restart, when this set is
#: empty, fails a start that died only after its grace period (audit 6 Oct 2026).
_STARTING: set[str] = set()
_STARTING_LOCK = threading.Lock()


def _is_starting(case_id: str) -> bool:
    with _STARTING_LOCK:
        return case_id in _STARTING


def start_check(conn: db.Connection, case: db.Row, user) -> dict:
    """Start (or resume) the verification of a case; see ``_start_check``."""
    with _STARTING_LOCK:
        _STARTING.add(case["id"])
    try:
        return _start_check(conn, case, user)
    finally:
        with _STARTING_LOCK:
            _STARTING.discard(case["id"])


def _start_check(conn: db.Connection, case: db.Row, user) -> dict:
    """Start (or resume) the verification over the case's documents; record the run on the case.

    A pension case goes to the pension pipeline; a GP Fund case to the GP Fund module's reader
    (api.gpf_bridge). The case is moved to AI_CHECKING first, conditionally on its current
    status, so two clicks at once start one run; only then is the work started. If starting
    fails the case is moved to AI_FAILED with the reason, never left in AI_CHECKING with nothing
    running.
    """
    from api import rounds
    short = disk_shortfall()
    if short:
        raise workflow.WorkflowError(507, short)           # before the case is moved (audit 6 Oct 2026, R8)
    body, docs = bundle_bytes(conn, case["id"])
    intake = json.loads(case["intake_json"] or "{}")
    # A resubmission reuses the earlier round's reading of every paper it has not changed
    # (pipeline.carryover). Round 1, and a GP Fund case, have no base: a full run, as ever.
    base = rounds.base_run_for(conn, case) or rounds.gpf_base_run_for(conn, case)
    workflow.transition(conn, case, "RUN_CHECK", user,
                        payload={"documents": len(docs),
                                 **({"base_run_id": base["run_id"]} if base is not None else {})})
    try:
        if (case["product"] if "product" in case.keys() else "PENSION") == "GPF":
            started = _start_gpf(case, docs, intake, user)
        else:
            started = _start(case, body, docs, intake, user,
                             base_run_id=base["run_id"] if base is not None else None)
        run_id = started["run_id"]
        mode = "INCREMENTAL" if base is not None and base["run_id"] != run_id else "FULL"
        with db.transaction(conn):
            # The pipeline resumes an unchanged bundle under the same run id, so a re-run after a
            # failure is the SAME row, started afresh -- never a second row that a sweep could
            # mistake for the old failed one.
            existing = conn.execute("SELECT id FROM case_runs WHERE case_id = ? AND run_id = ?",
                                    (case["id"], run_id)).fetchone()
            # db.stamp(), not db.now(): started_at is what orders a case's runs, and at second
            # precision two of them routinely share one. The id beside it in the ORDER BY is a
            # uuid4 and breaks a tie arbitrarily -- deterministically, but arbitrarily -- so a
            # resubmission verified in the same second as the one before it could show the
            # previous run as the latest (audit of 13 Oct 2026, H-08). A microsecond stamp sorts
            # after a second-precision one of the same second as text, so the rows already in
            # the table stay in their right places.
            if existing:
                conn.execute(
                    "UPDATE case_runs SET submission_no = ?, started_by = ?, started_at = ?, finished_at = NULL, "
                    "state = ?, verdict = NULL, high_flags = NULL, blocking_flags_json = NULL, checklist_result = NULL, "
                    "error = NULL, docs_sha = ?, mode = ?, base_run_id = ? WHERE id = ?",
                    (case["submission_no"], user.id, db.stamp(), started.get("state", "queued"),
                     documents_sha(conn, case["id"]), mode,
                     base["run_id"] if mode == "INCREMENTAL" else None, existing["id"]))
            else:
                conn.execute(
                    "INSERT INTO case_runs(id, case_id, run_id, submission_no, started_by, started_at, "
                    "state, auto_forward, docs_sha, mode, base_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                    (db.new_id(), case["id"], run_id, case["submission_no"], user.id, db.stamp(),
                     started.get("state", "queued"), documents_sha(conn, case["id"]), mode,
                     base["run_id"] if mode == "INCREMENTAL" else None))
            rounds.check_started(conn, case, run_id, mode=mode,
                                 base=base if mode == "INCREMENTAL" else None, user=user, documents=docs)
            conn.execute("UPDATE cases SET current_run_id = ?, updated_at = ? WHERE id = ?",
                         (run_id, db.now(), case["id"]))
    except Exception as exc:                                       # noqa: BLE001
        # Whether the pipeline refused or the run row could not be written (a locked database),
        # the case must not stay in AI_CHECKING with nothing behind it.
        fresh = conn.execute("SELECT * FROM cases WHERE id = ?", (case["id"],)).fetchone()
        try:
            workflow.transition(conn, fresh, "CHECK_FAILED", None, remark=f"the verification could not start: {exc}")
        except workflow.WorkflowError:
            pass
        raise workflow.WorkflowError(502, f"the AI verification could not be started: {exc}") from exc
    return {"run_id": run_id, "resumed": bool(started.get("resumed")), "documents": len(docs)}


def _start_gpf(case, docs: list, intake: dict, user) -> dict:
    """Hand the department's pages to the GP Fund module; its reading job is our run."""
    # The department's specimen signature sheet travels with the claim but is not read as a page
    # of it; it goes to the module as the specimen the officer compares signatures against.
    files = [Path(d["stored_path"]) for d in docs if not gpf_bridge.is_specimen(d["filename"])]
    specimens = [Path(d["stored_path"]) for d in docs if gpf_bridge.is_specimen(d["filename"])]
    if not files:
        raise workflow.WorkflowError(422, "only a specimen signature is attached; attach the claim's papers too")
    try:
        job = gpf_bridge.start_examination(
            files, specimens=specimens,
            kind=str(intake.get("gpf_kind") or "final"), gazetted=str(intake.get("gazetted") or "unknown"),
            officer=gpf_bridge.OFFICER_FOR_ROLE.get(getattr(user, "role", ""), "ao"),
            work_dir=gpf_bridge.scratch_dir(case["id"], case["submission_no"]),
            # Every round of the case under one scope: a resubmission reads only its new pages.
            # Sent only while carryover is switched on (rounds.carryover_allowed). Off by the
            # office's decision of 23 Oct 2026 -- every verify reads every page of the bundle
            # again -- which until now was honoured on the pension side alone: base_run_for
            # passes a GP Fund case by, because its reading is the module's and not the
            # pipeline's, so the same decision has to be made here. Without a scope the module
            # reads every page, as it always did (gpf.api._read_scans).
            #
            # What it cost while it was on: re-examining a bundle whose pages were all in the
            # cache finished in half a second without looking at one of them, so a fix to the
            # reader never reached a case already read -- and the officer, told the examination
            # takes ten to twenty minutes, saw no progress window at all (23 Oct 2026).
            reuse_scope=(f"portal-case-{case['id']}" if rounds.carryover_allowed() else ""),
            # ...and re-read into the module case this portal case already holds, so the
            # officer's dispositions carry into the new round instead of being abandoned with
            # an examination the portal then stops pointing at (H-19).
            # .keys(), like the product check above: the row reaching here is not always a
            # full SELECT *, and indexing a column that is not on it would raise on EVERY GP
            # Fund submission rather than only on a resubmission. Absent means "no module case
            # yet", which is exactly a first submission.
            into_case=str((case["gpf_case_id"] if "gpf_case_id" in case.keys() else None) or ""))
    except gpf_bridge.GpfError as exc:
        raise workflow.WorkflowError(exc.status, exc.detail) from exc
    return {"run_id": GPF_RUN_PREFIX + str(job["jobId"]), "resumed": False, "state": "queued" if job.get("state") == "queued" else "running"}


def _start(case, body: bytes, docs: list, intake: dict, user, base_run_id: str | None = None) -> dict:
    return start_run(
        body, f"{case['case_no']}-s{case['submission_no']}.zip",
        variant=case["variant"] or None,
        # Only a declaration (or the AG's correction) steers the run; a type that was itself
        # detected by an earlier run is not fed back as if the department had said it.
        case_type=(case["case_type"] if case["case_type_source"] in ("DECLARED", "CORRECTED") else None),
        annual_pay=intake.get("annual_pay") or {},
        commutation_percent=intake.get("commutation_percent") or "",
        retirement_date=intake.get("retirement_date") or "",
        pension_in_payment=intake.get("pension_in_payment") or "",
        date_of_death=intake.get("date_of_death") or "",
        source={"kind": "portal_v2", "case_id": case["id"], "case_no": case["case_no"],
                "department": case["department_code"], "submission_no": case["submission_no"],
                "documents": len(docs), "user": getattr(user, "username", ""),
                "desk": "AD_SUBMITTER"},
        namespace=case["id"],
        base_run_id=base_run_id,
    )


def open_issues(report: dict | None) -> dict:
    """What the verification found, in the shape the screens show and the history keeps.

    Taken from the report as it stood when the run finished, so a later re-run cannot quietly
    change what the case was moved on.
    """
    if not report:
        return {"verdict": None, "blocking_flags": [], "high_flags": [], "flags_total": 0,
                "missing_checklist": [], "checklist_result": None, "checklist_present": False,
                "unidentified_pages": 0, "has_issues": True}
    rec = report.get("recommendation") or {}
    checklist = report.get("checklist") or {}
    flags = report.get("flags") or []
    blocking = list(rec.get("blocking_flags") or [])
    high = [{"id": f.get("id"), "title": f.get("title"), "class": f.get("class")}
            for f in flags if f.get("severity") == "HIGH"]
    missing = [{"id": i.get("id"), "requirement": i.get("requirement"), "status": i.get("status")}
               for i in checklist.get("items") or [] if i.get("status") in ("MISSING", "DEFECTIVE")]
    verdict = rec.get("verdict")
    unidentified = report.get("nameable_pages")
    if unidentified is None:
        unidentified = report.get("pages_unaccounted") or []
    ct = report.get("case_type") or {}
    detected = report.get("case_type_detected") or ct
    return {
        "case_type": ct.get("case_type"), "case_type_source": ct.get("source") or "detected",
        "detected_case_type": detected.get("case_type"),
        "detected_case_type_confidence": detected.get("case_type_confidence"),
        "detected_case_variant": report.get("case_variant") if report.get("case_variant_source") == "detected" else None,
        "verdict": verdict, "blocking_flags": blocking, "high_flags": high, "flags_total": len(flags),
        "missing_checklist": missing, "checklist_result": checklist.get("result"),
        "checklist_present": bool(checklist),
        "unidentified_pages": len(unidentified),
        "claimant_name": report.get("claimant_name"),
        "has_issues": bool(blocking or high or missing or (verdict and verdict != "FORWARD")),
    }


def outcome(issues: dict) -> str:
    """Where a finished verification sends the case: to the Accountant General, always.

    CHECK_DONE (UNDER_REVIEW): the AG reads the findings and the list of missing or defective
    documents and decides -- approve, reject, return, or ask for papers. Nothing is approved and
    nothing is returned by the system (business decisions M1 of 7 Oct 2026 and of 9 Oct 2026: no
    automatic return in pension or GP Fund; until then a case with documents missing was
    AUTO_RETURNed to the department with the list).
    """
    return "CHECK_DONE"


def nothing_outstanding(issues: dict) -> bool:
    """Every required document present, a checklist applied and no finding: the shape that used
    to approve a case by itself. Said in the history now, decided by an officer."""
    return bool(not issues["missing_checklist"] and not issues["flags_total"] and issues["checklist_present"])


def mirror_decision(run_id: str, action: str, officer: str, role: str, remark: str) -> None:
    """Keep the old register (api.cases) in agreement with what was decided on the case."""
    try:
        from api.artefacts import report_dict
        from api.checklist_actions import apply
        from api.decisions import record_decision
        from api.runs import ARTIFACTS
        run_dir = ARTIFACTS / f"run-{run_id}"
        rep = report_dict(run_dir)
        if rep is None:
            return
        record_decision(run_dir, run_id=run_id, action=action, officer=officer, role=role,
                        justification=remark, report=apply(rep, run_dir))
    except Exception:                                  # noqa: BLE001 -- the case record is authoritative
        pass


def settle(conn: db.Connection, case: db.Row, run_id: str, gate: dict, officer: str,
           by=None) -> dict | None:
    """Record that nothing is left outstanding on a case under review; move nothing.

    Called after every disposition and checklist action with the gate those computed. Until
    7 Oct 2026 an open gate approved the case by itself (AUTO_APPROVE); business decision M1
    removed every automatic approval, so the officer who cleared the last finding now also
    decides the case, by hand, with a remark. What is kept is the audit row: the account whose
    clearance completed the review and the gate it opened, so the trail still shows the moment
    the review was complete. Returns None always (nothing moved).
    """
    if case["status"] != workflow.UNDER_REVIEW or case["current_run_id"] != run_id or not gate.get("open"):
        return None
    if by is not None:
        workflow.audit(conn, actor=by, action="CLEARANCE_COMPLETE", entity_type="case",
                       entity_id=case["id"], before=None,
                       after={"run_id": run_id, "gate": gate},
                       reason=(f"Every finding cleared by {officer} and every required document present "
                               f"({gate.get('flags_cleared', 0)} finding(s) cleared). The case awaits a decision."))
    return None


#: How long a GP Fund reading may go unconfirmed (module down, slow, restarting) before it is
#: failed. Until then a poll that gets no answer is not an answer (audit 6 Oct 2026).
GPF_JOB_DEADLINE_MIN = int(os.environ.get("PENSION_GPF_JOB_DEADLINE_MIN", "120") or 120)


def _gpf_job_state(run_id: str, started_at: str | None = None) -> tuple[str, str | None, dict | None]:
    """(state, error, view) of a GP Fund reading job.

    Failed only on an answer: the module says the job failed, or no longer knows it (404 -- it
    keeps jobs fifteen minutes, and forgets them on a restart). A poll that gets no answer -- the
    module busy past the 10 s timeout, restarting, briefly down -- used to fail the examination
    for good while the module went on reading, and the case it then opened was never linked. Now
    that is "still running", until GPF_JOB_DEADLINE_MIN after ``started_at``.
    """
    try:
        view = gpf_bridge.job(run_id[len(GPF_RUN_PREFIX):])
    except gpf_bridge.GpfError as exc:
        if exc.status == 404:
            return "failed", exc.detail, None
        age_min = None
        if started_at:
            try:
                age_min = (datetime.now() - datetime.fromisoformat(started_at)).total_seconds() / 60
            except ValueError:
                age_min = None
        if age_min is not None and age_min > GPF_JOB_DEADLINE_MIN:
            return "failed", (f"the GP Fund module has not confirmed the reading for {int(age_min)} minutes: "
                              f"{exc.detail}"), None
        return "running", None, None
    state = view.get("state")
    if state == "error":
        return "failed", view.get("detail") or "the GP Fund module could not read the pages", view
    if state == "done":
        return "done", None, view
    return ("queued" if state == "queued" else "running"), None, view


def gpf_issues_for_case(gpf_case_id: str) -> dict:
    """The module's current view of its case, in the shape the case system moves cases by."""
    return gpf_bridge.issues(gpf_bridge.case(gpf_case_id))


def referenced_run_ids(conn: db.Connection) -> set[str]:
    """Every run id a case has ever been verified under: never swept from disk."""
    return {r["run_id"] for r in conn.execute("SELECT run_id FROM case_runs")}


def _run_state(run_id: str) -> tuple[str, str | None]:
    """(state, error) for a run: live if it is in this process, else from its artefacts."""
    if run_id.startswith(GPF_RUN_PREFIX):
        state, error, _ = _gpf_job_state(run_id)
        return state, error
    live = RUNS.get(run_id)
    if live is not None:
        if past_deadline(live):
            # The run's own thread stops at its next stage boundary (api.runs.Run.emit); the case
            # is not left in "AI verification in progress" until then (audit 6 Oct 2026, R7).
            return "failed", f"the run exceeded its deadline (started {live.started_at}); verify the case again"
        return live.state, live.error
    adopted = adopt_from_disk(run_id)
    if adopted is not None:
        return adopted.state, adopted.error
    from api.runs import ARTIFACTS
    if (ARTIFACTS / f"run-{run_id}" / "manifest.json").exists():
        return "failed", "the run stopped before it produced a report (the API was restarted)"
    return "failed", "the run left no artefacts"


def record_detected_case_type(conn: db.Connection, case_id: str, issues: dict) -> None:
    """What the verification read the case as, on the case. A case nobody declared a type for
    (filed before 29 Sep 2026, or imported) takes the detected type as its own, marked DETECTED;
    a declared or corrected type is never overwritten by the machine."""
    from rules.case_type import office_type_for
    detected = issues.get("detected_case_type")
    conn.execute("UPDATE cases SET detected_case_type = ?, detected_case_type_confidence = ? WHERE id = ?",
                 (detected, issues.get("detected_case_type_confidence"), case_id))
    office = office_type_for(detected, issues.get("detected_case_variant"))
    if office:
        conn.execute("UPDATE cases SET case_type = ?, case_type_source = 'DETECTED', variant = COALESCE(variant, ?) "
                     "WHERE id = ? AND (case_type IS NULL OR case_type_source = 'DETECTED')",
                     (office, office, case_id))


def backfill_case_types(conn: db.Connection | None = None) -> int:
    """Cases filed before the case type existed: take the AI's reading from their last report.
    Idempotent; run at start-up."""
    from api.runs import ARTIFACTS
    from rules.case_type import OFFICE_CASE_TYPES, office_type_for
    own = conn is None
    conn = conn or db.connect()
    try:
        n = 0
        # Cases typed before the office's own types became the list (29 Sep 2026): a pipeline
        # path on the case is mapped onto the office column it stands for.
        marks = ",".join("?" * len(OFFICE_CASE_TYPES))
        for row in conn.execute(f"SELECT id, case_type, variant FROM cases WHERE case_type IS NOT NULL "
                                f"AND case_type NOT IN ({marks})", OFFICE_CASE_TYPES).fetchall():
            office = office_type_for(row["case_type"], row["variant"])
            with db.transaction(conn):
                conn.execute("UPDATE cases SET case_type = ?, variant = COALESCE(variant, ?) WHERE id = ?",
                             (office, office, row["id"]))
            n += 1
        rows = conn.execute(
            "SELECT id, current_run_id FROM cases WHERE product = 'PENSION' AND case_type IS NULL "
            "AND current_run_id IS NOT NULL").fetchall()
        for row in rows:
            rep = report_dict(ARTIFACTS / f"run-{row['current_run_id']}")
            if not rep:
                continue
            issues = open_issues(rep)
            if not office_type_for(issues.get("detected_case_type"), issues.get("detected_case_variant")):
                continue
            with db.transaction(conn):
                record_detected_case_type(conn, row["id"], issues)
            n += 1
        return n
    finally:
        if own:
            conn.close()


#: How often the request paths may sync. Every case read and the 3-second poll of every open
#: browser called sync_run_states, and a sync with a GP Fund examination pending asks the module
#: (up to 10 s), so 88 browsers could tie the API up in GP Fund calls (audit 6 Oct 2026, later
#: report item 8). Within this many seconds of the last sync a request-path call does nothing;
#: the reconciler's own timer always syncs.
SYNC_MIN_INTERVAL_S = float(os.environ.get("PENSION_SYNC_MIN_INTERVAL_S", "1.0") or 1.0)
_LAST_SYNC = 0.0
_SYNC_LOCK = threading.Lock()


def sync_run_states(conn: db.Connection, *, force: bool = False) -> int:
    """Bring ``case_runs`` up to date with the pipeline and move cases on. Idempotent.

    Returns the number of runs whose row changed. Safe to call from a timer and from every
    case read at once: each finish is applied under ``UPDATE ... WHERE state IN (queued,
    running)``, so two callers cannot both record it. Request-path calls are rate-limited
    (SYNC_MIN_INTERVAL_S); ``force`` is the reconciler's.
    """
    global _LAST_SYNC
    with _SYNC_LOCK:
        now = time.monotonic()
        if not force and SYNC_MIN_INTERVAL_S > 0 and now - _LAST_SYNC < SYNC_MIN_INTERVAL_S:
            return 0
        _LAST_SYNC = now
    from api.runs import ARTIFACTS
    pending = conn.execute(
        "SELECT cr.*, c.status AS case_status FROM case_runs cr JOIN cases c ON c.id = cr.case_id "
        "WHERE cr.state IN ('queued', 'running')").fetchall()
    changed = 0
    for row in pending:
        gpf_view = None
        if row["run_id"].startswith(GPF_RUN_PREFIX):
            state, error, gpf_view = _gpf_job_state(row["run_id"], row["started_at"])
        else:
            state, error = _run_state(row["run_id"])
        if state in ("queued", "running"):
            if state != row["state"]:
                conn.execute("UPDATE case_runs SET state = ? WHERE id = ? AND state IN ('queued','running')",
                             (state, row["id"]))
            continue
        rep = None
        if gpf_view is not None and state == "done":
            # The module opened its case: remember its id, and read the position it found.
            gpf_case_id = ((gpf_view.get("result") or {}).get("id"))
            try:
                issues = gpf_issues_for_case(gpf_case_id) if gpf_case_id else open_issues(None)
            except gpf_bridge.GpfError as exc:
                state, error, issues = "failed", exc.detail, open_issues(None)
            if gpf_case_id:
                conn.execute("UPDATE cases SET gpf_case_id = ? WHERE id = ?", (gpf_case_id, row["case_id"]))
            try:
                rounds.check_finished_gpf(conn, row, state, error, issues, gpf_view)
            except Exception:                         # noqa: BLE001 -- the record never blocks the outcome
                import logging
                logging.getLogger(__name__).exception("round record failed for run %s", row["run_id"])
        else:
            rep = report_dict(ARTIFACTS / f"run-{row['run_id']}") if state == "done" else None
            # The round's record of this run (api.rounds). For a resubmission this first carries
            # the officer's decisions on the earlier round into the run -- clearances of findings
            # that are unchanged, checklist waivers, pages named -- so the outcome below sees
            # them, as it would have seen them had the officer made them on this run.
            finished = None
            try:
                finished = rounds.check_finished(conn, row, state, error)
            except Exception:                         # noqa: BLE001 -- the record never blocks the outcome
                import logging
                logging.getLogger(__name__).exception("round record failed for run %s", row["run_id"])
            if rep is not None and (row["mode"] if "mode" in row.keys() else "FULL") == "INCREMENTAL":
                from api.checklist_actions import apply
                rep = apply(rep, ARTIFACTS / f"run-{row['run_id']}")
            issues = open_issues(rep)
        try:
            with db.transaction(conn):
                cur = conn.execute(
                    "UPDATE case_runs SET state = ?, finished_at = ?, verdict = ?, high_flags = ?, "
                    "blocking_flags_json = ?, checklist_result = ?, error = ? "
                    "WHERE id = ? AND state IN ('queued', 'running')",
                    (state, db.now(), issues["verdict"], len(issues["high_flags"]),
                     json.dumps(issues["blocking_flags"]), issues["checklist_result"], error, row["id"]))
                if cur.rowcount != 1:
                    continue                      # somebody else recorded it first
                if rep and rep.get("claimant_name"):
                    conn.execute("UPDATE cases SET claimant_name = COALESCE(claimant_name, ?) WHERE id = ?",
                                 (rep.get("claimant_name"), row["case_id"]))
                if rep:
                    record_detected_case_type(conn, row["case_id"], issues)
        except db.OperationalError:
            continue                              # the database was busy; the next sweep records it
        changed += 1
        _move_case_on(conn, row["case_id"], row["run_id"], state, issues, error)
    # A case left in AI_CHECKING whose run has already been recorded as finished (a crash or a
    # busy database between the two steps above) is moved on here, so nothing stays stuck.
    for case in conn.execute(
            "SELECT c.*, cr.state AS run_state, cr.error AS run_error FROM cases c "
            "LEFT JOIN case_runs cr ON cr.id = (SELECT x.id FROM case_runs x WHERE x.case_id = c.id "
            "AND x.run_id = c.current_run_id ORDER BY x.started_at DESC, x.id DESC LIMIT 1) "
            "WHERE c.status = ? AND (cr.id IS NULL OR cr.state IN ('done', 'failed'))",
            (workflow.AI_CHECKING,)).fetchall():
        if case["run_state"] is None:
            # No run row at all: the start failed after the status moved. Not while this process
            # is still starting it, and otherwise only after a grace period.
            if _is_starting(case["id"]):
                continue
            try:
                age = (datetime.fromisoformat(db.now()) - datetime.fromisoformat(case["updated_at"])).total_seconds()
            except ValueError:
                age = 0
            if age < 120:
                continue
            _move_case_on(conn, case["id"], None, "failed", open_issues(None), "the verification never started")
            continue
        if str(case["current_run_id"] or "").startswith(GPF_RUN_PREFIX):
            try:
                issues = gpf_issues_for_case(case["gpf_case_id"]) if case["gpf_case_id"] else open_issues(None)
            except gpf_bridge.GpfError:
                continue
        else:
            rep = report_dict(ARTIFACTS / f"run-{case['current_run_id']}") if case["run_state"] == "done" else None
            issues = open_issues(rep)
        _move_case_on(conn, case["id"], case["current_run_id"], case["run_state"], issues, case["run_error"])
    return changed


def sync_gpf_case(conn: db.Connection, case: db.Row) -> dict | None:
    """Nothing moves a GP Fund case on the pension side but the Accountant General.

    Until 7 Oct 2026 "passed for payment" in the module approved the pension-side case by itself
    (business decision M1 ended that), and until 9 Oct 2026 a RETURN the officer made in the
    module's own screens returned the pension-side case by itself (GPF_RETURN). Decision of 9 Oct
    2026: no automatic return in pension or GP Fund. The module's examination -- its disposal
    included -- shows on the case screen, and the AG returns the case with the Return button and
    a remark. Kept as the hook every read of a GP Fund case still calls; returns None."""
    return None


def _move_case_on(conn: db.Connection, case_id: str, run_id: str | None, state: str, issues: dict,
                  error: str | None) -> None:
    """CHECK_DONE or CHECK_FAILED on a case still in AI_CHECKING for this run; silent otherwise."""
    case = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if case is None or case["status"] != workflow.AI_CHECKING:
        return
    if run_id is not None and case["current_run_id"] != run_id:
        return                                # a newer check superseded this one
    try:
        if state != "done":
            workflow.transition(conn, case, "CHECK_FAILED", None, run_id=run_id,
                                remark=_plain_failure(error))
            return
        clean = nothing_outstanding(issues)
        workflow.transition(conn, case, outcome(issues), None, run_id=run_id,
                            payload={**issues, **({"nothing_outstanding": True} if clean else {})},
                            remark=_clean_remark() if clean else _summary_line(issues))
    except (workflow.WorkflowError, db.OperationalError):
        pass                                  # somebody moved the case meanwhile, or the database was busy


def _plain_failure(error: str | None) -> str:
    """The failure in one office-readable sentence; the engine's full text stays on the run."""
    if not error:
        return "The verification stopped without producing a report."
    text = error.strip().splitlines()[0]
    if "nothing in this bundle could be read" in text:
        return "None of the attached files could be read as a document; attach the papers as PDF or scanned images and run the verification again."
    text = text.split("BundleError:")[-1].split("Error:")[-1].strip()
    return (text[:160] + "…") if len(text) > 160 else text or "The verification did not complete."


def _clean_remark() -> str:
    return ("AI verification complete: every required document present and no finding. "
            "The case awaits the Office of the Accountant General's decision; nothing is approved automatically.")


def _summary_line(issues: dict) -> str:
    parts = []
    if issues.get("verdict"):
        parts.append(f"engine verdict {issues['verdict'].replace('_', ' ').lower()}")
    if issues.get("high_flags"):
        parts.append(f"{len(issues['high_flags'])} HIGH finding(s)")
    if issues.get("missing_checklist"):
        parts.append(f"{len(issues['missing_checklist'])} checklist item(s) missing or defective — "
                     f"return the case to the department for them if required")
    if issues.get("unidentified_pages"):
        parts.append(f"{issues['unidentified_pages']} page(s) could not be identified — name them before returning the case")
    return "AI verification complete, for the Office of the Accountant General's decision: " + (", ".join(parts) if parts else "no issues found") + "."


_SYNC_THREAD: threading.Thread | None = None


def start_reconciler(interval_s: float = 3.0) -> None:
    """A daemon that syncs run states every few seconds, so a case moves on even when nobody
    is looking at it (the automatic return and approval depend on that)."""
    global _SYNC_THREAD
    if _SYNC_THREAD and _SYNC_THREAD.is_alive():
        return

    last_sweep = 0.0

    def loop() -> None:
        nonlocal last_sweep
        while True:
            time.sleep(interval_s)
            try:
                prune_registry()
                conn = db.connect()
                try:
                    sync_run_states(conn, force=True)
                    # Disk housekeeping every ten minutes (api.runs.sweep_disk, R8): orphan run
                    # folders and stale upload staging files; never a run a case refers to.
                    if time.monotonic() - last_sweep > 600:
                        last_sweep = time.monotonic()
                        removed = sweep_disk(referenced_run_ids(conn))
                        if removed["runs"] or removed["staging"]:
                            print(f"[case_runs] swept {len(removed['runs'])} orphan run(s), "
                                  f"{len(removed['staging'])} stale upload(s)")
                finally:
                    conn.close()
            except Exception as exc:                        # noqa: BLE001
                print(f"[case_runs] reconciler: {exc}")

    _SYNC_THREAD = threading.Thread(target=loop, name="case-run-reconciler", daemon=True)
    _SYNC_THREAD.start()
