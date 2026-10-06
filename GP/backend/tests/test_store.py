"""The shared-database repository: round trip, one-time import of the JSON snapshots, documents."""
import json
import sqlite3

from gpf.engine import CaseState
from gpf.store import CaseRepository, DocumentStore, SqliteCaseRepository


def _state(kind="refundable", **kw) -> CaseState:
    s = CaseState(k=kind, F={"kind": kind, "personnelNo": "30012345"}, **kw)
    s.log_audit("Case opened", {"template": kind})
    return s


def test_round_trip_survives_a_restart(tmp_path):
    db = tmp_path / "portal.sqlite3"
    repo = SqliteCaseRepository(db)
    s = _state()
    repo.create("refundable-abc12345", s)
    s.version = 3
    s.caseDisp = "pass"
    repo.save("refundable-abc12345", s)

    again = SqliteCaseRepository(db)                      # a new process
    assert again.list_ids() == ["refundable-abc12345"]
    got = again.get("refundable-abc12345")
    assert got.version == 3 and got.caseDisp == "pass" and got.F["personnelNo"] == "30012345"
    row = sqlite3.connect(db).execute(
        "SELECT kind, version, case_disp, from_scans, officer_id FROM gpf_cases").fetchone()
    assert row == ("refundable", 3, "pass", 0, "ao")


def test_schema_is_recorded_like_a_migration(tmp_path):
    db = tmp_path / "portal.sqlite3"
    SqliteCaseRepository(db)
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"gpf_cases", "gpf_documents", "schema_migrations"} <= tables
    assert conn.execute("SELECT version FROM schema_migrations").fetchall() == [("0005_gpf_cases",)]


def test_imports_the_old_snapshots_once(tmp_path):
    snaps = tmp_path / "cases"
    old = CaseRepository(snapshot_dir=snaps)
    old.create("death-scan-0e5c5ee6", _state("death", meta={"label": "From scans"}))
    old.create("final-11c43ffd", _state("final"))
    (snaps / "broken.json").write_text("{not json", encoding="utf-8")

    db = tmp_path / "portal.sqlite3"
    repo = SqliteCaseRepository(db, import_dir=snaps)
    assert repo.imported == 2
    assert sorted(repo.list_ids()) == ["death-scan-0e5c5ee6", "final-11c43ffd"]
    assert repo.get("death-scan-0e5c5ee6").meta == {"label": "From scans"}
    assert sqlite3.connect(db).execute(
        "SELECT from_scans FROM gpf_cases WHERE id = 'death-scan-0e5c5ee6'").fetchone() == (1,)

    # Saved in the database since; a restart must not put the stale snapshot back.
    s = repo.get("final-11c43ffd")
    s.version = 5
    repo.save("final-11c43ffd", s)
    again = SqliteCaseRepository(db, import_dir=snaps)
    assert again.imported == 0
    assert again.get("final-11c43ffd").version == 5


def test_document_store_records_pages(tmp_path):
    repo = SqliteCaseRepository(tmp_path / "portal.sqlite3")
    docs = DocumentStore(tmp_path / "uploads", db=repo)
    meta = docs.save("final-11c43ffd", "page 1.pdf", b"%PDF-1.4 x")
    assert docs.read("final-11c43ffd", meta["storedAs"]) == b"%PDF-1.4 x"
    row = sqlite3.connect(tmp_path / "portal.sqlite3").execute(
        "SELECT case_id, name, stored_as, sha256, bytes, content_type FROM gpf_documents").fetchone()
    assert row == ("final-11c43ffd", "page 1.pdf", meta["storedAs"], meta["hash"], 10, "application/pdf")
    assert json.loads(json.dumps(meta))  # plain data, as the audit trail records it
