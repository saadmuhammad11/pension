"""The delegation-of-authority register. Build specification §8, §17.

The §17 row is "DOA lookup on designation strings seen in the corpus: every corpus signatory
matched to its authority", and that is the first class below. The rest hold the two
prohibitions §8 and §14 impose on this layer: a provisional register never raises a hard stop
(§14 rule 7), and nothing here ever decides whether ink matches ink (§14 rule 6).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gpfund.rules                                                        # noqa: F401
from gpfund import CORPUS_ORDER, evaluate, load_corpus_case
from gpfund.corpus import provisional_doa
from gpfund.doa import (
    AUTHORITY_NOT_LISTED,
    FINAL,
    LISTED_NO_SPECIMEN,
    LISTED_WITH_SPECIMEN,
    SIGNATORY_NOT_LISTED,
    Register,
    normalise,
    score,
    use_register,
)


class EveryCorpusSignatoryMatchesItsAuthority(unittest.TestCase):
    """§17. Ten authorities, built from the signatories in the eight case files (§8.5)."""

    def setUp(self) -> None:
        self.register = Register(provisional_doa())

    def test_every_signature_in_the_corpus_finds_its_authority(self):
        seen = 0
        for slug in CORPUS_ORDER:
            facts = load_corpus_case(slug)
            for signature in facts.signatures:
                if signature.get("role") not in ("sanctioning", "ddo", "certifying"):
                    continue
                seen += 1
                with self.subTest(case=slug, signature=signature.get("id")):
                    match = self.register.lookup(signature.get("authority"),
                                                 signature.get("signedBy"))
                    self.assertNotEqual(
                        match.status, AUTHORITY_NOT_LISTED,
                        f"{slug}/{signature.get('id')}: {signature.get('authority')!r} is not on "
                        f"the provisional register, which was built from these very cases")
        # Eleven signatures across the eight cases: §8.5 lists ten AUTHORITIES, and the
        # refundable case puts two of them under the same one (the sanction and Form 05
        # are both signed by SP Headquarters for the DIG Operations).
        self.assertEqual(seen, 11, "the corpus carries eleven signatures for the register")

    def test_the_one_unidentified_signatory_is_reported_as_such(self):
        """The balance-transfer proforma carries a DDO signature with no stamp, name or date.

        Not listed, and correctly so -- there is nothing to match. §8.5 records it as a
        signatory seen in the corpus precisely so the gap is visible.
        """
        facts = load_corpus_case("balance-transfer")
        ddo = next(s for s in facts.signatures if s["id"] == "ddo")
        match = self.register.lookup(ddo["authority"], ddo["signedBy"])
        self.assertEqual(match.status, SIGNATORY_NOT_LISTED)
        self.assertIsNotNone(match.authority)

    def test_signing_for_an_authority_is_matched_to_the_person_not_the_authority(self):
        """SP Headquarters signs FOR the DIG Operations. §8.3 step 1 drops the "for", and the
        person who actually signed is looked up -- matching the DIG instead would record the
        wrong hand on the case."""
        match = self.register.lookup(
            "Deputy Inspector General of Police, Operations, Lahore", "SP Headquarters")
        self.assertEqual(match.signatory.post, "SP Headquarters")
        self.assertTrue(match.signatory.may_sign_for_authority)
        self.assertIn("authorised to sign for", match.sentence())

    def test_an_authority_signing_in_its_own_name_says_so(self):
        match = self.register.lookup("Chief Traffic Officer, Lahore", "Chief Traffic Officer, Lahore")
        self.assertFalse(match.signatory.may_sign_for_authority)
        self.assertIn("signing in own name", match.sentence())

    def test_no_signatory_matches_another_authority(self):
        """The threshold has to separate, not merely match. Every corpus signature is tried
        against every OTHER authority and must fail."""
        signatures = [(slug, s) for slug in CORPUS_ORDER
                      for s in load_corpus_case(slug).signatures
                      if s.get("role") in ("sanctioning", "ddo", "certifying")]
        for slug, signature in signatures:
            own = self.register.lookup(signature["authority"], signature["signedBy"])
            if own.authority is None:
                continue
            for authority in self.register.authorities:
                if authority.id == own.authority.id:
                    continue
                with self.subTest(case=slug, signature=signature["id"], other=authority.id):
                    match = self.register.lookup(authority.authority, signature["signedBy"])
                    self.assertNotEqual(
                        match.status, LISTED_WITH_SPECIMEN,
                        f"{signature['signedBy']!r} matched {authority.authority!r}")

    def test_abbreviations_normalise(self):
        self.assertEqual(normalise("DIG (Operations), Lahore"),
                         "deputy inspector general operations lahore")
        self.assertEqual(normalise("SP HQ f/o DIG"),
                         "superintendent of police headquarters deputy inspector general")

    def test_the_register_being_more_specific_does_not_lower_the_score(self):
        """A stamp reads "Chief Traffic Officer, Lahore"; the register adds "(DDO L04087)".
        Scoring against the shorter word set is what keeps that a full match."""
        self.assertEqual(score("Chief Traffic Officer, Lahore",
                               "Chief Traffic Officer, Lahore (DDO L04087)"), 1.0)


class AProvisionalRegisterNeverStopsACase(unittest.TestCase):
    """§8.3 and §14 rule 7. Open item GPF-O14 until the office supplies its list."""

    def tearDown(self) -> None:
        use_register(None)

    def test_the_corpus_register_is_provisional(self):
        self.assertTrue(Register(provisional_doa()).is_provisional)

    def test_no_signature_in_the_corpus_is_a_hard_stop(self):
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                for result in evaluate(load_corpus_case(slug)):
                    if result.id.startswith("DOA:"):
                        self.assertEqual(
                            result.status, "conf",
                            f"{slug}/{result.id}: a provisional register raised {result.status}")

    def test_no_specimen_exists_for_anyone_yet(self):
        register = Register(provisional_doa())
        for authority in register.authorities:
            for signatory in authority.signatories:
                with self.subTest(signatory=signatory.id):
                    self.assertIsNone(signatory.specimen)

    def test_a_final_register_does_raise_a_hard_stop_for_an_unlisted_signatory(self):
        """The other half: once the office publishes its list, an unapproved hand stops the
        case, and the code that prints is B1-ii on a refundable sanction (§8.3)."""
        payload = provisional_doa()
        payload["status"] = FINAL
        use_register(payload)
        results = {r.id: r for r in evaluate(load_corpus_case("balance-transfer"))}
        self.assertEqual(results["DOA:ddo"].status, "hard")
        self.assertEqual(results["DOA:ddo"].code, "R4")

    def test_an_unlisted_authority_is_never_a_hard_stop_even_on_a_final_register(self):
        """A gap in the office's own register is not a defect in the department's paperwork.
        §14 rule 7 is about exactly this asymmetry."""
        use_register({"status": FINAL, "authorities": []})
        for slug in CORPUS_ORDER:
            with self.subTest(case=slug):
                for result in evaluate(load_corpus_case(slug)):
                    if result.id.startswith("DOA:"):
                        self.assertEqual(result.status, "conf")
                        self.assertIn("not yet on the DOA register", result.finding)

    def test_the_sanctioning_code_follows_what_was_signed(self):
        """B1-ii for a refundable sanction, B2-iv for any other, R4 for a DDO hand. §8.3."""
        payload = provisional_doa()
        payload["status"] = FINAL
        payload["authorities"] = []
        use_register(payload)
        # With no authority listed nothing is hard, so the code is read off the conf result.
        for slug, result_id, expected in (("refundable", "DOA:sanction", "B1-ii"),
                                          ("non-refundable", "DOA:sanction", "B2-iv")):
            with self.subTest(case=slug):
                use_register({"status": FINAL, "authorities": [
                    {"id": "x", "authority": load_corpus_case(slug).signatures[0]["authority"],
                     "signatories": [{"id": "y", "post": "Somebody Else Entirely"}]}]})
                result = next(r for r in evaluate(load_corpus_case(slug))
                              if r.id == result_id)
                self.assertEqual(result.status, "hard")
                self.assertEqual(result.code, expected)


class TheModuleNeverJudgesASignature(unittest.TestCase):
    """§8.4 and §14 rule 6: the officer decides, and the decision becomes a fact."""

    def test_the_signature_comparison_is_presented_not_decided(self):
        result = next(r for r in evaluate(load_corpus_case("refundable")) if r.id == "SIG-CNIC")
        self.assertEqual(result.status, "conf")
        self.assertIn("the officer decides", result.finding)
        self.assertIsNotNone(result.pair)
        self.assertIn("left", result.pair)
        self.assertIn("right", result.pair)

    def test_a_recorded_match_closes_it_and_a_recorded_mismatch_stops_the_case(self):
        base = load_corpus_case("refundable")
        for ok, expected in ((True, "ok"), (False, "hard")):
            with self.subTest(ok=ok):
                facts = base.with_changes(lambda data: data.setdefault("verifications", {}).update(
                    {"SIG-CNIC": {"ok": ok, "by": "Sadia Rehman", "desig": "Accounts Officer",
                                  "at": "T1", "note": "compared side by side"}}))
                result = next(r for r in evaluate(facts) if r.id == "SIG-CNIC")
                self.assertEqual(result.status, expected)
                self.assertIn("Sadia Rehman", result.finding)

    def test_no_similarity_score_appears_anywhere_in_a_result(self):
        """§8.4: a score never passes or fails a signature and is never shown without the
        images. This build computes none at all, so nothing can leak one."""
        for slug in CORPUS_ORDER:
            for result in evaluate(load_corpus_case(slug)):
                with self.subTest(case=slug, result=result.id):
                    self.assertNotIn("similarity", result.finding.lower())
                    if result.doa:
                        self.assertNotIn("score", result.doa)


if __name__ == "__main__":
    unittest.main()
