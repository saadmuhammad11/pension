"""A waiver covers the finding it was granted on, not whatever the item later says (audit 6 Oct 2026, G2).

A disposition stayed attached to its item through every re-run. After a cure or a corrected
reading changed the item's figure, a waiver given on "Rs 50,000 over the limit" silently covered
"Rs 250,000 over the limit". The disposition is now kept for the record, marked stale, and the
item counts as open again until an officer disposes of the new finding.
"""
from gpf import engine
from gpf.engine import CaseState, OFFICERS, fingerprint, position, run_case


def _result(finding: str, status: str = "hard") -> dict:
    return {"id": "ADV-LIMIT", "code": "R9", "status": status, "finding": finding, "title": "80% limit"}


def _state() -> CaseState:
    return CaseState(k="refundable", F={"kind": "refundable"}, officer=OFFICERS[1])


def test_a_changed_finding_marks_the_waiver_stale_and_reopens_the_item(monkeypatch):
    s = _state()
    first = [_result("Rs 50,000 over the 80% limit")]
    monkeypatch.setattr(engine, "evaluate", lambda F: [dict(r) for r in first])
    run_case(s, "opened")
    s.disp["ADV-LIMIT"] = {"action": "waive", "ground": "Hardship", "authority": "DAG (Funds) order 12",
                           "by": "DAG", "desig": "DAG", "at": "06-10-2026 17:00", "fingerprint": fingerprint(first[0])}
    assert position(s)["waived"] == 1 and position(s)["open"] == 0

    # The same item, a different figure: the waiver no longer applies.
    second = [_result("Rs 250,000 over the 80% limit")]
    monkeypatch.setattr(engine, "evaluate", lambda F: [dict(r) for r in second])
    run_case(s, "pay slip corrected")
    d = s.disp["ADV-LIMIT"]
    assert d["stale"] is True and d["staleSince"]
    assert d["ground"] == "Hardship"                          # kept for the record
    pos = position(s)
    assert (pos["waived"], pos["open"], pos["hard"]) == (0, 1, 1)

    # The figure goes back to what was waived: the waiver applies again.
    monkeypatch.setattr(engine, "evaluate", lambda F: [dict(r) for r in first])
    run_case(s, "corrected back")
    assert "stale" not in s.disp["ADV-LIMIT"]
    assert position(s)["waived"] == 1


def test_an_unchanged_finding_keeps_its_waiver_and_a_cured_one_is_marked_cured(monkeypatch):
    s = _state()
    results = [_result("Rs 50,000 over the 80% limit"), _result("Form missing", "adv") | {"id": "FORM"}]
    monkeypatch.setattr(engine, "evaluate", lambda F: [dict(r) for r in results])
    run_case(s, "opened")
    for r in results:
        s.disp[r["id"]] = {"action": "waive", "ground": "g", "authority": "a", "fingerprint": fingerprint(r)}
    run_case(s, "re-run, nothing changed")
    assert all("stale" not in d for d in s.disp.values())
    assert position(s)["waived"] == 2
    monkeypatch.setattr(engine, "evaluate", lambda F: [dict(results[0])])     # the form arrived
    run_case(s, "form uploaded")
    assert s.disp["FORM"]["cured"] is True
    assert position(s)["waived"] == 1


def test_a_disposition_without_a_fingerprint_is_trusted(monkeypatch):
    """Dispositions recorded before this change carry no fingerprint; they are not disturbed."""
    s = _state()
    monkeypatch.setattr(engine, "evaluate", lambda F: [_result("Rs 50,000 over the 80% limit")])
    run_case(s, "opened")
    s.disp["ADV-LIMIT"] = {"action": "waive", "ground": "g", "authority": "a"}
    monkeypatch.setattr(engine, "evaluate", lambda F: [_result("Rs 250,000 over the 80% limit")])
    run_case(s, "changed")
    assert "stale" not in s.disp["ADV-LIMIT"]
