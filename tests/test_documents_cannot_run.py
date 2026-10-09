"""An uploaded document never opens as a web page on the portal's address (audit 6 Oct 2026, Medium).

    python3 -m unittest tests.test_documents_cannot_run -v

The upload check looked only at a file's first bytes, so HTML behind a PDF header, saved as
notice.html, was accepted; it was then served with a type guessed from its name (text/html),
and the portal opened it from a blob in a tab on its own address, within reach of the session.
Now the name must match the content, a stored file is served as a PDF, an image or a download,
and the portal opens only PDFs and pictures.
"""
from __future__ import annotations

import io
import re
import unittest
from pathlib import Path

from api import db
from api.v2 import _document_problem
from tests import test_api_v2 as _v2

PDF = _v2.PDF


class NameMustMatchContent(unittest.TestCase):
    def test_disguised_files_are_refused(self) -> None:
        self.assertIn(".html", _document_problem("notice.html", b"%PDF-1.4\n<html><script>x</script>"))
        self.assertIn(".svg", _document_problem("stamp.svg", b"GIF89a<svg onload=alert(1)>"))
        self.assertIn(".htm", _document_problem("form.htm", b"\x89PNG\r\n\x1a\n<html>"))

    def test_proper_names_still_pass(self) -> None:
        self.assertIsNone(_document_problem("case.pdf", PDF))
        self.assertIsNone(_document_problem("scan001", PDF))                 # a scanner's name, no extension
        self.assertIsNone(_document_problem("CNIC.JPG", b"\xff\xd8\xff\xe0" + b"\x00" * 16))
        self.assertIsNone(_document_problem("bundle.zip", b"PK\x03\x04" + b"\x00" * 26))


class ServedAsDocumentsOnly(unittest.TestCase):
    report_to_write = _v2.CLEAN_REPORT
    fail_runs = False
    setUp = _v2.V2Test.setUp
    tearDown = _v2.V2Test.tearDown
    login = _v2.V2Test.login
    # The tiers (C3, 9 Oct 2026): the wing's Senior Auditor, Assistant AO and AO, and the climb to the AO.
    sa, aao, ao, escalate, decide = _v2.V2Test.sa, _v2.V2Test.aao, _v2.V2Test.ao, _v2.V2Test.escalate, _v2.V2Test.decide
    create = _v2.V2Test.create

    def test_the_upload_is_refused_at_the_counter(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        r = self.client.post("/api/v2/cases", headers=police, data={"case_type": "FRESH_SELF"},
                             files=[("files", ("notice.html", io.BytesIO(b"%PDF-1.4\n<html>"), "text/html"))])
        self.assertEqual(r.status_code, 422, r.text)
        self.assertIn("notice.html", r.json()["detail"])

    def test_a_stored_file_is_served_as_a_pdf_or_a_download_never_a_page(self) -> None:
        police = self.login("punjab-police", "punjab-police")
        case = self.create(police)["case"]
        doc = self.client.get(f"/api/v2/cases/{case['id']}", headers=police).json()["documents"][0]
        url = f"/api/v2/cases/{case['id']}/documents/{doc['id']}"
        r = self.client.get(url, headers=police)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        # A file stored before this check, under a web page's name.
        conn = db.connect()
        conn.execute("UPDATE case_documents SET filename = 'notice.html' WHERE id = ?", (doc["id"],))
        conn.commit()
        conn.close()
        r = self.client.get(url, headers=police)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/octet-stream")
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(r.headers["content-security-policy"], "sandbox")
        self.assertTrue(r.headers["content-disposition"].startswith("attachment"))


class PortalOpensOnlyDocuments(unittest.TestCase):
    def test_the_portal_opens_only_pdfs_and_pictures(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "portals/src/shared/api/client.ts").read_text()
        viewable = set(re.findall(r"'([a-z]+/[a-z+.-]+)'", re.search(r"const VIEWABLE = new Set\(\[(.*?)\]\)", source).group(1)))
        self.assertEqual(viewable, {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"})
        self.assertIn("VIEWABLE.has(blob.type)", source)


if __name__ == "__main__":
    unittest.main()
