"""The officer is the pension portal's signed-in account, not the page's choice (5 Oct 2026).

The portal server confirms the AG's sign-in for every /gpf/ request and names the officer in
X-GPF-Officer (api/portal_server.py in the pension tree). Where that header is present, every
action is recorded under it, whatever ``officer`` the page sent -- the page's choice comes from the
frame's address, which anyone can edit.
"""
from fastapi.testclient import TestClient

from gpf import api as gpf_api

client = TestClient(gpf_api.app)


def _capture(monkeypatch, name):
    seen = {}

    def fake(*args, **kwargs):
        seen["officer"] = kwargs.get("officer_id")
        return {"ok": True}
    monkeypatch.setattr(gpf_api.service, name, fake)
    return seen


def test_the_portal_header_decides_who_disposes(monkeypatch):
    seen = _capture(monkeypatch, "dispose")
    client.post("/api/cases/x/dispose", json={"disposal": "pay", "officer": "dag"},
                headers={"X-GPF-Officer": "ao"})
    assert seen["officer"] == "ao"


def test_the_header_decides_on_form_posts_too(monkeypatch):
    seen = _capture(monkeypatch, "doa_add_specimen")
    client.post("/api/doa/specimens", data={"sigId": "S1", "officer": "dag"},
                files={"file": ("s.png", b"\x89PNG", "image/png")}, headers={"X-GPF-Officer": "da"})
    assert seen["officer"] == "da"


def test_without_the_portal_the_page_choice_stands(monkeypatch):
    seen = _capture(monkeypatch, "verify")
    client.post("/api/cases/x/verify", json={"vid": "v1", "officer": "dag"})
    assert seen["officer"] == "dag"


def test_the_page_can_ask_who_is_acting():
    assert client.get("/api/acting", headers={"X-GPF-Officer": "ao"}).json() == {"officer": "ao", "name": None}
    assert client.get("/api/acting").json() == {"officer": None, "name": None}
    assert client.get("/api/acting", headers={"X-GPF-Officer": "ao", "X-GPF-User": "Ayesha Khan"}).json() == {"officer": "ao", "name": "Ayesha Khan"}


# -- the real officer's name, not the band's placeholder (business decision G6, 7 Oct 2026) -------

def test_the_portal_s_user_header_names_the_officer_beside_the_band(monkeypatch):
    seen = _capture(monkeypatch, "dispose")
    client.post("/api/cases/x/dispose", json={"disposal": "pay", "officer": "dag"},
                headers={"X-GPF-Officer": "ao", "X-GPF-User": "Ayesha Khan (Auditor)"})
    assert seen["officer"] == "ao|Ayesha Khan (Auditor)"


def test_a_user_header_without_the_portal_s_band_is_ignored(monkeypatch):
    """Only the portal server sets the band; a name alone could come from anyone."""
    seen = _capture(monkeypatch, "verify")
    client.post("/api/cases/x/verify", json={"vid": "v1", "officer": "ao"}, headers={"X-GPF-User": "Impostor"})
    assert seen["officer"] == "ao"


def test_the_service_records_the_named_officer_with_the_band_s_powers():
    from gpf.service import _officer
    named = _officer("ao|Ayesha Khan (Auditor)")
    assert named["name"] == "Ayesha Khan (Auditor)"
    assert (named["level"], named["desig"]) == (2, "Accounts Officer, GP Fund-I")
    assert named["named"] is True
    assert _officer("ao")["name"] == "Sadia Rehman"            # the module on its own: the placeholder
    assert "named" not in _officer("ao")


def test_the_audit_line_carries_the_real_name(tmp_path):
    """End to end on the service: an action taken as 'ao|Ayesha Khan' is logged under Ayesha Khan."""
    from gpf.clients import ManualUploadConnector
    from gpf.service import CaseService
    from gpf.store import CaseRepository, DocumentStore
    svc = CaseService(CaseRepository(), DocumentStore(tmp_path / "docs"), ManualUploadConnector())
    case_id = svc.create_case("refundable", officer_id="ao|Ayesha Khan (Auditor)")
    view = svc.view(case_id)
    by = {a.get("by") for a in view.get("audit", [])}
    assert "Ayesha Khan (Auditor)" in by
    assert "Sadia Rehman" not in by
    desig = {a.get("desig") for a in view.get("audit", [])}
    assert "Accounts Officer, GP Fund-I" in desig                  # the band's designation and powers stay
