"""A form scanned sideways is read upright. extraction/orient.py.

    python3 -m unittest tests.test_orientation -v

The vision reader is stubbed: it answers a sane form for one rotation and the garbage the real
model produced on the sideways Disabled Son form for the others. Nothing here touches a model.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _v(value, conf=0.9):
    return {"value": value, "confidence": conf, "unreadable_reason": None}


#: What the model actually returned for the sideways scan (run e2c24ee825f5, p.4).
SIDEWAYS_READ = {
    "deceased_pensioner_name": _v("M. Hamza General"),
    "claimant_name": _v("M. Hamza General"),
    "prior_family_pensioner_name": _v("M. Hamza General"),
    "claimant_relation": _v("Husband"),
    "date_of_retirement": _v("23-12-97"),
    "date_of_death_of_pensioner": _v("28-2-24"),
    "date_of_death_of_prior_pensioner": _v("28-2-24"),
    "date_of_divorce": _v("20-05-239"),
    "pension_drawn_rs": 17028,
}

#: What the same form says when read the right way up.
UPRIGHT_READ = {
    "deceased_pensioner_name": _v("Mst. Rukhsar Abdul Majeed"),
    "claimant_name": _v("M. Hamza Qureshi"),
    "prior_family_pensioner_name": _v(None),
    "claimant_relation": _v("Son, Disable"),
    "date_of_retirement": _v("1997-12-22"),
    "date_of_death_of_pensioner": _v("2021-02-28"),
    "date_of_death_of_prior_pensioner": _v(None),
    "date_of_divorce": _v(None),
    "pension_drawn_rs": 10475,
    "net_pension_rs": 14836,
    "total_pension_rs": 17028,
}


def _png(path: Path, size: tuple[int, int]) -> Path:
    from PIL import Image
    Image.new("L", size, 255).save(path)
    return path


class ScoringARead(unittest.TestCase):
    def test_the_upright_read_outscores_the_sideways_one(self):
        from extraction.orient import field_sanity_score
        self.assertGreater(field_sanity_score(UPRIGHT_READ), field_sanity_score(SIDEWAYS_READ))

    def test_one_name_in_every_name_field_is_penalised(self):
        from extraction.orient import field_sanity_score
        same = {"a_name": _v("Mst. Ayesha"), "b_name": _v("AYESHA"), "c_name": _v("ayesha,")}
        different = {"a_name": _v("Ayesha"), "b_name": _v("Mazhar"), "c_name": _v("Amna")}
        self.assertLess(field_sanity_score(same), field_sanity_score(different))

    def test_a_date_that_is_not_a_date_costs(self):
        from extraction.orient import field_sanity_score
        self.assertLess(field_sanity_score({"date_x": _v("20-05-239")}),
                        field_sanity_score({"date_x": _v("2021-02-28")}))

    def test_an_empty_read_scores_nothing(self):
        from extraction.orient import field_sanity_score
        self.assertEqual(field_sanity_score({}), 0)


class ChoosingTheImageToRead(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()

    def _reader_that_is_sane_for(self, suffix: str):
        def fake(image, schema):
            return SimpleNamespace(data=UPRIGHT_READ if suffix in Path(image).name
                                   else SIDEWAYS_READ)
        return fake

    def test_a_portrait_page_is_taken_as_upright_without_reading(self):
        from extraction.orient import upright_form_image
        src = _png(self.dir / "p004.png", (1554, 2199))
        calls = []
        chosen = upright_form_image(src, 4, schema_name="FORM_D_II",
                                    read=lambda *a: calls.append(a))
        self.assertEqual(chosen, src)
        self.assertEqual(calls, [])
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["p004.png"])

    def test_a_landscape_form_is_read_from_the_rotation_that_makes_sense(self):
        from PIL import Image
        from extraction.orient import upright_form_image
        src = _png(self.dir / "p004.png", (2199, 1554))
        notes = []
        chosen = upright_form_image(src, 4, schema_name="FORM_D_II", progress=notes.append,
                                    read=self._reader_that_is_sane_for("rot090"))
        self.assertEqual(chosen.name, "p004-rot090.png")
        with Image.open(chosen) as im:
            self.assertEqual(im.size, (1554, 2199))
        self.assertTrue(notes and "upright at 90 degrees" in notes[0])

    def test_the_other_way_round_too(self):
        from extraction.orient import upright_form_image
        src = _png(self.dir / "p004.png", (2199, 1554))
        self.assertEqual(
            upright_form_image(src, 4, schema_name="FORM_D_II",
                               read=self._reader_that_is_sane_for("rot270")).name,
            "p004-rot270.png")

    def test_a_landscape_page_that_reads_well_as_it_is_stays(self):
        from extraction.orient import upright_form_image
        src = _png(self.dir / "p004.png", (2199, 1554))
        chosen = upright_form_image(src, 4, schema_name="FORM_D_II",
                                    read=self._reader_that_is_sane_for("p004.png"))
        self.assertEqual(chosen, src)

    def test_a_tie_keeps_the_page_as_scanned(self):
        from extraction.orient import upright_form_image
        src = _png(self.dir / "p004.png", (2199, 1554))
        chosen = upright_form_image(src, 4, schema_name="FORM_D_II",
                                    read=lambda *a: SimpleNamespace(data=UPRIGHT_READ))
        self.assertEqual(chosen, src)

    def test_a_failed_read_is_not_a_vote(self):
        from extraction.orient import upright_form_image
        src = _png(self.dir / "p004.png", (2199, 1554))

        def flaky(image, schema):
            if "rot270" in Path(image).name:
                raise RuntimeError("service down")
            return self._reader_that_is_sane_for("rot090")(image, schema)
        self.assertEqual(upright_form_image(src, 4, schema_name="FORM_D_II", read=flaky).name,
                         "p004-rot090.png")


class TheRelationClauseOfTheDisabledSonForm(unittest.TestCase):
    def test_son_comma_disable_is_the_disabled_child_column(self):
        from rules import suggest_variant
        from rules.case_type import FAMILY_PENSION_DEATH_AFTER_RETIREMENT
        got = suggest_variant(FAMILY_PENSION_DEATH_AFTER_RETIREMENT, "",
                              claimant_relation="Son, Disable")
        self.assertEqual(got.variant, "DISABLED_CHILD_SIBLING")

    def test_and_the_disabled_child_share(self):
        from rules.dii import _share_key_for
        self.assertEqual(_share_key_for("Son, Disable"), "disabled_child_percent")


if __name__ == "__main__":
    unittest.main()
