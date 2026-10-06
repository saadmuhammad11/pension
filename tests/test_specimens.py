"""The specimen-signature register and the check that reads a sanction against it.

The register's first entry is S&GAD's Additional Secretary (Admn), letter
No.SO.A.III(S&GAD)7-7/2025 of 9 September 2025 (rules/specimens/register.json).
"""

import unittest
from datetime import date

from rules import CaseRecord, PsaSignature, specimens
from rules.flags import AUTH_DEFECT, LOW, MEDIUM, SPECIMEN_CHECK, check_psa_specimen


def record(*sigs):
    return CaseRecord(case_ref="t", case_type="", psa_signatures=tuple(sigs))


def sgad(**kw):
    base = dict(document="FORM_B_I", page=4, signature_present=True, stamp_present=True,
                signer_name=None, designation="Additional Secretary (Admn.)", department="S&GAD",
                stamp_text="Additional Secretary (Admn.) / Govt. of the Punjab / S&GAD",
                date_signed=date(2026, 1, 12), date_signed_raw="12-01-2026",
                signature_image="FORM_B_I-p4.jpg", specimen="SGAD-AS-ADMN-2025-09-09",
                specimen_status="on file")
    base.update(kw)
    return PsaSignature(**base)


class Register(unittest.TestCase):
    def test_the_sgad_specimen_is_on_file_with_its_images(self):
        spec = specimens.load()[0]
        self.assertEqual(spec.post, "Additional Secretary (Admn)")
        self.assertEqual(spec.effective_from, date(2025, 9, 9))
        self.assertEqual(len(spec.images), 3)
        self.assertTrue(all(p.exists() for p in spec.images))

    def test_lookup_by_department_post_and_date(self):
        spec, why = specimens.lookup("Govt. of the Punjab / S & G A D", "Addl. Secretary (Admn)", date(2026, 3, 1))
        self.assertEqual(spec.id, "SGAD-AS-ADMN-2025-09-09")
        self.assertEqual(why, "on file")

    def test_sgad_as_a_scan_reads_it(self):
        for text in ("S R G A D", "S & G A D", "S and GAD", "Services & General Administration Department"):
            self.assertTrue(specimens.for_department(text), text)
        self.assertFalse(specimens.for_department("Sargodha Division"))

    def test_what_is_not_on_file_says_why(self):
        self.assertEqual(specimens.lookup("School Education Department", "Additional Secretary (Admn)",
                                          date(2026, 1, 1))[1], "department not on file")
        self.assertEqual(specimens.lookup("S&GAD", "Section Officer (Admn-III)", date(2026, 1, 1))[1],
                         "post not on file")
        self.assertEqual(specimens.lookup("S&GAD", "Additional Secretary (Admn)", date(2025, 3, 1))[1],
                         "not in force on 2025-03-01")


class Check(unittest.TestCase):
    def test_a_matching_sanction_is_put_beside_the_specimen_for_the_officer(self):
        [f] = check_psa_specimen(record(sgad()), None)
        self.assertEqual((f.severity, f.flag_class), (LOW, SPECIMEN_CHECK))
        self.assertEqual(f.specimen["signature_image"], "FORM_B_I-p4.jpg")
        self.assertEqual(len(f.specimen["images"]), 3)
        self.assertFalse(f.blocks_ppo)

    def test_another_name_under_the_signature_is_a_defect(self):
        [f] = check_psa_specimen(record(sgad(signer_name="Muhammad Asif Khan")), None)
        self.assertEqual((f.severity, f.flag_class), (MEDIUM, AUTH_DEFECT))
        self.assertIn("Muhammad Asif Khan", f.finding)
        self.assertEqual(f.owner, "DEPARTMENT")

    def test_the_post_read_as_a_name_is_not_another_name(self):
        [f] = check_psa_specimen(record(sgad(signer_name="Additional Secretary (Admn.)")), None)
        self.assertEqual(f.flag_class, SPECIMEN_CHECK)

    def test_the_specimen_officers_own_name_is_not(self):
        [f] = check_psa_specimen(record(sgad(signer_name="(Mudassir Ahmed Shah)")), None)
        self.assertEqual(f.flag_class, SPECIMEN_CHECK)

    def test_a_stamp_for_another_post_is_a_defect(self):
        [f] = check_psa_specimen(record(sgad(stamp_text="Section Officer (Admn-III) / S&GAD")), None)
        self.assertEqual(f.flag_class, AUTH_DEFECT)

    def test_the_ocr_stamp_is_preferred_to_the_vision_misread(self):
        [f] = check_psa_specimen(record(sgad(stamp_text="S R G A N",
                                            stamp_ocr="Additional Secretary (Admn.) Govt. of the Punjab S&GAD")), None)
        self.assertEqual(f.flag_class, SPECIMEN_CHECK)

    def test_no_signature_or_stamp_is_a_defect(self):
        [f] = check_psa_specimen(record(sgad(signature_present=False, stamp_present=False,
                                            signature_image=None)), None)
        self.assertEqual(f.severity, MEDIUM)
        self.assertIn("no signature", f.finding)

    def test_an_sgad_post_with_no_specimen_asks_for_one(self):
        sig = sgad(designation="Deputy Secretary (Admn)", stamp_text="Deputy Secretary (Admn) / S&GAD",
                   specimen=None, specimen_status="post not on file")
        [f] = check_psa_specimen(record(sig), None)
        self.assertEqual((f.severity, f.flag_class), (LOW, SPECIMEN_CHECK))
        self.assertIn("Deputy Secretary", f.finding)

    def test_a_sanction_older_than_the_specimen_says_so(self):
        sig = sgad(date_signed=date(2025, 5, 2), date_signed_raw="02-05-2025", specimen=None,
                   specimen_status="not in force on 2025-05-02")
        [f] = check_psa_specimen(record(sig), None)
        self.assertIn("before", f.finding)

    def test_a_department_with_no_specimen_raises_nothing(self):
        sig = sgad(department="School Education Department", designation="District Officer (SE)",
                   stamp_text="Pension Sanctioning Authority", specimen=None,
                   specimen_status="department not on file")
        self.assertEqual(check_psa_specimen(record(sig), None), [])

    def test_the_side_by_side_reaches_the_report(self):
        [f] = check_psa_specimen(record(sgad()), None)
        self.assertEqual(f.to_dict()["specimen"]["id"], "SGAD-AS-ADMN-2025-09-09")


if __name__ == "__main__":
    unittest.main()
