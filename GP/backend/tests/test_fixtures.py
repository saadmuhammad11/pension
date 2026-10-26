"""Acceptance: the rules engine must reproduce the corpus results exactly.

Ground truth (`ground_truth.json`) is the per-check id -> status map produced by
the prototype's own engine for all eight cases, with and without SAP. It agrees
with the fixture table in spec §16.2. A build that does not match is not working.
"""
import json
from pathlib import Path

import pytest

from gpf import evaluate, lists
from gpf.fixtures import all_case_keys, load_case

GROUND_TRUTH = json.loads((Path(__file__).parent / "ground_truth.json").read_text(encoding="utf-8"))

# Spec §16.2 headline counts: (hard, adv/observation, conf/verify, sap).
#
# AMENDED 21 Oct 2026, when QR checking went out of scope (rules_common.py). Thirteen QR rows
# leave the corpus and three cases lose advisories with them:
#
#     fp-death      4 -> 1 advisories   (QR: death cert, decline, FRC, old CNIC, widow CNIC)
#     fp-dismissal  4 -> 2 advisories   (QR: CNIC back, e-stamp, order)
#     residual      1 -> 0 advisories   (QR: CNIC back, notification barcode)
#
# NO REAL EXAMINATION CHANGES. These fixtures carry canned QR facts; a scan read on the box
# does not, because the pipeline is wired to NullBarcodeDecoder and F["qr"] is always empty.
# So the corpus has been asserting advisories that no deployed build has ever raised, and this
# amendment makes the acceptance suite describe the engine that actually runs. If the decoder
# is ever wired, these rows and these counts come back with it.
# One verification fewer on every fixture from 26 Oct 2026: the DOA check is off at the
# office's asking (gpf/rules_common.py). It raised one task per signature reading saying the
# authority was not yet on the DOA register and no specimen was on file -- true, and not
# clearable by an officer, because the register waits on a list the office has not supplied.
# It produced no hard stop on any fixture: checked fixture by fixture, the third figure is
# the only one that moves, and it moves by exactly the number of signatures that fixture
# carries -- one on most, two on the advances and the balance transfer.
SPEC_16_2 = {
    "fp-non-gazetted": (0, 3, 4, 0),
    "fp-death": (4, 1, 6, 0),
    "fp-dismissal": (0, 2, 5, 0),
    "missing-credits": (1, 1, 0, 4),
    "residual": (1, 0, 1, 0),
    "refundable": (0, 2, 2, 0),
    "non-refundable": (0, 2, 2, 0),
    "balance-transfer": (0, 0, 0, 5),
}


def _id_status(results):
    return sorted([r["id"], r["status"]] for r in results)


@pytest.mark.parametrize("key", list(SPEC_16_2))
def test_per_check_status_with_sap(key):
    got = _id_status(evaluate(load_case(key)))
    assert got == sorted(GROUND_TRUTH[key]["withSap"])


@pytest.mark.parametrize("key", list(SPEC_16_2))
def test_per_check_status_without_sap(key):
    got = _id_status(evaluate(load_case(key, without_sap=True)))
    assert got == sorted(GROUND_TRUTH[key]["withoutSap"])


@pytest.mark.parametrize("key,expected", SPEC_16_2.items())
def test_spec_16_2_headline_counts(key, expected):
    results = evaluate(load_case(key))
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    hard = counts.get("hard", 0)
    adv = counts.get("adv", 0)
    conf = counts.get("conf", 0)
    sap = counts.get("sap", 0)
    assert (hard, adv, conf, sap) == expected


def test_without_sap_waits_never_passes():
    """Removing SAP must turn SAP-dependent checks to `sap`, never silently `ok`."""
    for key in all_case_keys():
        results = evaluate(load_case(key, without_sap=True))
        by_id = {r["id"]: r["status"] for r in results}
        # SAP pay slip / report can never be satisfied without an extract.
        assert by_id.get("SAP-PAYSLIP") == "sap"
        assert by_id.get("SAP-RECALC") == "sap"


def test_lists_partition_is_complete():
    for key in all_case_keys():
        results = evaluate(load_case(key))
        L = lists(results)
        # obs = hard + adv, and every result lands in exactly one status bucket.
        assert len(L["obs"]) == len(L["hard"]) + len(L["adv"])
        total = len(L["obs"]) + len(L["conf"]) + len(L["sap"]) + len(L["ok"])
        na = sum(1 for r in results if r["status"] == "na")
        assert total + na == len(results)
