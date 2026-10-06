"""A NADRA FRC must have been issued within six months of the case's submission. FRC-09.

AG Punjab office practice, stated 17 September 2026 (``rules/checklist.py FRC_MAX_AGE_MONTHS``).
The certificate's printed issue date is read at extraction and put on the timeline as
``FRC_ISSUED``; the checklist marks AG-06 DEFECTIVE and the battery raises ``DOC-STALE`` HIGH.

Standard library only; no GPU and no network.
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _record(frc_dates: dict[int, date], submitted: date | None, received: date | None = None,
            variant: str = "WIDOW"):
    from rules import CaseRecord, Document
    from rules.caserecord import Source, TimelineEvent
    timeline = [TimelineEvent("FRC_ISSUED", d, Source(p, "NADRA_FRC")) for p, d in frc_dates.items()]
    if received:
        timeline.append(TimelineEvent("RECEIVED_AT_AG", received))
    return CaseRecord(
        case_ref="T-FRC", case_type="FAMILY_PENSION_DEATH_AFTER_RETIREMENT",
        documents=tuple(Document("NADRA_FRC", (p,)) for p in frc_dates),
        timeline=tuple(timeline), submitted_date=submitted, case_variant=variant,
    )


def _pack():
    from rules.loader import select_pack
    return select_pack(effective_date=date(2026, 2, 18))


class MonthArithmetic(unittest.TestCase):
    def test_six_months_later_and_short_months_clamp(self):
        from rules.checklist import add_months
        self.assertEqual(add_months(date(2025, 12, 23), 6), date(2026, 6, 23))
        self.assertEqual(add_months(date(2026, 8, 31), 6), date(2027, 2, 28))
        self.assertEqual(add_months(date(2024, 8, 29), 6), date(2025, 2, 28))
        self.assertEqual(add_months(date(2023, 8, 29), 6), date(2024, 2, 29))


class WhichCertificatesAreStale(unittest.TestCase):
    def test_a_certificate_within_six_months_is_not_stale(self):
        from rules.checklist import stale_frcs
        # Ghulam Zainab's bundle: FRC 29-07-2026, case forwarded in 2026 -- within six months.
        self.assertEqual(stale_frcs(_record({6: date(2026, 7, 29)}, date(2026, 8, 20))), [])

    def test_the_last_valid_day_is_exactly_six_months_later(self):
        from rules.checklist import stale_frcs
        self.assertEqual(stale_frcs(_record({8: date(2025, 12, 23)}, date(2026, 6, 23))), [])
        stale = stale_frcs(_record({8: date(2025, 12, 23)}, date(2026, 6, 24)))
        self.assertEqual([x["page"] for x in stale], [8])
        self.assertEqual(stale[0]["valid_until"], date(2026, 6, 23))
        self.assertEqual(stale[0]["days_over"], 1)

    def test_the_khan_bahadur_certificate_is_stale_against_its_forwarding_letter(self):
        from rules.checklist import stale_frcs
        # FRC issued 10-11-2025; forwarding letter 06-07-2026: seven months and change.
        stale = stale_frcs(_record({8: date(2025, 11, 10)}, date(2026, 7, 6)))
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["reference_label"], "the date the department forwarded the case")

    def test_receipt_at_the_ag_is_preferred_to_the_forwarding_date(self):
        from rules.checklist import stale_frcs
        stale = stale_frcs(_record({8: date(2025, 11, 10)}, date(2026, 3, 1),
                                   received=date(2026, 7, 6)))
        self.assertEqual(stale[0]["reference_label"], "receipt at the Accountant General")

    def test_a_certificate_issued_after_submission_is_not_stale(self):
        from rules.checklist import stale_frcs
        self.assertEqual(stale_frcs(_record({8: date(2026, 9, 1)}, date(2026, 7, 6))), [])

    def test_no_submission_date_means_not_measured(self):
        from rules.checklist import stale_frcs
        self.assertEqual(stale_frcs(_record({8: date(2019, 1, 1)}, None)), [])

    def test_each_certificate_page_is_judged_on_its_own_date(self):
        from rules.checklist import stale_frcs
        stale = stale_frcs(_record({6: date(2025, 1, 1), 7: date(2026, 7, 1)}, date(2026, 7, 6)))
        self.assertEqual([x["page"] for x in stale], [6])


class WhatTheOfficerSees(unittest.TestCase):
    def test_the_flag_is_high_names_the_page_and_asks_for_a_fresh_certificate(self):
        from rules.flags import DOC_STALE, HIGH, check_frc_currency
        flags = check_frc_currency(_record({8: date(2025, 11, 10)}, date(2026, 7, 6)), _pack())
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual((f.severity, f.flag_class, f.owner), (HIGH, DOC_STALE, "DEPARTMENT"))
        self.assertTrue(f.blocks_ppo)
        self.assertFalse(f.affects_determination)
        self.assertIn("p.8", f.title)
        self.assertIn("2025-11-10", f.title)
        self.assertIn("2026-05-10", f.finding)          # valid to
        self.assertIn("fresh NADRA FRC", f.required_action)
        self.assertEqual([s.page for s in f.asserted], [8])

    def test_a_self_pension_bundle_is_not_flagged_for_a_certificate_it_need_not_carry(self):
        from rules.flags import check_frc_currency
        # The Revised Pension bundle: FRC of 12-08-2024 in a FRESH_SELF case. AG-06 does not
        # apply to that column, so its age is not a defect.
        rec = _record({15: date(2024, 8, 12)}, date(2026, 6, 10), variant="FRESH_SELF")
        self.assertEqual(check_frc_currency(rec, _pack()), [])
        # ...but with the column unknown it is judged, and a widow's case certainly is.
        self.assertEqual(len(check_frc_currency(
            _record({15: date(2024, 8, 12)}, date(2026, 6, 10), variant=None), _pack())), 1)

    def test_the_flag_is_in_the_battery_and_a_fresh_certificate_raises_nothing(self):
        from rules.flags import BATTERY, check_frc_currency, run_battery
        self.assertIn(check_frc_currency, BATTERY)
        fresh = _record({6: date(2026, 7, 29)}, date(2026, 8, 20))
        self.assertEqual([f for f in run_battery(fresh, _pack()) if f.flag_class == "DOC-STALE"], [])

    def test_ag_06_is_defective_not_merely_present(self):
        from rules.checklist import DEFECTIVE, PRESENT, run_checklist
        stale = run_checklist(_record({8: date(2025, 11, 10)}, date(2026, 7, 6)), variant="WIDOW")
        item = next(i for i in stale.items if i.id == "AG-06")
        self.assertEqual(item.status, DEFECTIVE)
        self.assertIn("fresh NADRA FRC", item.reason)
        fresh = run_checklist(_record({8: date(2026, 5, 10)}, date(2026, 7, 6)), variant="WIDOW")
        self.assertEqual(next(i for i in fresh.items if i.id == "AG-06").status, PRESENT)


if __name__ == "__main__":
    unittest.main()
