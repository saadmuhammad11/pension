"""Stage "verify" reads its pages at once, and gets exactly what the sequential loop got.

Until 19 Oct 2026 verify_with_ocr was a plain for-loop: measured at 1.00x parallelism -- 89.4s
of model work in 89.5s of wall clock -- while the OCR server reported one request running and
nothing queued. The pages are independent, so they now go through a pool.

Two things could break and neither is visible in a total: the bundle's page ORDER, which decides
how pages group into documents, and the form_text dictionary stage 6 reads a form's own wording
from. Both are rebuilt on the calling thread, and this test holds that to the sequential result.

    python3 -m unittest tests.test_verify_concurrency -v
"""
from __future__ import annotations

import random
import sys
import time
import unittest
from unittest import mock

from extraction import identify as I

_FORM = next(iter(I._FORM_NUMBER))
#: One of each branch verify_with_ocr takes, repeated: prescribed form, pay document, proforma,
#: promotable label, and types it passes straight through.
_KINDS = (_FORM, "LPC", "QUALIFYING_SERVICE_PROFORMA", "ANNEX_A", "CNIC", "OTHER",
          "SALARY_STATEMENT", "AFFIDAVIT", "SUPERANNUATION_ORDER", "PENSION_SLIP")


def _Text(page: int):
    """A real PageText: verify_with_ocr now asks it whether the reader looped
    (looks_degenerate), which needs the normalised view a bare stub does not have."""
    from extraction.ocr import OCR_MODEL, PageText
    # Varied words, so the degeneracy guard sees a genuine reading rather than a loop.
    body = " ".join(f"line{page}-{i} printed text on the page" for i in range(12))
    return PageText(page=page, text=body, model=OCR_MODEL)


def _jitter() -> None:
    """Uneven work, so a pool that returned results in completion order would reorder them."""
    time.sleep(random.uniform(0.002, 0.02))


class VerifyConcurrency(unittest.TestCase):
    def _identities(self, n: int = 40) -> list[I.PageIdentity]:
        return [I.PageIdentity(page=i + 1, document_type=_KINDS[i % len(_KINDS)], confidence=1.0,
                               evidence=f"e{i}", is_first_page=True) for i in range(n)]

    def _run_at(self, conc: int, idents):
        import extraction.ocr as O

        def reclaim(ident, image):
            _jitter()
            promoted = I.replace(ident, promoted_from=ident.document_type) if ident.page % 2 else ident
            return promoted, f"PROMO-{ident.page}" * 10

        with mock.patch.object(I, "VERIFY_CONCURRENCY", conc), \
             mock.patch.object(I, "_deny_pay_claim_on_a_card",
                               lambda i, img: (_jitter(), I.replace(i, evidence=f"denied-{i.page}"))[1]), \
             mock.patch.object(I, "_verify_proforma_claim",
                               lambda i, img: (_jitter(), I.replace(i, evidence=f"pro-{i.page}"))[1]), \
             mock.patch.object(I, "_reclaim_form", reclaim), \
             mock.patch.object(I, "_verify_form_claim",
                               lambda i, n, t: I.replace(i, evidence=f"verified-{i.page}")), \
             mock.patch.object(O, "ocr_page", lambda image, page, **kw: (_jitter(), _Text(page))[1]), \
             mock.patch.object(O, "forms_printed_on", lambda t: []), \
             mock.patch.object(O, "form_titles_on", lambda t: []):
            out = I.verify_with_ocr(idents, lambda p: f"/img/p{p}.png")
            return out, dict(I.verify_with_ocr.form_text)

    def test_every_concurrency_matches_the_sequential_result(self) -> None:
        idents = self._identities()
        want_out, want_text = self._run_at(1, idents)
        self.assertEqual(len(want_out), len(idents))
        self.assertTrue(want_text, "the fixture must exercise the form_text branches")
        for conc in (2, 4, 8, 16):
            with self.subTest(concurrency=conc):
                out, text = self._run_at(conc, idents)
                self.assertEqual([i.page for i in out], [i.page for i in want_out])
                self.assertEqual(out, want_out)
                self.assertEqual(text, want_text)

    def test_the_pool_is_configurable_and_never_below_one(self) -> None:
        for given, expect in (("8", 8), ("1", 1), ("0", 1), ("", 4), (None, 4)):
            env = {} if given is None else {"PENSION_VERIFY_CONCURRENCY": given}
            with mock.patch.dict("os.environ", env, clear=False):
                if given is None:
                    import os
                    os.environ.pop("PENSION_VERIFY_CONCURRENCY", None)
                import importlib
                mod = importlib.reload(I)
                self.assertEqual(mod.VERIFY_CONCURRENCY, expect, f"for {given!r}")
        importlib.reload(I)


if __name__ == "__main__":
    unittest.main()
