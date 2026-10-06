"""Rule-citation retrieval: corpus integrity + offline keyword fallback."""
from gpf.citations import CITATIONS, keyword_search, search
from gpf.clients import StubModelClient


def test_corpus_is_well_formed():
    assert len(CITATIONS) > 40
    ids = [c["id"] for c in CITATIONS]
    for code in ("B1-i", "B2-vi", "A2-vii", "R14", "1.16"):
        assert code in ids
    for c in CITATIONS:
        assert c["id"] and c["source"] and c["text"]


def test_keyword_search_finds_the_right_clause():
    hits = keyword_search("insufficient balance in the fund account", k=3)
    assert hits and hits[0]["id"] == "B1-i"
    hits = keyword_search("service book date of retirement entries", k=3)
    assert any(h["id"] == "B2-viii" for h in hits)


def test_search_falls_back_to_keyword_without_embeddings():
    # StubModelClient has no embed endpoint -> keyword method
    out = search("original sanction competent authority", 5, StubModelClient())
    assert out["method"] == "keyword"
    assert any(h["id"] in ("B1-ii", "A1-i") for h in out["results"])
