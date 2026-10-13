"""Scans are PDFs or images, and are served only as such (audit 6 Oct 2026, Medium).

A claim's pages and specimen signatures were stored under their own names with no type check and
served with a type guessed from that name, inline, on the portal's address through /gpf/: an
.html or .js "specimen" became a page or a script there. Now an upload must be a PDF or an image
by content, and a stored file goes out as the type its bytes say, or as a download.
"""
import time
from pathlib import Path

from fastapi.testclient import TestClient

from gpf import api
from gpf import apikey

client = TestClient(api.app, headers={apikey.HEADER: apikey.api_key() or ''})
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
HTML = b"<html><script>parent.sessionStorage</script></html>"


def test_a_page_or_specimen_that_is_not_a_scan_is_refused():
    for field, files in (("files", [("files", ("p1.html", HTML, "text/html"))]),
                         ("specimens", [("files", ("p1.jpg", JPEG, "image/jpeg")),
                                        ("specimens", ("sig.js", b"fetch('/gpf/api/doa/finalize')", "text/javascript"))])):
        r = client.post("/api/cases/from-scans/start",
                        data={"kind": "refundable", "gazetted": "non-gazetted", "officer": "ao"}, files=files)
        assert r.status_code == 422, (field, r.text)
        assert "not a PDF or an image" in r.json()["detail"]


def test_stored_files_are_served_as_scans_or_downloads():
    root = api.DATA_DIR / "uploads" / f"scan-typetest-{int(time.time() * 1000)}"
    root.mkdir(parents=True, exist_ok=True)
    page = root / "page.html"                 # stored before this check, under a web page's name
    page.write_bytes(HTML)
    scan = root / "scan.jpg"
    scan.write_bytes(JPEG)
    api.save_page_refs("typetest-case", [str(page), str(scan)])

    r = client.get("/api/cases/typetest-case/pages/1")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "sandbox"

    r = client.get("/api/cases/typetest-case/pages/2")
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["content-security-policy"] == "sandbox"
