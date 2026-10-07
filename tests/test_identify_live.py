"""Live check of pipeline stage 3 against the vision service. Skips when it is unreachable.

Separated from ``test_golden_case`` on purpose. That suite is hermetic -- no GPU, no network,
3 ms -- because BUILD §6.2 requires the deterministic layer to be recomputable anywhere. This
file is the opposite: it exercises the one part of stage 3 that genuinely needs a model, and it
skips rather than fails when the service is down, because the model services are shared
infrastructure this project does not own.

It exists because the deterministic tests passed while the model call was confidently wrong.
On 2026-09-04 a synthetic Form D-I was identified as ``DEPUTATION_CHALLANS`` at 0.90 and a page
headed "LAST PAY CERTIFICATE" answered ``OTHER`` at 0.99 -- while quoting that exact heading as
its own evidence. Nothing in the unit suite could have caught that.

Run:  python3 -m unittest tests.test_identify_live -v
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# So the file runs directly as well as under `-m unittest` from the project root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest
import urllib.error
import urllib.request

VISION_HEALTH = "http://192.168.1.1:8011/health"
# Rendered into a temporary folder, never into the tree: a stale render under tests/fixtures/
# kept a real claimant's name after the code was scrubbed (found 7 Oct 2026, N12).


def vision_available() -> bool:
    try:
        with urllib.request.urlopen(VISION_HEALTH, timeout=4) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def make_pages(directory: Path) -> dict[str, Path]:
    """Render three synthetic pages. Crude on purpose -- the point is the printed heading.

    Synthetic rather than real scan pages because the real 46-page case contains a named
    person's CNIC, bank account and family records, and those do not belong in a test fixture
    committed to a repository (BRAIN §15.4).
    """
    from PIL import Image, ImageDraw

    directory.mkdir(parents=True, exist_ok=True)
    specs = {
        "form_d_i": [
            "GOVERNMENT OF THE PUNJAB",
            "FORM D-I",
            "APPLICATION FOR FAMILY PENSION - DEATH IN SERVICE",
            "1. Name of deceased Government Servant: Mst. Nargas Waqar",
            "   Personnel No: 90000857",
            "3. (iv) Total qualifying service: 32 years",
            "5. No Demand / Recovery was due",
            "   Total Pay 192030",
        ],
        "lpc": [
            "LAST PAY CERTIFICATE",
            "Office of the District Accounts Officer, Lahore",
            "Name: Nargas Waqar    Personnel No: 90000853",
            "Basic Pay 178440   Personal Pay 13590",
            "ROP recoverable: 126355",
        ],
        "frc": [
            "NATIONAL DATABASE & REGISTRATION AUTHORITY",
            "FAMILY REGISTRATION CERTIFICATE",
            "Mahnoor Waqar    Daughter    Married",
            "Usman Waqar     Son         Married",
        ],
    }
    out = {}
    for name, lines in specs.items():
        im = Image.new("RGB", (760, 460), "white")
        d = ImageDraw.Draw(im)
        for i, line in enumerate(lines):
            d.text((40, 30 + i * 34), line, fill="black")
        d.rectangle([30, 15, 730, 445], outline="black")
        path = directory / f"{name}.png"
        im.save(path)
        out[name] = path
    return out


@unittest.skipUnless(vision_available(), "vision service on :8011 is not reachable")
class IdentifyLive(unittest.TestCase):
    """The printed heading must map to the right token."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="identify-live-")
        cls.addClassCleanup(cls._tmp.cleanup)
        try:
            cls.pages = make_pages(Path(cls._tmp.name))
        except ImportError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"Pillow unavailable: {exc}") from exc

    def _identify(self, name: str, page: int):
        from extraction.identify import identify_page

        return identify_page(self.pages[name], page=page, timeout_s=300)

    def test_prescribed_form_is_identified_by_its_form_number(self):
        """§4.1 rule 1 depends entirely on this: the form decides the case type."""
        r = self._identify("form_d_i", 19)
        self.assertEqual(r.document_type, "FORM_D_I")
        self.assertGreaterEqual(r.confidence, 0.80)
        self.assertFalse(r.needs_human)

    def test_last_pay_certificate_is_not_other(self):
        """Regression: this answered OTHER at 0.99 while quoting its own heading."""
        r = self._identify("lpc", 6)
        self.assertEqual(r.document_type, "LPC")
        self.assertGreaterEqual(r.confidence, 0.80)

    def test_frc_is_not_a_file_cover(self):
        """Regression: this answered FILE_COVER at 0.95."""
        r = self._identify("frc", 10)
        self.assertEqual(r.document_type, "NADRA_FRC")
        self.assertGreaterEqual(r.confidence, 0.80)

    def test_identified_pages_drive_the_case_type(self):
        """End to end: pages -> documents -> case type, model then rules."""
        from extraction.identify import assemble_documents
        from rules import CaseRecord, classify_case_type

        identities = [
            self._identify("form_d_i", 19),
            self._identify("lpc", 6),
            self._identify("frc", 10),
        ]
        docs = assemble_documents(identities)
        self.assertIn("FORM_D_I", [d.type for d in docs])

        record = CaseRecord(case_ref="LIVE", case_type="", documents=docs)
        result = classify_case_type(record)
        self.assertEqual(result.case_type, "FAMILY_PENSION_DEATH_IN_SERVICE")
        self.assertEqual(result.prescribed_form, "D-I")


if __name__ == "__main__":
    unittest.main(verbosity=2)
