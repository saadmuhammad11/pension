"""LibreOffice never fetches anything while converting a bundle (audit 6 Oct 2026, item 6).

    python3 -m unittest tests.test_office_conversion -v

Before the fix, converting a department's zip made the server request whatever addresses the
documents named and embed local files in the case PDF. Measured on this host with a listener
on 127.0.0.1: an .html file, the same HTML saved as .doc and as .rtf (LibreOffice picks the
type from the content), and a .docx with a linked picture all made it fetch. There is no
sandbox to run LibreOffice in here (unprivileged namespaces are disabled), so such documents
are refused before they are opened, and the import filter is forced per extension.

The test converts real files with the installed LibreOffice and a live listener, and checks
the listener heard nothing.
"""
from __future__ import annotations

import http.server
import io
import shutil
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from pipeline import bundle

_CT = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/'
       '2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-'
       'package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override '
       'PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
       'wordprocessingml.document.main+xml"/></Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/'
         'package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
         'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
       'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
_PICTURE = ('<w:p><w:r><w:drawing><wp:inline><wp:extent cx="914400" cy="914400"/><wp:docPr id="1" name="p"/>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
            '<pic:nvPicPr><pic:cNvPr id="1" name="p"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill>'
            '<a:blip r:link="rIdX"/></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="914400" '
            'cy="914400"/></a:xfrm><a:prstGeom prst="rect"/></pic:spPr></pic:pic></a:graphicData></a:graphic>'
            '</wp:inline></w:drawing></w:r></w:p>')
_LINK = ('<w:p><w:hyperlink r:id="rIdX"><w:r><w:t>punjab.gov.pk</w:t></w:r></w:hyperlink></w:p>')
_IMAGE_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
_LINK_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"


def _docx(body: str = "", rel: tuple[str, str] | None = None) -> bytes:
    """A minimal Word document; ``rel`` is (type, external target) for relationship rIdX."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:document {_NS}><w:body>'
                                        f'<w:p><w:r><w:t>Application for family pension</w:t></w:r></w:p>'
                                        f'{body}</w:body></w:document>')
        if rel:
            z.writestr("word/_rels/document.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
                       'openxmlformats.org/package/2006/relationships"><Relationship Id="rIdX" '
                       f'Type="{rel[0]}" Target="{rel[1]}" TargetMode="External"/></Relationships>')
    return out.getvalue()


class _Listener:
    """An HTTP server on 127.0.0.1 that records every request it receives."""
    def __init__(self) -> None:
        heard = self.heard = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def _record(self):
                heard.append(f"{self.command} {self.path}")
                self.send_response(404)
                self.end_headers()
            do_GET = do_HEAD = do_OPTIONS = do_PROPFIND = do_POST = _record

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@unittest.skipUnless(shutil.which("soffice"), "LibreOffice is not installed")
class NothingIsFetched(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.listener = _Listener()
        u = cls.listener.url
        page = f'<html><body><p>Notice</p><img src="{u}/IMG"></body></html>'
        cls.attacks = {
            "notice.html": page.replace("IMG", "html").encode(),
            "notice.doc": page.replace("IMG", "doc").encode(),
            "notice.rtf": page.replace("IMG", "rtf").encode(),
            "linked-picture.docx": _docx(_PICTURE, (_IMAGE_TYPE, f"{u}/docx-image.png")),
            "local-picture.docx": _docx(_PICTURE, (_IMAGE_TYPE, "file:///etc/hostname")),
            "include.rtf": ('{\\rtf1\\ansi{\\field{\\*\\fldinst INCLUDEPICTURE "' + u + '/rtf-field" }}}').encode(),
        }
        cls.good = {
            "covering-letter.docx": _docx(),
            "with-a-web-link.docx": _docx(_LINK, (_LINK_TYPE, "https://punjab.gov.pk/")),
            "note.txt": f"Plain text that mentions {u}/text-is-not-fetched\n".encode(),
            "statement.rtf": b"{\\rtf1\\ansi Statement of service}",
        }
        tmp = tempfile.TemporaryDirectory()
        cls._tmp = tmp
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w") as zf:
            for name, data in {**cls.attacks, **cls.good}.items():
                zf.writestr(name, data)
        cls.bundle = bundle.normalise(z.getvalue(), "case.zip", Path(tmp.name))
        cls.parts = {p.name: p for p in cls.bundle.parts}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.listener.close()
        cls._tmp.cleanup()

    def test_the_listener_heard_nothing(self) -> None:
        self.assertEqual(self.listener.heard, [])

    def test_every_attack_is_skipped_with_its_reason(self) -> None:
        reasons = {name: self.parts[name].skipped for name in self.attacks}
        self.assertIn("is not a document", reasons["notice.html"])
        self.assertIn("is not really a .doc file", reasons["notice.doc"])
        self.assertIn("is not really a .rtf file", reasons["notice.rtf"])
        for name in ("linked-picture.docx", "local-picture.docx", "include.rtf"):
            self.assertIn("links to files or web addresses outside itself", reasons[name], name)

    def test_ordinary_documents_still_convert(self) -> None:
        for name in self.good:
            part = self.parts[name]
            self.assertFalse(part.skipped, f"{name}: {part.skipped}")
            self.assertGreaterEqual(part.pages, 1, name)


class RefusedAtUpload(unittest.TestCase):
    def test_disguised_and_linking_files_are_refused_by_name(self) -> None:
        from api.v2 import _document_problem
        self.assertIn("is not really a .doc file",
                      _document_problem("notice.doc", b"\xd0\xcf\x11\xe0 not really OLE <html>"[:4] + b"<html>"))
        self.assertIn("links to files", _document_problem(
            "letter.docx", _docx(_PICTURE, (_IMAGE_TYPE, "http://203.0.113.1/x.png"))))
        self.assertIn("not a PDF, image", _document_problem("notice.html", b"<html><img src=x></html>"))
        self.assertIsNone(_document_problem("letter.docx", _docx()))


if __name__ == "__main__":
    unittest.main()
