"""Nothing but the pension portal may ask this module anything (audit of 13 Oct 2026, C-04).

The module has no sign-in of its own: the portal settles who the officer is and what they may
touch, then passes the request on. Until this key, the only thing between the module and anyone
else on the box was its loopback bind, and every mutating endpoint trusted an `officer` string
in the body -- so any local process could act as the Deputy AG and read any claimant's scans.
"""
from fastapi.testclient import TestClient

from gpf import api, apikey

keyed = TestClient(api.app, headers={apikey.HEADER: apikey.api_key() or ""})
bare = TestClient(api.app)


def test_a_request_without_the_key_is_refused():
    r = bare.get("/api/cases")
    assert r.status_code == 401
    assert "pension portal" in r.json()["detail"]


def test_a_request_with_the_wrong_key_is_refused():
    r = TestClient(api.app, headers={apikey.HEADER: "not-the-key"}).get("/api/cases")
    assert r.status_code == 401


def test_a_write_without_the_key_is_refused_before_it_is_read():
    """The officer band in the body decides nothing if the request never gets that far."""
    r = bare.post("/api/cases/anything/dispositions",
                  json={"resultId": "x", "action": "waive", "ground": "y" * 20, "officer": "dag"})
    assert r.status_code == 401


def test_the_portal_s_key_is_accepted():
    assert keyed.get("/api/cases").status_code == 200


def test_a_health_probe_needs_no_key():
    """Monitoring says whether the module is up, and nothing about anyone's claim.

    It carries a count of cases, which is a number and not a claimant; no id, no name, no
    scan. Everything that names a person is behind the key.
    """
    r = bare.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert not any(k in body for k in ("lists", "record", "results", "meta", "uploads"))
    assert "-scan-" not in r.text                     # no examination id


def test_the_web_ui_itself_is_not_gated():
    """Its files carry no claim and are served through the same portal."""
    assert bare.get("/").status_code == 200


def test_both_sides_resolve_the_same_key():
    """The pension tree's copy and this one must agree, or the module answers nothing."""
    import importlib.util
    import sys
    path = apikey.PENSION_ROOT / "api" / "gpf_bridge.py"
    sys.path.insert(0, str(apikey.PENSION_ROOT))
    spec = importlib.util.spec_from_file_location("pension_gpf_bridge", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._KEY_FILE == apikey.KEY_FILE
    assert mod.GPF_KEY_HEADER.lower() == apikey.HEADER
    assert mod.api_key() == apikey.api_key()
