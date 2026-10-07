"""Resubmission rounds (30 Sep 2026): a returned case comes back and only its new papers are read.

    python3 -m unittest tests.test_resubmission_rounds -v

The pipeline pieces are tested with the models stubbed and COUNTED -- the point of the change is
which pages reach a model, so every test that runs a stage asserts the pages it was called on.
The API flow runs over TestClient with ``api.runs.execute`` stubbed, as tests.test_api_v2 does,
and checks what the rounds record says: the request, the base run, the resolution.
"""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pipeline import carryover


def _bundle(*parts):
    """A bundle.json of (name, sha, pages) parts, laid end to end."""
    out, page = [], 1
    for i, (name, sha, n) in enumerate(parts, start=1):
        out.append({"index": i, "name": name, "sha256": sha, "pages": n,
                    "page_from": page, "page_to": page + n - 1, "skipped": ""})
        page += n
    return {"parts": out, "pages": page - 1}


class Plan(unittest.TestCase):
    def test_an_added_document_is_new_and_every_earlier_page_keeps_its_number(self) -> None:
        base = _bundle(("01-case.pdf", "A", 15))
        new = _bundle(("01-case.pdf", "A", 15), ("02-frc.pdf", "F", 2))
        p = carryover.plan(new, base)
        self.assertEqual(p["page_map"], {n: n for n in range(1, 16)})
        self.assertEqual(p["new_pages"], [16, 17])
        self.assertEqual([x["status"] for x in p["parts"]], ["REUSED", "NEW"])

    def test_a_replacement_early_in_the_bundle_renumbers_the_pages_after_it(self) -> None:
        # Round 1: cover (1 page), FRC (2 pages), LPC (3 pages). Round 2 replaces the FRC: the
        # replacement goes to the end, so the LPC moves from pp.4-6 to pp.2-4.
        base = _bundle(("01-cover.pdf", "C", 1), ("02-frc.pdf", "F", 2), ("03-lpc.pdf", "L", 3))
        new = _bundle(("01-cover.pdf", "C", 1), ("02-lpc.pdf", "L", 3), ("03-frc-new.pdf", "F2", 1))
        p = carryover.plan(new, base)
        self.assertEqual(p["page_map"], {1: 1, 2: 4, 3: 5, 4: 6})
        self.assertEqual(p["new_pages"], [5])

    def test_two_identical_files_are_matched_one_to_one(self) -> None:
        base = _bundle(("01-cnic.pdf", "K", 1))
        new = _bundle(("01-cnic.pdf", "K", 1), ("02-cnic.pdf", "K", 1))
        p = carryover.plan(new, base)
        self.assertEqual(p["page_map"], {1: 1})
        self.assertEqual(p["new_pages"], [2])


class Remap(unittest.TestCase):
    def test_pages_are_renumbered_and_facts_from_a_withdrawn_page_are_dropped(self) -> None:
        fwd = {1: 1, 4: 2}                                     # base p.2-3 were withdrawn
        facts = {"names": [{"value": "A", "page": 1}, {"value": "B", "page": 2}, {"value": "C", "page": 4}],
                 "forms": [{"pages": [4], "page": 4}, {"pages": [2, 3]}],
                 "form_recovery_declared": {"page": 3, "value": "nil"}, "note": "kept"}
        out = carryover.remap(facts, fwd)
        self.assertEqual([n["value"] for n in out["names"]], ["A", "C"])
        self.assertEqual(out["names"][1]["page"], 2)
        self.assertEqual(out["forms"], [{"pages": [2], "page": 2}])
        self.assertNotIn("form_recovery_declared", out)
        self.assertEqual(out["note"], "kept")


class Prepare(unittest.TestCase):
    """Seeding a resubmission's run directory from the earlier round's."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-carry-")
        root = Path(self._tmp.name)
        self.base, self.run = root / "run-base", root / "run-new"
        (self.base / "pages").mkdir(parents=True)
        self.run.mkdir()
        rows = []
        for n in (1, 2, 3):
            img = self.base / "pages" / f"p{n:03d}-{n:02d}.png"
            img.write_bytes(b"png%d" % n)
            rows.append({"page": n, "image_path": f"pages/{img.name}", "header_title": "", "transcription": "",
                         "quality": 0.5, "width": 10, "height": 10, "rotation": 90 if n == 2 else 0,
                         "rotation_basis": "turned" if n == 2 else ""})
        (self.base / "pages" / "p002-02-as-scanned.png").write_bytes(b"sideways")
        (self.base / "manifest.json").write_text(json.dumps({"source_kind": "raw_scan", "pages": rows}))
        (self.base / "bundle.json").write_text(json.dumps(_bundle(("01-a.pdf", "A", 1), ("02-b.pdf", "B", 2))))
        (self.base / "identities.json").write_text(json.dumps(
            [{"page": n, "document_type": t} for n, t in ((1, "FORM_D_I"), (2, "LPC"), (3, "LPC"))]))
        (self.base / "ocr_text.json").write_text(json.dumps({"1": "form", "2": "lpc a", "3": "lpc b"}))
        (self.base / "psa_signatures.json").write_text(json.dumps({"forms": [
            {"document": "FORM_D_I", "pages": [1], "page": 1, "signature_image": None}], "register": ["x"]}))
        (self.base / "case_report.json").write_text("{}")
        # Round 2 replaces document B (pages 2-3) with C (one page) and keeps A.
        (self.run / "bundle.json").write_text(json.dumps(_bundle(("01-a.pdf", "A", 1), ("02-c.pdf", "C", 1))))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def prepare(self) -> dict:
        with mock.patch.object(carryover, "_is_verification_copy", return_value=False):
            return carryover.prepare(self.run, self.base, "base", self.run / "case.pdf")

    def test_the_unchanged_document_is_seeded_and_the_replaced_one_is_not(self) -> None:
        rec = self.prepare()
        self.assertEqual(rec["mode"], "INCREMENTAL")
        self.assertEqual(rec["page_map"], {"1": 1})
        self.assertEqual(rec["new_pages"], [2])
        self.assertEqual([r["page"] for r in json.loads((self.run / "identities.json").read_text())], [1])
        self.assertEqual(json.loads((self.run / "ocr_text.json").read_text()), {"1": "form"})
        self.assertEqual(json.loads((self.run / "psa_signatures.json").read_text())["forms"][0]["pages"], [1])
        rows = carryover.carried_manifest_rows(self.run)
        self.assertEqual(list(rows), [1])
        self.assertTrue((self.run / rows[1]["image_path"]).exists())

    def test_prepare_is_idempotent_and_never_seeds_over_a_full_run(self) -> None:
        first = self.prepare()
        self.assertEqual(self.prepare(), first)
        # A run directory already under way as a full run is left alone.
        other = Path(self._tmp.name) / "run-full"
        other.mkdir()
        (other / "bundle.json").write_text((self.run / "bundle.json").read_text())
        (other / "identities.json").write_text('[{"page": 1}, {"page": 2}]')
        with mock.patch.object(carryover, "_is_verification_copy", return_value=False):
            rec = carryover.prepare(other, self.base, "base", other / "case.pdf")
        self.assertEqual(rec["mode"], "FULL")
        self.assertEqual(len(json.loads((other / "identities.json").read_text())), 2)
        self.assertIsNone(carryover.load(other))

    def test_nothing_in_common_is_a_full_run(self) -> None:
        (self.run / "bundle.json").write_text(json.dumps(_bundle(("01-z.pdf", "Z", 2))))
        rec = self.prepare()
        self.assertEqual(rec["mode"], "FULL")
        self.assertFalse((self.run / "identities.json").exists())

    def test_a_turned_page_keeps_its_rotation_and_the_as_scanned_original(self) -> None:
        (self.run / "bundle.json").write_text(json.dumps(_bundle(("01-a.pdf", "A", 1), ("02-b.pdf", "B", 2))))
        rec = self.prepare()
        self.assertEqual(rec["new_pages"], [])
        row = carryover.carried_manifest_rows(self.run)[2]
        self.assertEqual(row["rotation"], 90)
        self.assertTrue((self.run / "pages" / "p002-c002-as-scanned.png").exists())


class IngestTakesCarriedRows(unittest.TestCase):
    def test_a_carried_page_is_neither_rendered_nor_judged_for_upright(self) -> None:
        from pipeline import ingest
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "pages").mkdir()
            (out / "pages" / "p001-c001.png").write_bytes(b"x")
            carried = {1: {"page": 1, "image_path": "pages/p001-c001.png", "header_title": "", "transcription": "",
                           "quality": 0.4, "width": 1, "height": 1, "rotation": 0, "rotation_basis": "carried"}}
            rendered, judged = [], []

            def fake_run(cmd):
                if cmd[0] == "pdfinfo":
                    return "Pages: 2\n"
                rendered.append(cmd)
                (out / "pages" / "p002-2.png").write_bytes(b"y")
                return ""
            with mock.patch.object(ingest, "_run", fake_run), \
                 mock.patch.object(ingest, "_render_dpi", return_value=150), \
                 mock.patch.object(ingest, "_quality", return_value=(0.5, 1, 1)), \
                 mock.patch("extraction.upright.vision_judge", return_value=None), \
                 mock.patch("extraction.upright.decide",
                            side_effect=lambda img, j: judged.append(img) or SimpleNamespace(rotated=False, rotation=0, basis="")):
                pages = ingest._ingest_raw_scan(out / "case.pdf", out, out / "pages", carried=carried)
        self.assertEqual([p.page for p in pages], [1, 2])
        self.assertEqual(pages[0].rotation_basis, "carried")
        self.assertEqual(len(rendered), 1)
        self.assertEqual([Path(j).name for j in judged], ["p002-2.png"])


class _StageDir(unittest.TestCase):
    """A base run and a resubmission run on disk, with manifests and documents."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-stage-")
        root = Path(self._tmp.name)
        self.base, self.run = root / "run-base", root / "run-new"
        for d in (self.base, self.run):
            (d / "pages").mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def pages(self, run: Path, n: int) -> None:
        rows = []
        for p in range(1, n + 1):
            (run / "pages" / f"p{p:03d}.png").write_bytes(b"x")
            rows.append({"page": p, "image_path": f"pages/p{p:03d}.png"})
        (run / "manifest.json").write_text(json.dumps({"pages": rows}))

    def carry(self, page_map: dict[int, int], new_pages: list[int]) -> dict:
        return {"mode": "INCREMENTAL", "base_run_id": "base", "base_dir": str(self.base),
                "page_map": {str(k): v for k, v in page_map.items()}, "new_pages": new_pages}


class Stage4Reuse(_StageDir):
    def test_the_form_is_reused_and_only_the_new_salary_statement_is_read(self) -> None:
        from pipeline import extract
        self.pages(self.base, 2)
        self.pages(self.run, 3)
        (self.base / "documents.json").write_text(json.dumps(
            [{"type": "FORM_D_I", "pages": [1]}, {"type": "LPC", "pages": [2]}]))
        (self.base / "fields.json").write_text(json.dumps({
            "fields": [{"name": "date_of_birth", "value": "01-01-1960", "confidence": 0.9, "page": 1,
                        "document": "FORM_D_I", "unreadable_reason": None}],
            "pay_components": [{"name": "basic", "amount": 50000, "page": 1},
                               {"name": "lpc basic", "amount": 50000, "page": 2}],
            "printed_totals": {"form_total_pay": 50000, "lpc_gross": 50000},
            "prescribed_form": "FORM_D_I", "prescribed_form_page": 1,
            "form_d_i_agreement": {"agreed": True}, "lpc_agreement": {"agreed": True}}))
        (self.run / "documents.json").write_text(json.dumps(
            [{"type": "FORM_D_I", "pages": [1]}, {"type": "LPC", "pages": [2]},
             {"type": "SALARY_STATEMENT", "pages": [3]}]))
        calls = []

        def fake_read(image, schema_name):
            calls.append((Path(image).name, schema_name))
            return SimpleNamespace(data={"gross_printed_rs": 60000}), {"agreed": True}
        with mock.patch.object(extract, "extract_page_confirmed", fake_read):
            result = extract.stage_extract(self.run, carry=self.carry({1: 1, 2: 2}, [3]))
        self.assertEqual(calls, [("p003.png", "AG_PAY_CERTIFICATE")])
        self.assertEqual(result["fields"][0]["value"], "01-01-1960")
        self.assertEqual(result["printed_totals"]["form_total_pay"], 50000)
        self.assertEqual(result["printed_totals"]["lpc_gross"], 50000)
        self.assertEqual(result["salary_statement_agreement"]["agreed"], True)   # tagged with document/page since H1
        self.assertEqual(result["carryover"]["run"], 1)
        self.assertEqual(result["carryover"]["reused"], 2)

    def test_a_carried_page_in_a_new_role_is_read_again(self) -> None:
        # Round 1's first LPC was p.2; round 2 replaced it, and the case's first LPC is now a
        # page that was the second LPC before -- carried, but never read as THE LPC.
        from pipeline import extract
        self.pages(self.base, 3)
        self.pages(self.run, 2)
        (self.base / "documents.json").write_text(json.dumps(
            [{"type": "FORM_D_I", "pages": [1]}, {"type": "LPC", "pages": [2]}, {"type": "LPC", "pages": [3]}]))
        (self.base / "fields.json").write_text(json.dumps({
            "fields": [], "pay_components": [], "printed_totals": {}, "prescribed_form": "FORM_D_I",
            "prescribed_form_page": 1, "form_d_i_agreement": {}, "lpc_agreement": {}}))
        (self.run / "documents.json").write_text(json.dumps(
            [{"type": "FORM_D_I", "pages": [1]}, {"type": "LPC", "pages": [2]}]))
        calls = []
        with mock.patch.object(extract, "extract_page_confirmed",
                               lambda image, schema_name: calls.append(Path(image).name) or (SimpleNamespace(data={}), {})):
            extract.stage_extract(self.run, carry=self.carry({1: 1, 2: 3}, []))
        self.assertEqual(calls, ["p002.png"])

    def test_without_a_carry_record_the_stage_reads_as_it_always_has(self) -> None:
        from pipeline import extract
        self.pages(self.run, 2)
        (self.run / "documents.json").write_text(json.dumps(
            [{"type": "FORM_D_I", "pages": [1]}, {"type": "LPC", "pages": [2]}]))
        calls = []
        with mock.patch.object(extract, "extract_page_confirmed",
                               lambda image, schema_name: calls.append((Path(image).name, schema_name))
                               or (SimpleNamespace(data={}), {})), \
             mock.patch("extraction.orient.upright_form_image", side_effect=lambda img, *a, **k: img):
            result = extract.stage_extract(self.run)
        self.assertEqual(calls, [("p001.png", "FORM_D_I"), ("p002.png", "AG_PAY_CERTIFICATE")])
        self.assertNotIn("carryover", result)


class Stage6Reuse(_StageDir):
    def test_only_new_pages_are_read_and_carried_facts_are_renumbered(self) -> None:
        from pipeline import extract
        self.pages(self.run, 3)
        # Round 1 read the LPC at p.2 and the FRC at p.3; round 2 withdrew nothing but moved the
        # FRC to p.2 behind a replaced LPC, and a new CNIC card is p.3.
        (self.base / "assertions.json").write_text(json.dumps({
            "assertions": [{"field": "personnel_no", "value": "123", "page": 3, "document": "NADRA_FRC"}],
            "document_dates": [{"value": "2020", "page": 2, "document": "LPC"},
                               {"value": "2021", "page": 3, "document": "NADRA_FRC"}],
            "frc_family": [{"name": "X", "relation": "wife", "marital_status": "", "page": 3,
                            "document": "NADRA_FRC"}],
            "names": [], "annex_a_family": [], "recoveries": [], "issuing_offices": [], "unreadable": [],
            "payroll_deductions_noted": [], "cnic_cards": []}))
        (self.run / "documents.json").write_text(json.dumps(
            [{"type": "FORM_D_I", "pages": [1]}, {"type": "NADRA_FRC", "pages": [2]},
             {"type": "CNIC", "pages": [3]}]))
        base_facts = {"assertions": [], "document_dates": [{"value": "d", "page": 1, "document": "FORM_D_I"}]}
        (self.base / "assertions.json").write_text(json.dumps(
            {**json.loads((self.base / "assertions.json").read_text()),
             "document_dates": base_facts["document_dates"] + json.loads(
                 (self.base / "assertions.json").read_text())["document_dates"]}))
        read = []

        def fake_read(image, schema_name):
            read.append((Path(image).name, schema_name))
            return SimpleNamespace(data={"document_date": {"value": "2024", "confidence": 0.9}}), {}
        with mock.patch.object(extract, "extract_page_confirmed", fake_read), \
             mock.patch("extraction.ocr.ocr_page", side_effect=AssertionError("no LPC to OCR")), \
             mock.patch("extraction.ocr.attestation_on", side_effect=AssertionError("nothing to attest")):
            result = extract.stage_assertions(self.run, carry=self.carry({1: 1, 2: 3}, [3]))
        self.assertEqual([r[0] for r in read], ["p003.png"])
        self.assertEqual(result["frc_family"][0]["page"], 2)            # renumbered, not re-read
        self.assertEqual(result["assertions"][0]["page"], 2)
        dates = sorted((d["page"], d["value"]) for d in result["document_dates"])
        self.assertEqual(dates, [(1, "d"), (2, "2021"), (3, "2024")])   # the withdrawn LPC's date dropped
        self.assertEqual(result["carryover"]["pages_read"], [3])


class RoundTables(unittest.TestCase):
    """The migration's rules on history: closed rounds and finished checks are final."""

    def setUp(self) -> None:
        from api import db
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-rounds-")
        self.conn = db.connect(Path(self._tmp.name) / "p.sqlite3")
        db.migrate(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def test_a_closed_round_a_request_and_a_finished_check_cannot_be_changed(self) -> None:
        c = self.conn
        c.execute("PRAGMA foreign_keys=OFF")
        c.execute("INSERT INTO case_rounds(id, case_id, submission_no, opened_at, opened_via, closed_at, closed_action) "
                  "VALUES ('r', 'c', 1, 'now', 'CREATE', 'now', 'RETURN')")
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("UPDATE case_rounds SET closed_action = 'APPROVE' WHERE id = 'r'")
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("DELETE FROM case_rounds WHERE id = 'r'")
        c.execute("INSERT INTO case_round_requests(id, case_id, from_submission_no, for_submission_no, action, at) "
                  "VALUES ('q', 'c', 1, 2, 'RETURN', 'now')")
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("UPDATE case_round_requests SET remark = 'x' WHERE id = 'q'")
        c.execute("INSERT INTO case_round_checks(id, case_id, submission_no, run_id, mode, started_at, state, finished_at) "
                  "VALUES ('k', 'c', 1, 'run', 'FULL', 'now', 'done', 'now')")
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("UPDATE case_round_checks SET state = 'failed' WHERE id = 'k'")

    def test_existing_rows_keep_their_meaning(self) -> None:
        cols = {r[1]: r for r in self.conn.execute("PRAGMA table_info(case_runs)")}
        self.assertEqual(cols["mode"][4], "'FULL'")
        docs = {r[1] for r in self.conn.execute("PRAGMA table_info(case_documents)")}
        self.assertTrue({"replaces_document_id", "superseded_in_submission"} <= docs)


# -- the API flow -------------------------------------------------------------------------------
PDF = b"%PDF-1.4\n%round one\n"
FRC = b"%PDF-1.4\n%the NADRA FRC\n"
FIXED = b"%PDF-1.4\n%a corrected Annex-A\n"

MISSING_FRC = {"claimant_name": "Mst. Khalida Bibi",
               "flags": [{"id": "F-1", "severity": "LOW", "class": "ALIAS-RESOLVED", "title": "Names match",
                          "blocks_ppo": False, "evidence": {"asserted": [{"page": 1, "doc": "FORM_D_I"}],
                                                            "contradicted_by": []}}],
               "checklist": {"result": "INCOMPLETE", "missing": 1,
                             "items": [{"id": "AG-06", "requirement": "NADRA FRC", "status": "MISSING"},
                                       {"id": "AG-01", "requirement": "Forwarding letter", "status": "PRESENT",
                                        "located": [1]}]},
               "recommendation": {"verdict": "RETURN_FOR_CORRECTION", "blocking_flags": []}}
FRC_ON_FILE = {**MISSING_FRC,
               "checklist": {"result": "COMPLETE", "missing": 0,
                             "items": [{"id": "AG-06", "requirement": "NADRA FRC", "status": "PRESENT", "located": [2]},
                                       {"id": "AG-01", "requirement": "Forwarding letter", "status": "PRESENT",
                                        "located": [1]}]},
               "recommendation": {"verdict": "FORWARD", "blocking_flags": []}}


class RoundsOverTheApi(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient
        from api import case_runs, db, runs
        self._tmp = tempfile.TemporaryDirectory(prefix="agpb-rounds-api-")
        root = Path(self._tmp.name)
        artifacts = root / "artifacts"
        artifacts.mkdir()
        self.started: list[runs.Run] = []
        self.report = MISSING_FRC

        def fake_execute(run: runs.Run) -> None:
            self.started.append(run)
            run.run_dir.mkdir(parents=True, exist_ok=True)
            runs.persist_intake(run)
            (run.run_dir / "manifest.json").write_text(json.dumps({"source_kind": "raw_scan", "pages": []}))
            if run.base_run_id:
                (run.run_dir / "carryover.json").write_text(json.dumps(
                    {"mode": "INCREMENTAL", "base_run_id": run.base_run_id,
                     "base_dir": str(runs.ARTIFACTS / f"run-{run.base_run_id}"),
                     "page_map": {"1": 1}, "new_pages": [2], "parts": [],
                     "seeded": {"pages": 1, "identities": 1, "ocr_pages": 0, "signature_forms": 0}}))
            (run.run_dir / "case_report.json").write_text(json.dumps(self.report))
            run.state = "done"
            run.started_at = run.finished_at = "2026-09-30T10:00:00"
            run.emit("end", run.state, state=run.state)
        self._patches = [
            mock.patch.object(db, "DB_PATH", root / "portal.sqlite3"),
            mock.patch.object(runs, "ARTIFACTS", artifacts),
            mock.patch.object(runs, "UPLOADS", artifacts / "uploads"),
            mock.patch.object(runs, "execute", fake_execute),
            mock.patch.object(case_runs, "CASE_FILES", artifacts / "cases"),
            mock.patch.object(case_runs, "start_reconciler", lambda *a, **k: None),
            mock.patch.object(case_runs, "SYNC_MIN_INTERVAL_S", 0.0),      # no reconciler: every read syncs
            mock.patch.dict("os.environ", {"PENSION_JWT_SECRET": "test-secret"}),
            mock.patch.object(db, "SEED_PASSWORD", "Pension@2026"),
            mock.patch.object(db, "CREDENTIALS_CSV", root / "credentials.csv"),
            mock.patch.object(db, "CREDENTIALS_HTML", root / "credentials.html"),
        ]
        for p in self._patches:
            p.start()
        self._saved = dict(runs.RUNS)
        runs.RUNS.clear()
        db.migrate()
        db.seed(quiet=True)
        from api.server import app
        self.client = TestClient(app, client=("127.0.0.1", 50000))
        self.db = db

    def tearDown(self) -> None:
        from api import runs
        runs.RUNS.clear()
        runs.RUNS.update(self._saved)
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def login(self, username: str) -> dict:
        r = self.client.post("/api/v2/auth/login", json={"username": username, "password": self.db.SEED_PASSWORD},
                             headers={"X-Portal": "ag"})
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def file(self, h: dict) -> str:
        r = self.client.post("/api/v2/cases", headers=h, data={"case_type": "DEATH_IN_SERVICE"},
                             files=[("files", ("case.pdf", io.BytesIO(PDF), "application/pdf"))])
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["case"]["id"]

    def verify(self, h: dict, case_id: str) -> str:
        r = self.client.post(f"/api/v2/cases/{case_id}/check", headers=h)
        self.assertEqual(r.status_code, 202, r.text)
        return r.json()["run_id"]

    def test_a_first_submission_is_a_full_run_with_no_base(self) -> None:
        dept, ag = self.login("school-education"), self.login("ag.reviewer")
        case_id = self.file(dept)
        self.verify(ag, case_id)
        self.assertIsNone(self.started[0].base_run_id)
        rounds = self.client.get(f"/api/v2/cases/{case_id}/rounds", headers=ag).json()["rounds"]
        self.assertEqual(rounds[0]["checks"][0]["mode"], "FULL")

    def test_return_for_a_missing_document_resubmit_it_and_the_item_is_resolved(self) -> None:
        dept, ag = self.login("school-education"), self.login("ag.reviewer")
        case_id = self.file(dept)
        first = self.verify(ag, case_id)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=ag).json()
        self.assertEqual(case["status"], "RETURNED")                      # the automatic return

        # The department sends the FRC; round 2.
        r = self.client.post(f"/api/v2/cases/{case_id}/documents", headers=dept,
                             files=[("files", ("frc.pdf", io.BytesIO(FRC), "application/pdf"))])
        self.assertEqual(r.json()["submission_no"], 2)
        self.client.post(f"/api/v2/cases/{case_id}/forward", headers=dept, json={"remark": "FRC attached."})
        self.report = FRC_ON_FILE
        second = self.verify(ag, case_id)
        self.assertNotEqual(first, second)
        self.assertEqual(self.started[-1].base_run_id, first)              # round 2 reuses round 1

        rounds = self.client.get(f"/api/v2/cases/{case_id}/rounds", headers=ag).json()["rounds"]
        self.assertEqual([r["submission_no"] for r in rounds], [1, 2])
        self.assertEqual(rounds[0]["closed_action"], "AUTO_RETURN")
        req = rounds[1]["requests"][0]
        self.assertEqual((req["action"], req["items"][0]["id"]), ("AUTO_RETURN", "AG-06"))
        check = rounds[1]["checks"][0]
        self.assertEqual((check["mode"], check["base_run_id"]), ("INCREMENTAL", first))
        self.assertEqual(check["resolution"][0]["resolution"], "RESOLVED")
        self.assertTrue(check["resolution"][0]["on_new_pages"])
        self.assertEqual(check["steps"]["pages_reused"], 1)
        self.assertEqual([d["status"] for d in check["documents"]], ["EARLIER", "NEW"])
        # The unchanged finding is carried as unchanged, not raised again as new.
        self.assertEqual(len(check["changes"]["unchanged"]), 1)
        self.assertEqual(check["changes"]["new"], [])
        # Round 1's record is untouched.
        self.assertEqual(rounds[0]["checks"][0]["mode"], "FULL")

        # The department sees what was asked and that it is on file -- no findings.
        mine = self.client.get(f"/api/v2/cases/{case_id}/rounds", headers=dept).json()["rounds"]
        self.assertNotIn("checks", mine[1])
        self.assertEqual(mine[1]["requested_items"], [{"id": "AG-06", "label": "NADRA FRC", "on_file": True}])

    def test_the_ag_names_items_on_a_return_and_a_clearance_carries_to_the_next_round(self) -> None:
        dept, ag = self.login("school-education"), self.login("ag.reviewer")
        case_id = self.file(dept)
        second = {"id": "F-2", "severity": "MEDIUM", "class": "RELATIONSHIP-UNPROVED",
                  "title": "No Nikah Nama", "blocks_ppo": False,
                  "evidence": {"asserted": [{"page": 1, "doc": "NADRA_FRC"}], "contradicted_by": []}}
        self.report = {**FRC_ON_FILE, "flags": FRC_ON_FILE["flags"] + [second],
                       "recommendation": {"verdict": "HOLD", "blocking_flags": []}}
        first = self.verify(ag, case_id)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=ag).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")
        r = self.client.post(f"/api/v2/cases/{case_id}/runs/{first}/dispositions", headers=ag,
                             json={"flag_id": "F-1", "action": "WAIVE", "ground": "Spellings are the same person."})
        self.assertIn(r.status_code, (200, 201), r.text)
        r = self.client.post(f"/api/v2/cases/{case_id}/return", headers=ag, json={
            "remark": "Annex-A is unsigned; send a signed copy.",
            "items": [{"label": "Annexure-A, signed", "pages": [1], "note": "the DDO's signature is missing"},
                      {"id": "AG-01"}]})
        self.assertEqual(r.status_code, 200, r.text)
        bad = self.client.post(f"/api/v2/cases/{case_id}/return", headers=ag,
                               json={"remark": "x", "items": [{"id": "NOPE"}]})
        self.assertIn(bad.status_code, (409, 422))

        doc_id = self.client.get(f"/api/v2/cases/{case_id}", headers=dept).json()["documents"][0]["id"]
        r = self.client.post(f"/api/v2/cases/{case_id}/documents/{doc_id}/replace", headers=dept,
                             files=[("files", ("annex-a.pdf", io.BytesIO(FIXED), "application/pdf"))])
        self.assertEqual(r.status_code, 201, r.text)
        docs = r.json()["documents"]
        self.assertEqual(docs[0]["superseded_in_submission"], 2)
        self.assertEqual(docs[1]["replaces_document_id"], doc_id)
        self.client.post(f"/api/v2/cases/{case_id}/forward", headers=dept, json={"remark": "Signed copy."})
        self.verify(ag, case_id)
        run = self.started[-1]
        self.assertEqual(run.base_run_id, first)
        # The replaced paper is out of the bundle: the zip holds the replacement alone.
        import zipfile
        from api import runs
        upload = next(runs.UPLOADS.glob(f"{run.run_id}-*.zip"))
        self.assertEqual(zipfile.ZipFile(upload).namelist(), ["01-annex-a.pdf"])

        rounds = self.client.get(f"/api/v2/cases/{case_id}/rounds", headers=ag).json()["rounds"]
        items = rounds[1]["requests"][0]["items"]
        self.assertEqual(items[0]["kind"], "DOCUMENT")
        self.assertEqual(items[1], {"kind": "CHECKLIST", "id": "AG-01", "requirement": "Forwarding letter",
                                    "status": "PRESENT", "note": ""})
        check = rounds[1]["checks"][0]
        self.assertEqual([d["status"] for d in check["documents"]], ["SUPERSEDED", "REPLACEMENT"])
        self.assertEqual(check["carried"]["dispositions"],
                         [{"flag_id": "F-1", "from_flag_id": "F-1", "action": "WAIVE", "officer": "Syed Haider (AG Punjab, Pension Wing)"}])
        # F-2 was never cleared, so the case waits for the AG.
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=ag).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")
        # Clearing it opens the gate; the AG then approves by hand (M1: nothing is approved automatically).
        run_id = run.run_id
        r = self.client.post(f"/api/v2/cases/{case_id}/runs/{run_id}/dispositions", headers=ag,
                             json={"flag_id": "F-2", "action": "WAIVE", "ground": "Relationship shown on the FRC."})
        self.assertIn(r.status_code, (200, 201), r.text)
        self.assertTrue(r.json()["gate"]["open"])
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=ag).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")
        r = self.client.post(f"/api/v2/cases/{case_id}/approve", headers=ag, json={"remark": "Both findings cleared; approved."})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=ag).json()["status"], "APPROVED")

    def test_carried_clearances_that_clear_every_finding_still_wait_for_the_ag(self) -> None:
        dept, ag = self.login("school-education"), self.login("ag.reviewer")
        case_id = self.file(dept)
        self.report = {**FRC_ON_FILE, "checklist": MISSING_FRC["checklist"],
                       "recommendation": {"verdict": "HOLD", "blocking_flags": []}}
        # One finding and a paper missing, with a page the AG must name first: under review.
        self.report = {**self.report, "nameable_pages": [1]}
        first = self.verify(ag, case_id)
        self.assertEqual(self.client.get(f"/api/v2/cases/{case_id}", headers=ag).json()["status"], "UNDER_REVIEW")
        self.client.post(f"/api/v2/cases/{case_id}/runs/{first}/dispositions", headers=ag,
                         json={"flag_id": "F-1", "action": "WAIVE", "ground": "Spellings are the same person."})
        r = self.client.post(f"/api/v2/cases/{case_id}/request-docs", headers=ag,
                             json={"remark": "Send the NADRA FRC.", "items": [{"id": "AG-06"}]})
        self.assertEqual(r.status_code, 200, r.text)
        self.client.post(f"/api/v2/cases/{case_id}/documents", headers=dept,
                         files=[("files", ("frc.pdf", io.BytesIO(FRC), "application/pdf"))])
        self.client.post(f"/api/v2/cases/{case_id}/forward", headers=dept, json={"remark": "FRC attached."})
        self.report = FRC_ON_FILE
        self.verify(ag, case_id)
        case = self.client.get(f"/api/v2/cases/{case_id}", headers=ag).json()
        self.assertEqual(case["status"], "UNDER_REVIEW")                  # carried waivers approve nothing (M1)
        rounds = self.client.get(f"/api/v2/cases/{case_id}/rounds", headers=ag).json()["rounds"]
        self.assertEqual(rounds[1]["requests"][0]["action"], "REQUEST_DOCS")
        self.assertEqual(rounds[1]["checks"][0]["resolution"][0]["resolution"], "RESOLVED")
        self.assertIsNone(rounds[1]["closed_action"])
        r = self.client.post(f"/api/v2/cases/{case_id}/approve", headers=ag, json={"remark": "Resubmission complete; approved."})
        self.assertEqual(r.status_code, 200, r.text)
        rounds = self.client.get(f"/api/v2/cases/{case_id}/rounds", headers=ag).json()["rounds"]
        self.assertEqual(rounds[1]["closed_action"], "APPROVE")


class BackfillOfExistingCases(unittest.TestCase):
    def test_backfill_only_inserts_and_is_idempotent(self) -> None:
        from api import db, rounds
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "p.sqlite3")
            db.migrate(conn)
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("INSERT INTO cases(id, case_no, department_code, created_via, created_by, status, "
                         "submission_no, created_at, updated_at) VALUES ('c', 'PC-1', 'HEALTH', 'DEPARTMENT', 'u', "
                         "'DRAFT', 2, 't0', 't9')")
            for seq, (action, payload) in enumerate([("CREATE", {}), ("FORWARD", {}),
                                                     ("AUTO_RETURN", {"missing_checklist": [{"id": "AG-06", "requirement": "FRC"}]}),
                                                     ("ADD_DOCS", {"submission_no": 2})], start=1):
                conn.execute("INSERT INTO case_events(id, case_id, seq, action, to_status, payload_json, at) "
                             "VALUES (?, 'c', ?, ?, 'X', ?, ?)", (f"e{seq}", seq, action, json.dumps(payload), f"t{seq}"))
            with mock.patch("api.runs.ARTIFACTS", Path(tmp)):
                first = rounds.backfill(conn)
                again = rounds.backfill(conn)
            self.assertGreater(first, 0)
            self.assertEqual(again, 0)
            rs = conn.execute("SELECT submission_no, closed_action FROM case_rounds ORDER BY submission_no").fetchall()
            self.assertEqual([tuple(r) for r in rs], [(1, "AUTO_RETURN"), (2, None)])
            req = conn.execute("SELECT for_submission_no, items_json FROM case_round_requests").fetchone()
            self.assertEqual(req[0], 2)
            self.assertEqual(json.loads(req[1])[0]["id"], "AG-06")
            conn.close()


if __name__ == "__main__":
    unittest.main()
