"""The "Signatories and delegation of authority" task shows the specimens of the case's department
from the shared master store (scope change C1, 9 Oct 2026)."""
import json
import sqlite3
from datetime import date
from pathlib import Path

from gpf import signatories
from gpf.rules_common import _doa

PENSION_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = PENSION_ROOT / "api" / "migrations" / "0013_signing_authorities.sql"


def _store(tmp_path, *, specimen=True, effective_to=None):
    conn = sqlite3.connect(tmp_path / "portal.sqlite3", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO signing_authorities(id, product_scope, department_code, department_name, department_aliases_json, post, "
        "post_aliases_json, officer_name, effective_from, effective_to, provisional, source, created_at, updated_at) "
        "VALUES ('SGAD-AS-ADMN-2025-09-09', 'BOTH', 'SGAD', 'Services & General Administration Department', ?, "
        "'Additional Secretary (Admn)', ?, 'Mr X', '2025-09-09', ?, 0, 'PENSION_REGISTER', 't', 't')",
        (json.dumps(["S&GAD", "SGAD"]), json.dumps(["Additional Secretary (Admn.)", "Addl. Secretary (Admn)"]), effective_to))
    if specimen:
        img = tmp_path / "spec.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 16)
        conn.execute("INSERT INTO signatory_specimens(id, authority_id, stored_path, uploaded_at) VALUES ('sp1', 'SGAD-AS-ADMN-2025-09-09', ?, 't')",
                     (str(img),))
    return conn


def _facts():
    return {"kind": "refundable", "docs": {}, "signatures": [
        {"id": "sanction", "page": 3, "doc": "sanction order", "role": "sanctioning", "roleLabel": "Sanctioning signature",
         "authority": "Govt. of the Punjab, S & G A D", "signedBy": "Additional Secretary (Admn.)", "forMarker": False, "crop": None}],
        "verifications": {}}


def test_the_task_carries_the_sgad_specimen_for_an_sgad_case(tmp_path):
    conn = _store(tmp_path)
    signatories.set_connection(conn)
    try:
        found = signatories.specimens_for("S&GAD", "Addl. Secretary (Admn)", date(2026, 1, 1))
        assert found["authority"]["id"] == "SGAD-AS-ADMN-2025-09-09"
        assert found["specimens"] == [{"id": "sp1", "url": "api/signatories/sp1/image"}]
        assert found["message"] is None
        results = _doa(_facts())
        assert results and results[0]["status"] == "conf"            # the comparison stays the officer's
        assert results[0]["specimens"][0]["url"] == "api/signatories/sp1/image"
        assert results[0]["specimen_authority"]["department"].startswith("Services")
        assert "No specimen on file" not in results[0]["finding"]
        assert signatories.specimen_path("sp1").name == "spec.jpg"
        assert signatories.specimen_path("../etc/passwd") is None
    finally:
        signatories.set_connection(None)


def test_no_specimen_on_file_is_said_and_stays_a_verification_task(tmp_path):
    conn = _store(tmp_path, specimen=False)
    signatories.set_connection(conn)
    try:
        found = signatories.specimens_for("S&GAD", "Additional Secretary (Admn)")
        assert found["specimens"] == []
        assert found["message"] == "No specimen on file for Services & General Administration Department, Additional Secretary (Admn)"
        results = _doa(_facts())
        assert results[0]["status"] == "conf"
        assert "No specimen on file for Services & General Administration Department" in results[0]["finding"]
        # Another department: nothing on file at all.
        other = signatories.specimens_for("Punjab Police", "DIG Operations")
        assert other["authority"] is None and other["message"].startswith("No specimen on file for Punjab Police")
    finally:
        signatories.set_connection(None)


def test_a_closed_or_not_yet_in_force_entry_is_no_match(tmp_path):
    conn = _store(tmp_path, effective_to="2025-12-31")
    signatories.set_connection(conn)
    try:
        assert signatories.specimens_for("S&GAD", "Additional Secretary (Admn)", date(2025, 10, 1))["specimens"]
        assert not signatories.specimens_for("S&GAD", "Additional Secretary (Admn)", date(2026, 2, 1))["specimens"]
        assert not signatories.specimens_for("S&GAD", "Additional Secretary (Admn)", date(2025, 1, 1))["specimens"]
    finally:
        signatories.set_connection(None)


def test_without_a_store_the_task_still_stands(tmp_path):
    signatories.set_connection(None)
    found = signatories.specimens_for("S&GAD", "Additional Secretary (Admn)")
    assert found["specimens"] == [] and found["message"].startswith("No specimen on file")
    assert _doa(_facts())[0]["status"] == "conf"
