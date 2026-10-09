"""The DOA register survives a restart (audit 6 Oct 2026, G5).

Specimens an officer recorded and signatories added lived only in the process and were gone at
the next restart. Every change is now written to GPF_DATA_DIR/doa.json and read back at start-up.
"""
import copy
import json

import pytest

from gpf import doa as doa_mod


@pytest.fixture(autouse=True)
def _restore_doa(tmp_path):
    snap = copy.deepcopy(doa_mod.DOA)
    doa_mod.DOA_PATH = tmp_path / "doa.json"
    yield
    doa_mod.DOA_PATH = None
    doa_mod.DOA.clear()
    doa_mod.DOA.update(snap)


def test_changes_are_written_and_read_back():
    authority = doa_mod.DOA["authorities"][0]["id"]
    authority_name = doa_mod.DOA["authorities"][0]["authority"]
    sig = doa_mod.doa_add_signatory(authority, "Additional Secretary (Admin)", name="A. Khan", may_for=True)
    assert sig is not None
    assert doa_mod.doa_set_specimen(sig["id"], "specimens/khan.png", by="ao", at="06-10-2026 17:00")
    saved = json.loads(doa_mod.DOA_PATH.read_text(encoding="utf-8"))
    kept = next(g for a in saved["authorities"] for g in a["signatories"] if g["id"] == sig["id"])
    assert kept["specimen"]["imageRef"] == "specimens/khan.png"

    # A restart: the module starts from the provisional register and loads the saved one.
    doa_mod.DOA.clear()
    doa_mod.DOA.update({"status": "provisional", "version": "fresh process", "authorities": []})
    assert doa_mod.load_register()
    _, again = doa_mod.doa_find_signatory(sig["id"])
    assert again["specimen"]["capturedBy"] == "ao"
    assert doa_mod.doa_lookup(authority_name, "Additional Secretary (Admin) A. Khan")["status"] == "listed_with_specimen"


def test_finalising_is_kept_too():
    doa_mod.doa_finalize(published_by="dag", published_at="06-10-2026")
    saved = json.loads(doa_mod.DOA_PATH.read_text(encoding="utf-8"))
    assert (saved["status"], saved["publishedBy"]) == ("final", "dag")


def test_nothing_is_written_without_a_path(tmp_path):
    doa_mod.DOA_PATH = None
    authority = doa_mod.DOA["authorities"][0]["id"]
    assert doa_mod.doa_add_signatory(authority, "Someone") is not None
    assert not (tmp_path / "doa.json").exists()
    assert doa_mod.load_register(tmp_path / "doa.json") is False


def test_a_damaged_file_is_kept_aside_and_the_register_refuses_changes(tmp_path):
    """A corrupt saved register must not fall back to the sample register silently and then be
    written over (review C4, 9 Oct 2026): the file is kept, changes are refused, health says so."""
    path = tmp_path / "doa.json"
    path.write_text("{not json")
    before = copy.deepcopy(doa_mod.DOA)
    try:
        assert doa_mod.load_register(path) is False
        assert doa_mod.DOA == before                                   # the provisional register stays in memory
        assert not path.exists()
        kept = list(tmp_path.glob("doa.json.corrupt-*"))
        assert len(kept) == 1 and kept[0].read_text() == "{not json"
        assert doa_mod.DAMAGED == kept[0]
        assert "changes are refused" in doa_mod.register_problem()
        doa_mod.DOA_PATH = path
        with pytest.raises(doa_mod.RegisterDamaged):
            doa_mod.doa_finalize("Officer", "2026-10-09")
        assert not path.exists()                                       # nothing was written over the damaged file
    finally:
        doa_mod.DAMAGED = None


def test_a_good_file_clears_the_damage_flag(tmp_path):
    path = tmp_path / "doa.json"
    doa_mod.DAMAGED = tmp_path / "doa.json.corrupt-x"
    path.write_text(json.dumps({"authorities": []}))
    try:
        assert doa_mod.load_register(path) is True
        assert doa_mod.DAMAGED is None and doa_mod.register_problem() is None
    finally:
        doa_mod.DAMAGED = None
