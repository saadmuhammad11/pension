"""Whether a read of a pay table is usable. ``extraction.client.amounts_look_unread``.

Standard library only, no GPU and no network: the decision is pure, which is the point of
having lifted it out of ``extract_page``.

The guard exists for a real failure. A page's first read in a fresh vLLM instance can come
back with every printed_label correct and every amount null -- the page is legible and the
digits are simply not emitted -- and a determination built on it would be a page of nulls.

It cost a case its determination on 2026-09-15 by firing on the opposite situation. Form D-I
is a PRO-FORMA: it prints six pay slots and the department strikes a dash through the ones
that do not apply. On the golden case four of six are dashes, so a faithful read of page 41
IS a majority of nulls, and the guard rejected the page three times in three attempts. Both
halves are pinned below.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def row(label: str, amount: int | None, kind: str = "pay_or_allowance") -> dict:
    return {"printed_label": label, "amount_rs": amount, "line_kind": kind}


class TheKnownPathology(unittest.TestCase):
    """The failure the guard was written for. It must keep firing on every one of these."""

    def test_every_label_read_and_no_figure_at_all(self):
        from extraction.client import amounts_look_unread
        data = {"pay_components": [row(f"Allowance {i}", None) for i in range(14)],
                "total_pay_printed_rs": 192030}
        self.assertTrue(amounts_look_unread(data))

    def test_one_figure_out_of_fourteen(self):
        """The threshold exists because an earlier version tested 'no amount is an integer'
        and failed to fire: 1 row of 14 (the recovery line) did carry a figure."""
        from extraction.client import amounts_look_unread
        data = {"pay_components": [row("Recovery", 126355, "recovery")]
                                  + [row(f"Row {i}", None) for i in range(13)],
                "total_pay_printed_rs": 192030}
        self.assertTrue(amounts_look_unread(data))

    def test_no_printed_total_to_appeal_to(self):
        """With no independent witness the rows cannot vouch for themselves, so a majority
        of nulls stands rejected."""
        from extraction.client import amounts_look_unread
        data = {"pay_components": [row("Basic Pay", None), row("HRA", None),
                                   row("Special Pay", None), row("Adhoc", 13284)],
                "total_pay_printed_rs": None}
        self.assertTrue(amounts_look_unread(data))

    def test_figures_read_but_they_do_not_add_up_to_the_printed_total(self):
        """A partial read is the dangerous one: it reconciles against nothing and would
        understate the pension. The rows must add up before they are believed."""
        from extraction.client import amounts_look_unread
        data = {"pay_components": [row("Basic Pay", 178440)]
                                  + [row(f"R{i}", None) for i in range(5)],
                "total_pay_printed_rs": 192030}
        self.assertTrue(amounts_look_unread(data))


#: Page 41 of the golden case exactly as the vision model returned it on 2026-09-15, on the
#: read that was rejected three times in three attempts. Transcribed from the payload, not
#: reconstructed: the defects it carries are the ones that actually occur.
P041_AS_READ = {
    "total_pay_printed_rs": 192030,
    "gross_printed_rs": None,
    "pay_components": [
        row("Basic Pay Rs.", 178440),
        row("Special Pay Rs.", None),
        row("Personal Pay Rs.", 13590),
        row("Qualification Pay Rs.", None),
        row("Technical Pay Rs.", None),
        row("Senior Post Allowance Rs.", None),
        row("Total Pay Rs.", 192030),                     # the printed total, mis-tagged
        row("Orderly Allowance (if any) Rs.", 192030),    # phantom: total paired with next label
        row("No. Demand / Recovery was due against him.", None),
        row("Advances drawn by the deceased which needs", None),
        row("Bank Account No. in which family pension/", None),
        row("Administrative and Financial sanction for", None),
        row("is hereby accorded in favor of Mr. WAQA", None),
    ] + [row("00001-0000108-3", None)] * 11,
}


class TheReadThatWasWronglyRejected(unittest.TestCase):
    """The regression. Twenty-four rows, four amounts, and a correct read underneath."""

    def test_the_page_is_accepted(self):
        from extraction.client import amounts_look_unread
        self.assertFalse(amounts_look_unread(P041_AS_READ))

    def test_what_survives_cleaning_is_the_right_answer(self):
        """The guard may only accept it because the deterministic layer really does reduce it
        to the two reckonable figures. If that stops being true, this must fail."""
        from pipeline.extract import _pay_components
        out = _pay_components(P041_AS_READ, page=41, printed_total=192030)
        self.assertEqual([(c.printed_label, int(c.amount)) for c in out],
                         [("Basic Pay Rs.", 178440), ("Personal Pay Rs.", 13590)])
        self.assertEqual(sum(int(c.amount) for c in out), 192030)

    def test_the_phantom_orderly_allowance_never_reaches_a_pension(self):
        """Orderly allowance is RECKONABLE. Summing the phantom would put pensionable pay at
        384,060 against a printed 192,030 and double the pension for life."""
        from pipeline.extract import _pay_components
        out = _pay_components(P041_AS_READ, page=41, printed_total=192030)
        self.assertNotIn("orderly_allowance", [c.component for c in out])


#: Page 42 of the golden case, the densest page in the bundle, exactly as the model returned
#: it on 2026-09-15. Nine real pay rows summing to the printed gross, wrapped in a deduction,
#: a GPF balance and thirteen rows of payroll-system metadata.
P042_AS_READ = {
    "gross_printed_rs": 353795,
    "total_pay_printed_rs": None,
    "total_deductions_printed_rs": 55236,
    "pay_components": [
        row("Basic Pay", 178440), row("House Rent Allowance 45%", 13284),
        row("Special Allow 2021 25%", 14803), row("Adhoc Relief All 2023 30%", 53532),
        row("Adhoc Relief 2025 (10%)", 19203), row("Personal Pay(Maxim Grade)", 13590),
        row("Medical Allow 15% (16-22)", 4963), row("Adhoc Rel Al 15% 22(PS17)", 17574),
        row("Adhoc Relief All 2024 20%", 38406),
        row("Income Tax", -55236, "deduction"),
        row("GPF Interest applied", None),
        row("GPF Balance: 62,336.00 (provisional)", 62336),
        row("GPF A/C No:", None), row("Vendor Number: 30044922 - MRS.NARGAS I", None),
        row("Pay scale: BPS For - 2022", None), row("Pay Scale Type: Civil BPS: 19", None),
        row("Pay Stage: 20", None), row("Payee Name: WAQAR ABDUL BASIT", None),
        row("Account Number: 0000000000000017", None),
        row("Bank Details: THE BANK OF PUNJAB, 070172", None),
        row("Permanent Address: 84 YASREB COLONY MULT", None), row("City: LAHORE", None),
        row("Domicile: PN - Punjab", None), row("Housing Status: No Official", None),
    ],
}


class TheSalaryStatementIsAlsoAccepted(unittest.TestCase):
    """Nine real rows against a printed gross, and fifteen rows of noise around them."""

    def test_the_page_is_accepted(self):
        from extraction.client import amounts_look_unread
        self.assertFalse(amounts_look_unread(P042_AS_READ))

    def test_the_deduction_is_not_counted_as_pay(self):
        """Income tax is negative and would drag the reconciliation below the gross."""
        from extraction.client import usable_pay_rows
        labels = [c["printed_label"] for c in usable_pay_rows(P042_AS_READ["pay_components"], 353795)]
        self.assertNotIn("Income Tax", labels)

    def test_the_gpf_balance_is_not_counted_as_pay(self):
        """A GPF balance is a separate stream entirely (BRAIN §9.11), and counting it would
        overstate the pensionable base by 62,336."""
        from extraction.client import usable_pay_rows
        labels = [c["printed_label"] for c in usable_pay_rows(P042_AS_READ["pay_components"], 353795)]
        self.assertNotIn("GPF Balance: 62,336.00 (provisional)", labels)

    def test_what_survives_reconciles_with_the_printed_gross(self):
        from extraction.client import usable_pay_rows
        usable = usable_pay_rows(P042_AS_READ["pay_components"], 353795)
        self.assertEqual(len(usable), 9)
        self.assertEqual(sum(c["amount_rs"] for c in usable), 353795)


class TheGuardAndThePipelineAgree(unittest.TestCase):
    """The guard decides whether a page is usable; the pipeline decides what is used from it.
    They must not drift apart -- a guard that accepted rows the pipeline then discarded would
    pass a page that determines nothing.

    One divergence is deliberate, and it runs the safe way. A row whose label matches no rule
    is never SUMMED, so the guard leaves it out; but the pipeline carries it to the engine,
    which puts it in ``Emoluments.unknown`` and refuses the determination (EMOL-08). See
    ``AnUnrecognisedPayLineReachesTheEngine`` below. The pipeline's set is therefore a
    superset of the guard's, and every addition is a line an officer has to settle."""

    def test_they_select_the_same_rows_on_page_41(self):
        from extraction.client import usable_pay_rows
        from pipeline.extract import _pay_components
        guard = [c["printed_label"] for c in usable_pay_rows(P041_AS_READ["pay_components"], 192030)]
        pipe = [c.printed_label for c in _pay_components(P041_AS_READ, page=41, printed_total=192030)]
        self.assertEqual(guard, pipe)

    def test_they_select_the_same_rows_on_page_42(self):
        from extraction.client import usable_pay_rows
        from pipeline.extract import _pay_components
        guard = [c["printed_label"] for c in usable_pay_rows(P042_AS_READ["pay_components"], 353795)]
        pipe = [c.printed_label for c in _pay_components(P042_AS_READ, page=42, printed_total=353795)]
        self.assertEqual(guard, pipe)


class ThePrescribedFormIsAProForma(unittest.TestCase):
    """Form D-I, page 41 of the golden case, as it is actually printed:

        (i) Basic Pay Rs. 178440/-  (ii) Special Pay Rs. -  (iii) Personal Pay Rs. 13590/-
        (iv) Qualification Pay Rs. -  (v) Technical Pay Rs. -  (vi) Senior Post Allowance Rs. -
        Total Pay Rs. 192030/-

    Two figures, four dashes, and the form's own total agreeing with the two.
    """

    def test_the_form_as_the_model_read_it_when_it_emitted_every_slot(self):
        from extraction.client import amounts_look_unread
        data = {"pay_components": [row("Basic Pay", 178440), row("Personal Pay", 13590),
                                   row("Special Pay", None), row("Qualification Pay", None),
                                   row("Technical Pay", None), row("Senior Post Allowance", None)],
                "total_pay_printed_rs": 192030}
        self.assertFalse(amounts_look_unread(data))

    def test_the_same_page_padded_out_to_the_schema_cap(self):
        """What actually happened: 24 rows, 4 amounts, rejected three times in three attempts.
        The two reckonable figures still add to the printed total, so the read is complete."""
        from extraction.client import amounts_look_unread
        data = {"pay_components": [row("Basic Pay", 178440), row("Personal Pay", 13590)]
                                  + [row(f"Slot {i}", None) for i in range(22)],
                "total_pay_printed_rs": 192030}
        self.assertFalse(amounts_look_unread(data))

    def test_the_good_read_is_unaffected(self):
        """The Sep-4 read of the same page: the dashes were never emitted at all, which is
        what the schema now asks for. Too few rows to test, and nothing to reject."""
        from extraction.client import amounts_look_unread
        data = {"pay_components": [row("Basic Pay", 178440), row("Personal Pay", 13590)],
                "total_pay_printed_rs": 192030}
        self.assertFalse(amounts_look_unread(data))

    def test_a_pay_certificate_reconciles_on_its_own_gross(self):
        """A Last Pay Certificate prints Gross rather than Total Pay, and the guard reads
        whichever the document states."""
        from extraction.client import amounts_look_unread
        data = {"pay_components": [row("Basic Pay", 178440), row("HRA 45%", 13284)]
                                  + [row(f"Slot {i}", None) for i in range(4)],
                "gross_printed_rs": 191724}
        self.assertFalse(amounts_look_unread(data))


class TheSchemaAndTheGuardAgree(unittest.TestCase):
    """They contradicted each other, which is how the defect arose: the schema said to emit a
    dash row as null, and the guard rejected a majority of nulls."""

    def test_the_schema_no_longer_asks_for_empty_slots(self):
        from extraction.schemas import SCHEMAS
        form = SCHEMAS["FORM_D_I"]["properties"]["pay_components"]
        described = form["items"]["properties"]["amount_rs"]["description"]
        self.assertIn("Do NOT emit a row", described)
        self.assertNotIn("null where the row shows a dash", described)

    def test_a_short_table_is_never_judged(self):
        """Two rows are not a sample. The guard needs three before it says anything."""
        from extraction.client import amounts_look_unread
        self.assertFalse(amounts_look_unread({"pay_components": [row("Basic Pay", None)]}))
        self.assertFalse(amounts_look_unread({"pay_components": []}))


class AnUnreadablePayDocumentIsAGapNotAFailure(unittest.TestCase):
    """Stage 4 discarded everything it had read when a supplementary page could not be read.

    On the golden case p041 (Form D-I, authoritative) and p042 (the salary statement) both
    read, then p007 -- a handwritten 2003 transfer LPC from another district, quality 0.364 --
    raised, and because ``fields.json`` is written after the loop the whole stage was lost. The
    officer was told "the bundle has no prescribed form for the extraction to read", of a
    bundle whose prescribed form had just been read successfully.
    """

    @staticmethod
    def _extraction(data):
        from extraction.client import Extraction
        return Extraction(data=data, doc_type="FORM_D_I", schema_name="FORM_D_I",
                          source="p041-000.png", model="test", prompt_version="test",
                          latency_s=0.0, prompt_tokens=0, completion_tokens=0)

    def _run_dir(self, tmp):
        """A minimal run directory: one Form D-I page and one LPC page."""
        import json
        from pathlib import Path
        run = Path(tmp)
        (run / "pages").mkdir(parents=True)
        (run / "pages" / "p041-000.png").write_bytes(b"")
        (run / "pages" / "p007-000.png").write_bytes(b"")
        (run / "manifest.json").write_text(json.dumps({"pages": [
            {"page": 41, "image_path": "pages/p041-000.png"},
            {"page": 7, "image_path": "pages/p007-000.png"},
        ]}))
        (run / "documents.json").write_text(json.dumps([
            {"type": "LPC", "pages": [7], "present": True},
            {"type": "FORM_D_I", "pages": [41], "present": True},
        ]))
        return run

    def test_the_form_is_kept_when_the_lpc_cannot_be_read(self):
        import tempfile
        from unittest import mock
        from extraction.client import ExtractionError
        import pipeline.extract as X

        form_read = self._extraction(
            {"date_of_birth": {"value": "19-02-1966", "confidence": 0.95},
             "total_pay_printed_rs": 192030,
             "pay_components": [{"printed_label": "Basic Pay", "amount_rs": 178440,
                                 "line_kind": "pay_or_allowance", "confidence": 0.95}]})

        def fake(image, schema_name="GENERIC_PAGE", **kw):
            if "p007" in str(image):
                raise ExtractionError("p007-000.png: could not obtain two usable reads")
            return form_read, {"agree": True}

        with tempfile.TemporaryDirectory() as tmp:
            run = self._run_dir(tmp)
            with mock.patch.object(X, "extract_page_confirmed", fake):
                out = X.stage_extract(run)
            self.assertEqual([c["printed_label"] for c in out["pay_components"]], ["Basic Pay"])
            self.assertEqual(out["printed_totals"]["form_total_pay"], 192030)
            self.assertTrue((run / "fields.json").exists(),
                            "fields.json must be written even though the LPC could not be read")

    def test_the_unread_document_is_recorded_not_silently_dropped(self):
        import tempfile
        from unittest import mock
        from extraction.client import ExtractionError
        import pipeline.extract as X

        form_read = self._extraction(
            {"date_of_birth": {"value": "19-02-1966", "confidence": 0.95},
             "total_pay_printed_rs": 192030, "pay_components": []})

        def fake(image, schema_name="GENERIC_PAGE", **kw):
            if "p007" in str(image):
                raise ExtractionError("p007-000.png: 24 pay rows, 0 amounts")
            return form_read, {"agree": True}

        with tempfile.TemporaryDirectory() as tmp:
            run = self._run_dir(tmp)
            with mock.patch.object(X, "extract_page_confirmed", fake):
                out = X.stage_extract(run)
            unread = out.get("unread_pay_documents") or []
            self.assertEqual(len(unread), 1)
            self.assertEqual(unread[0]["document"], "LPC")
            self.assertEqual(unread[0]["page"], 7)
            self.assertIn("0 amounts", unread[0]["reason"])

    def test_an_unreadable_prescribed_form_still_stops_the_stage(self):
        """Form D-I is the authoritative source. Without it there are no dates, no grade and
        no base, so it is NOT made tolerant along with the supplementary documents."""
        import tempfile
        from unittest import mock
        from extraction.client import ExtractionError
        import pipeline.extract as X

        def fake(image, schema_name="GENERIC_PAGE", **kw):
            raise ExtractionError("p041-000.png: could not obtain two usable reads")

        with tempfile.TemporaryDirectory() as tmp:
            run = self._run_dir(tmp)
            with mock.patch.object(X, "extract_page_confirmed", fake):
                with self.assertRaises(ExtractionError):
                    X.stage_extract(run)
            self.assertFalse((run / "fields.json").exists())

class AnUnrecognisedPayLineReachesTheEngine(unittest.TestCase):
    """``EMOL-08`` was unreachable from the pipeline.

    ``classify_pay_label`` returns ``component='unknown', needs_human=True`` for a label no
    rule matches -- and also ``is_line_item=False``, because such a line must never be
    summed. ``_pay_components`` dropped every non-line-item, so the unknown never became a
    ``PayComponent``, ``Emoluments.needs_human`` stayed False, and the finding could not be
    raised. Where no printed total had been extracted the reconciliation could not catch it
    either, so an unrecognised RECKONABLE component understated a pension for life with
    nothing raised anywhere.

    ``rules/emoluments.py`` had said the opposite in its own docstring throughout: "It raises
    a finding instead (needs_human), matching extraction/classify.py".
    """

    UNKNOWN = "Hill Compensatory Allowance"

    def _components(self, printed_total: int | None = None):
        from pipeline.extract import _pay_components

        return _pay_components({"pay_components": [
            row("Basic Pay", 178_440),
            row(self.UNKNOWN, 9_000),
        ]}, page=41, printed_total=printed_total)

    def test_the_classifier_asks_for_a_human(self):
        from extraction.classify import classify_pay_label

        verdict = classify_pay_label(self.UNKNOWN)
        self.assertEqual(verdict["component"], "unknown")
        self.assertTrue(verdict["needs_human"])

    def test_an_unknown_line_reaches_the_engine(self):
        self.assertIn("unknown", [c.component for c in self._components()])

    def test_an_unknown_line_stops_the_determination(self):
        from rules import reckon, select_pack
        from datetime import date

        emol = reckon(self._components(), select_pack(effective_date=date(2026, 2, 18)))
        self.assertTrue(emol.needs_human)
        self.assertIn("EMOL-08", emol.finding())

    def test_it_is_never_summed_into_either_total(self):
        """Carried is not counted. Summing an unknown allowance overstates a pension;
        excluding it understates one; neither is a call this engine may make."""
        from rules import reckon, select_pack
        from datetime import date

        emol = reckon(self._components(), select_pack(effective_date=date(2026, 2, 18)))
        self.assertEqual(int(emol.reckonable_total), 178_440)
        self.assertEqual(int(emol.excluded_total), 0)
        self.assertEqual([c.printed_label for c in emol.unknown], [self.UNKNOWN])

    def test_the_printed_total_guard_still_drops_a_phantom(self):
        """An unknown row that IS the printed total is still the borrowed-total phantom,
        and carrying it would put an unresolvable finding on every such page."""
        labels = [c.printed_label for c in self._components(printed_total=9_000)]
        self.assertNotIn(self.UNKNOWN, labels)

    def test_page_furniture_is_still_dropped(self):
        """What makes carrying unknowns safe: the model's junk rows have no figure on them,
        and a row with no amount is already gone. These are the real rows from page 41."""
        from pipeline.extract import _pay_components

        out = _pay_components(P041_AS_READ, page=41, printed_total=192030)
        self.assertEqual([c.printed_label for c in out],
                         ["Basic Pay Rs.", "Personal Pay Rs."])

    def test_a_deduction_is_still_dropped(self):
        """Income tax is classified, not unknown, and must stay out of the pay set."""
        from pipeline.extract import _pay_components

        out = _pay_components(P042_AS_READ, page=42, printed_total=353795)
        self.assertNotIn("Income Tax", [c.printed_label for c in out])
        self.assertNotIn("GPF Balance: 62,336.00 (provisional)",
                         [c.printed_label for c in out])


class AMissingFormIsOnlyMissingIfEveryPageWasRead(unittest.TestCase):
    """SOP §4.4 rule 5 / §6.3 rule 10.

    The Auditor must "confirm that every page of the bundle has been accounted for, a
    document reported as missing being reliable only where no page is unaccounted for". The
    determination gap said "No prescribed form was identified in the bundle" flat, and on a
    35-page self-pension bundle where 22 pages had been assigned to no document at all that
    sentence was a claim about the department's paperwork built on our own unread pages. The
    department gets asked for a paper it already sent.
    """

    def _run(self, pages: int, assigned: list[int]):
        import json
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        run = Path(tmp.name)
        (run / "manifest.json").write_text(json.dumps(
            {"pages": [{"page": p} for p in range(1, pages + 1)]}))
        (run / "documents.json").write_text(json.dumps(
            [{"type": "CNIC", "pages": assigned}] if assigned else []))
        return run

    def test_unaccounted_pages_are_counted(self):
        from pipeline.extract import pages_with_no_document

        unread, total = pages_with_no_document(self._run(5, [1, 3]))
        self.assertEqual((unread, total), ([2, 4, 5], 5))

    def test_a_fully_read_bundle_has_none(self):
        from pipeline.extract import pages_with_no_document

        self.assertEqual(pages_with_no_document(self._run(3, [1, 2, 3])), ([], 3))

    def test_an_unreadable_manifest_qualifies_nothing_rather_than_failing(self):
        """This qualifies a message; losing the message to build the qualification is worse."""
        import tempfile

        from pipeline.extract import pages_with_no_document

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.assertEqual(pages_with_no_document(Path(tmp.name)), ([], 0))

    def test_the_gap_says_the_form_may_be_among_the_unread_pages(self):
        from pipeline.extract import ExtractionGap, stage_determine

        run = self._run(35, [1, 2, 3])
        with self.assertRaises(ExtractionGap) as caught:
            stage_determine(run)
        message = str(caught.exception)
        self.assertIn("NOT a finding that the form is absent", message)
        self.assertIn("32 of 35 pages", message)
        self.assertIn("SOP §4.4 rule 5", message)

    def test_a_fully_read_bundle_gets_no_such_qualification(self):
        """A bundle every page of which was read really does lack the form, and saying so
        with a caveat attached would teach an officer to discount the caveat."""
        from pipeline.extract import ExtractionGap, stage_determine

        run = self._run(3, [1, 2, 3])
        with self.assertRaises(ExtractionGap) as caught:
            stage_determine(run)
        message = str(caught.exception)
        self.assertIn("No prescribed form was identified", message)
        self.assertNotIn("NOT a finding that the form is absent", message)

    def test_one_unread_page_reads_as_a_page_not_pages(self):
        from pipeline.extract import ExtractionGap, stage_determine

        run = self._run(4, [1, 2, 4])
        with self.assertRaises(ExtractionGap) as caught:
            stage_determine(run)
        self.assertIn("(page 3)", str(caught.exception))



if __name__ == "__main__":
    unittest.main()
