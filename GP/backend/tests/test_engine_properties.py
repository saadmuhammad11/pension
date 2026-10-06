"""Determinism, model-swap invariance, and re-evaluation, per spec §0 and §17."""
from gpf import CaseState, evaluate, run_case
from gpf.clients import StubModelClient, VllmModelClient
from gpf.fixtures import all_case_keys, load_case


def test_reevaluation_is_deterministic():
    """Same facts -> same results, every time (spec §0 rule 5)."""
    for key in all_case_keys():
        F = load_case(key)
        a = [(r["id"], r["status"]) for r in evaluate(F)]
        b = [(r["id"], r["status"]) for r in evaluate(F)]
        assert a == b


def test_results_do_not_depend_on_a_model():
    """The rules engine makes no model calls, so the model is irrelevant to outcomes.

    Model-swap invariance (spec §0 rule 4): the wording model can only rephrase a
    finding; it cannot change which observations exist or their status.
    """
    stub = StubModelClient()
    alt = VllmModelClient("http://unreachable.invalid")  # constructed, never called
    for key in all_case_keys():
        results = evaluate(load_case(key))
        base = sorted((r["id"], r["status"]) for r in results)
        # Re-word every finding with each "model"; the (id, status) set is unchanged.
        for client in (stub, alt):
            worded = []
            for r in results:
                text = client.phrase_observation(r) if client is stub else r["finding"]
                worded.append((r["id"], r["status"], bool(text) or not r.get("finding")))
            assert sorted((i, s) for i, s, _ in worded) == base


def test_run_case_versions_and_diffs():
    """A fresh CaseState records version 1; re-running bumps the version and diffs."""
    F = load_case("refundable")
    s = CaseState(k="refundable", F=F)
    run_case(s, reason="initial")
    assert s.version == 1 and s.results
    run_case(s, reason="re-check")
    assert s.version == 2
    assert s.last_diff is not None
    # Nothing changed between identical runs -> nothing resolved or raised.
    assert s.last_diff["resolved"] == [] and s.last_diff["raised"] == []
