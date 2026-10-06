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
    assert client.get("/api/acting", headers={"X-GPF-Officer": "ao"}).json() == {"officer": "ao"}
    assert client.get("/api/acting").json() == {"officer": None}
