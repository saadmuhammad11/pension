"""The frame's address changes when the screens behind it change.

24 Oct 2026. A Senior Auditor saw the Checklist tab and the AG's desk did not, for a day,
through three attempts to explain it as something else. The frame's address carries the
officer's band -- officer=da for a Senior Auditor, officer=dag for the AG's desk -- and a
browser caches per address, so each desk held its own copy of the module and aged it
separately. One desk had the screens of an hour ago and the next those of the day before,
which reads exactly like a tab that exists for one officer and not another.

The module's own files are addressed by their contents now, and its index.html is never
stored, which fixes every load after the next one. This fixes the next one: the address of
the frame itself carries the version, so a desk holding yesterday's copy is pointed at an
address it has never seen and cannot answer from its cache.

    python3 -m unittest tests.test_gpf_frame_address_follows_the_screens -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import gpf_bridge  # noqa: E402


class ThePortalPutsItInTheFramesAddress(unittest.TestCase):

    def _embed(self, band: str, web: str | None) -> str:
        """The one line of api.v2.case_gpf that builds the address."""
        out = {"officer": band}
        well = {"web": web} if web is not None else {}
        gpf_case_id = "final-scan-abc"
        w = (well or {}).get("web") or ""
        return (f"/gpf/?embed=1&officer={out['officer']}"
                + (f"&v={w}" if w else "")
                + f"#/case/{gpf_case_id}")

    def test_the_version_is_in_it(self) -> None:
        self.assertEqual(self._embed("dag", "abc123"),
                         "/gpf/?embed=1&officer=dag&v=abc123#/case/final-scan-abc")

    def test_both_bands_get_the_same_version(self) -> None:
        """Which is the point: the bands differ in the address, so without this they age
        apart."""
        da, dag = self._embed("da", "abc123"), self._embed("dag", "abc123")
        self.assertNotEqual(da, dag)
        self.assertIn("v=abc123", da)
        self.assertIn("v=abc123", dag)

    def test_a_changed_screen_is_a_changed_address(self) -> None:
        self.assertNotEqual(self._embed("dag", "abc123"), self._embed("dag", "def456"))

    def test_a_module_that_did_not_answer_still_gives_a_usable_address(self) -> None:
        """health() returns None when the module is down; the frame is still addressable."""
        self.assertEqual(self._embed("dag", None),
                         "/gpf/?embed=1&officer=dag#/case/final-scan-abc")

    def test_the_real_route_builds_it_this_way(self) -> None:
        from api import v2
        src = Path(v2.__file__).read_text(encoding="utf-8")
        block = src[src.index('out["embed_url"]') - 900:src.index('out["embed_url"]') + 400]
        self.assertIn('well = gpf_bridge.health()', src)
        self.assertIn('(well or {}).get("web")', block)
        self.assertIn('f"&v={web}" if web else ""', block)

    def test_health_is_fetched_once_and_used_twice(self) -> None:
        """module_up and the version come from the same call: the frame polls this route
        every few seconds and a second round trip for a hash would be paid every time."""
        from api import v2
        src = Path(v2.__file__).read_text(encoding="utf-8")
        # "def case_gpf" is a prefix of case_gpf_action, case_gpf_cure, case_gpf_page and
        # three more, all of which come first -- the signature disambiguates them.
        start = src.index("def case_gpf(case_id")
        body = src[start:src.index("\n@router", start)]
        self.assertEqual(body.count("gpf_bridge.health()"), 1)
        self.assertIn('"module_up": well is not None', body)


if __name__ == "__main__":
    unittest.main()
