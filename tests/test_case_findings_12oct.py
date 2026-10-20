"""Four fixes from the fresh self-pension case of 12 Oct 2026 (docs/FIX-PROMPT-case-findings-12oct.md).

    /home/tmc/vllm_env/bin/python3 -m unittest tests.test_case_findings_12oct -v

Run ``artifacts/run-a825399965b6`` (PC-2026-000100, FRESH_SELF): the FRC in the bundle read "not
found" because AG-06 never ran on a self-pension column; the department's Form B-I, headed
"Annex-B-1", was filed as Annex-A, so the case had no prescribed form and fell to manual routing;
and the Last Pay Certificate was required of gazetted self-pensioners too. The user's decisions of
12 Oct 2026: the FRC is required on a self pension too, "either found or not found" (an earlier
"acknowledged, not required" reading the same day was withdrawn); the LPC is required for
non-gazetted and not for gazetted (BPS-16) self-pensioners. The OCR text here is the real run's
wording with the servant's particulars replaced.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Page 6 of the run as OCR read it: the department's copy of Form B-I, headed "Annex-B-1".
FORM_B_I_AS_ANNEX = (
    "Annex-B-1 (To be issued by the Appointing Authority 90 days before superannuation of the retiring "
    "Government servant). Subject:- NOTIFICATION / ORDERS OF RETIREMENT ON SUPERANNUATION / RETIRING "
    "PENSION AND SANCTION OF PENSIONARY BENEFITS. Notification / Order No.: PR(L0)-2024/6/15 Dated: "
    "23-6-2026 On attainting the age of superannuation Mr Test Servant S/o Test Father Designation: "
    "Naib Qasid in BS* 04 Personnel No: 30001234 shall stand retired from Government service on 30.6.2026"
)
#: Page 7: the real Annex-A, which prints no form number.
ANNEX_A_TEXT = "(Annex-A) DESCRIPTIVE ROLL (List of Family Members) Name of Govt. Servant Test Servant"
#: A forwarding letter that cites the form by name and subject: must stay a letter.
LETTER_CITING_THE_FORM = (
    "Subject: RETIREMENT ON SUPERANNUATION OF MR TEST SERVANT. The pension papers are forwarded "
    "herewith: Form B-I (sanction), Annex-A, CNIC, LPC. Director Public Relations"
)


def _ident(page: int, doc_type: str, evidence: str = ""):
    from extraction.identify import PageIdentity
    return PageIdentity(page=page, document_type=doc_type, confidence=1.0, evidence=evidence,
                        is_first_page=True)


def _page_text(mapping: dict[int, str]):
    from extraction.ocr import PageText
    def fake(image, page, **kw):
        return PageText(page, mapping[page], "t")
    return fake


class FormBIFiledAsAnnexA(unittest.TestCase):
    """Change 2: a prescribed form the vision model filed under another label is reclaimed when OCR
    prints both its number and its own title on the page."""

    def test_the_annex_b_1_page_becomes_form_b_i_and_the_real_annex_a_stays(self) -> None:
        from extraction.identify import verify_with_ocr
        idents = [_ident(6, "ANNEX_A", "Annex-B-1"), _ident(7, "ANNEX_A", "DESCRIPTIVE ROLL")]
        with mock.patch("extraction.ocr.ocr_page", _page_text({6: FORM_B_I_AS_ANNEX, 7: ANNEX_A_TEXT})):
            out = verify_with_ocr(idents, lambda p: f"p{p}.png")
        self.assertEqual([(i.page, i.document_type) for i in out], [(6, "FORM_B_I"), (7, "ANNEX_A")])
        self.assertEqual(out[0].promoted_from, "ANNEX_A")
        self.assertTrue(out[0].is_first_page)
        self.assertIsNone(out[1].promoted_from)
        # The form's own text is kept for the checklist-column derivation, as for any form.
        self.assertIn(6, verify_with_ocr.form_text)

    def test_a_letter_that_cites_the_form_is_not_promoted(self) -> None:
        from extraction.identify import verify_with_ocr
        with mock.patch("extraction.ocr.ocr_page", _page_text({1: LETTER_CITING_THE_FORM})):
            out = verify_with_ocr([_ident(1, "FORWARDING_LETTER")], lambda p: f"p{p}.png")
        self.assertEqual(out[0].document_type, "FORWARDING_LETTER")

    def test_a_number_without_the_form_s_title_is_not_enough(self) -> None:
        from extraction.identify import verify_with_ocr
        text = "Annex-B-1 enclosed. List of family members of Test Servant: wife, son, daughter."
        with mock.patch("extraction.ocr.ocr_page", _page_text({6: text})):
            out = verify_with_ocr([_ident(6, "ANNEX_A")], lambda p: f"p{p}.png")
        self.assertEqual(out[0].document_type, "ANNEX_A")

    def test_two_form_numbers_on_one_page_promote_nothing(self) -> None:
        from extraction.identify import verify_with_ocr
        text = FORM_B_I_AS_ANNEX + " (copy of orders annexed alongwith a copy of form B-II)"
        with mock.patch("extraction.ocr.ocr_page", _page_text({6: text})):
            out = verify_with_ocr([_ident(6, "OTHER")], lambda p: f"p{p}.png")
        self.assertEqual(out[0].document_type, "OTHER")

    def test_stage_3_persists_the_promotion_and_re_decides_it_from_the_original_label(self) -> None:
        import json
        import tempfile
        from pipeline import run as prun
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            (run / "manifest.json").write_text(json.dumps({"pages": [{"page": 6, "image_path": "p6.png"}]}))
            (run / prun.IDENTITIES).write_text(json.dumps([{
                "page": 6, "document_type": "ANNEX_A", "confidence": 1.0, "evidence": "Annex-B-1",
                "is_first_page_of_document": False}]))
            with mock.patch("extraction.ocr.ocr_page", _page_text({6: FORM_B_I_AS_ANNEX})):
                rows = prun.stage_verify_forms(run)
            self.assertEqual((rows[0]["document_type"], rows[0]["promoted_from"]), ("FORM_B_I", "ANNEX_A"))
            self.assertTrue(rows[0]["is_first_page_of_document"])
            # Re-run with OCR no longer corroborating: the page goes back to what the model said.
            with mock.patch("extraction.ocr.ocr_page", _page_text({6: ANNEX_A_TEXT})):
                rows = prun.stage_verify_forms(run)
            self.assertEqual(rows[0]["document_type"], "ANNEX_A")
            self.assertNotIn("promoted_from", rows[0])

    def test_a_form_b_i_routes_the_self_pension_case_type(self) -> None:
        from rules import CaseRecord, Document
        from rules.case_type import classify_case_type
        # The real bundle: the reclaimed B-I, the Annex-A pages and the superannuation order
        # (p.12) that tells superannuation from retiring pension, both of which B-I governs.
        rec = CaseRecord(case_ref="T", case_type="SELF_PENSION", case_variant="FRESH_SELF",
                         documents=(Document("FORM_B_I", (6,)), Document("ANNEX_A", (7, 8)),
                                    Document("SUPERANNUATION_ORDER", (12,))))
        result = classify_case_type(rec)
        self.assertNotEqual(result.route, "ROUTE_MANUAL")
        self.assertEqual(result.case_type, "SUPERANNUATION_PENSION")
        self.assertIsNotNone(result.prescribed_form)


def _record(docs: tuple[str, ...], variant: str, bps: int | None = None):
    from rules import CaseRecord, Document
    return CaseRecord(case_ref="T", case_type="SELF_PENSION" if variant in ("FRESH_SELF", "FRESH_INVALID", "REVISED")
                      else "FAMILY_PENSION_DEATH_IN_SERVICE",
                      documents=tuple(Document(t, (n + 1,)) for n, t in enumerate(docs)),
                      pay_scale_bps=bps, case_variant=variant)


def _item(record, item_id: str):
    from rules.checklist import run_checklist
    return next((i for i in run_checklist(record, variant=record.case_variant).items if i.id == item_id), None)


class FrcOnASelfPension(unittest.TestCase):
    """Change 1: the FRC is required on a self pension too, "either found or not found" (user,
    12 Oct 2026, decision S14) -- PRESENT with its page, MISSING when not filed, as on the
    family-pension columns."""

    def test_the_frc_is_found_or_not_found_on_a_self_pension(self) -> None:
        from rules.checklist import MISSING, PRESENT
        for variant in ("FRESH_SELF", "FRESH_INVALID", "REVISED"):
            with_frc = _item(_record(("FORM_B_I", "NADRA_FRC"), variant, bps=4), "AG-06")
            self.assertEqual((with_frc.status, with_frc.located), (PRESENT, (2,)), variant)
            without = _item(_record(("FORM_B_I",), variant, bps=4), "AG-06")
            self.assertEqual(without.status, MISSING, variant)

    def test_family_pension_columns_still_require_it(self) -> None:
        from rules.checklist import MISSING, PRESENT
        self.assertEqual(_item(_record(("FORM_D_II",), "WIDOW"), "AG-06").status, MISSING)
        self.assertEqual(_item(_record(("FORM_D_II", "NADRA_FRC"), "WIDOW"), "AG-06").status, PRESENT)


class LpcOnASelfPension(unittest.TestCase):
    """Change 4: required for non-gazetted, not for gazetted self-pensioners; BPS-16 (user, 12 Oct 2026)."""

    def test_gazetted_self_pension_does_not_need_an_lpc(self) -> None:
        from rules.checklist import NOT_APPLICABLE
        for variant in ("FRESH_SELF", "FRESH_INVALID", "REVISED"):
            item = _item(_record(("FORM_B_I",), variant, bps=16), "AG-08")
            self.assertEqual(item.status, NOT_APPLICABLE, variant)
            self.assertIn("gazetted", item.reason)

    def test_non_gazetted_self_pension_still_needs_it(self) -> None:
        from rules.checklist import MISSING, PRESENT
        self.assertEqual(_item(_record(("FORM_B_I",), "FRESH_SELF", bps=15), "AG-08").status, MISSING)
        self.assertEqual(_item(_record(("FORM_B_I", "LPC"), "FRESH_SELF", bps=4), "AG-08").status, PRESENT)

    def test_death_in_service_is_unchanged(self) -> None:
        from rules.checklist import MISSING
        self.assertEqual(_item(_record(("FORM_D_I",), "DEATH_IN_SERVICE", bps=18), "AG-08").status, MISSING)

    def test_an_unknown_grade_keeps_the_requirement(self) -> None:
        from rules.checklist import MISSING
        self.assertEqual(_item(_record(("FORM_B_I",), "FRESH_SELF", bps=None), "AG-08").status, MISSING)


class ServiceStatementAndAutonomousPayslip(unittest.TestCase):
    """AG-09 (service statement, gazetted by Audit) and AG-12 (autonomous-body payslip) are not
    required in any case type (user, 12 Oct 2026, S16): "not required" when absent, cited when
    filed, never "not found"."""

    def test_absent_they_read_not_required_on_every_column(self) -> None:
        from rules.checklist import ALL_VARIANTS, NOT_REQUIRED, requirements_for, run_checklist
        from rules import CaseRecord
        for variant in ALL_VARIANTS:
            ids = {r.id for r in requirements_for(variant)}
            cl = run_checklist(CaseRecord(case_ref="T", case_type="", pay_scale_bps=4, case_variant=variant),
                               variant=variant)
            for item_id in ("AG-09", "AG-12"):
                if item_id not in ids:
                    continue                                   # the sheet has no such line on this column
                item = cl.item(item_id)
                self.assertEqual(item.status, NOT_REQUIRED, (variant, item_id))
                self.assertIn("not required in any case type", item.reason)
            self.assertNotIn("AG-09", [i.id for i in cl.items if i.status == "MISSING"], variant)
        self.assertIn("AG-09", {r.id for r in requirements_for("FRESH_SELF")})
        self.assertIn("AG-12", {r.id for r in requirements_for("FRESH_SELF")})

    def test_filed_they_are_cited_as_found_not_required(self) -> None:
        from rules.checklist import FOUND_NOT_REQUIRED
        for item_id, doc in (("AG-09", "SERVICE_STATEMENT"), ("AG-12", "SALARY_STATEMENT")):
            item = _item(_record(("FORM_B_I", doc), "FRESH_SELF", bps=4), item_id)
            self.assertEqual((item.status, item.located), (FOUND_NOT_REQUIRED, (2,)), item_id)

    def test_the_service_book_line_is_no_longer_required_of_anyone(self) -> None:
        """AG-10 was NOT_APPLICABLE for a gazetted officer until the office removed the
        requirement outright on 20 Oct 2026. It is now NOT_REQUIRED in every case type, so the
        gazetted distinction no longer decides this line -- see NOT_REQUIRED_ANYWHERE."""
        from rules.checklist import NOT_REQUIRED
        item = _item(_record(("FORM_B_I", "SERVICE_STATEMENT"), "FRESH_SELF"), "AG-10")
        self.assertEqual(item.status, NOT_REQUIRED)

    def test_a_service_book_that_is_filed_is_still_cited(self) -> None:
        """Removed, not deleted: a bundle that carries the book has it acknowledged rather
        than the paper going unmentioned."""
        from rules.checklist import FOUND_NOT_REQUIRED
        item = _item(_record(("FORM_B_I", "SERVICE_BOOK"), "FRESH_SELF"), "AG-10")
        self.assertEqual(item.status, FOUND_NOT_REQUIRED)
        self.assertTrue(item.located, "the page carrying it must still be cited")

    def test_the_statement_still_tells_a_gazetted_officer_elsewhere(self) -> None:
        """The capability AG-10 used is still live: it excuses the Last Pay Certificate for a
        gazetted officer (decision S15), so removing AG-10 must not have orphaned it."""
        from rules.checklist import NOT_APPLICABLE
        item = _item(_record(("FORM_B_I", "SERVICE_STATEMENT"), "FRESH_SELF"), "AG-08")
        self.assertEqual(item.status, NOT_APPLICABLE)


if __name__ == "__main__":
    unittest.main()
