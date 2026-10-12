"""QR and barcode payloads: what a decoded code actually says. §9.2, §9.3.

§9 has two halves and only one of them needs a library. The DECODER of §9.1 -- zxing-cpp over
four binarizers, then a second pass over overlapping tiles with CLAHE and Otsu and OpenCV's
Aruco detector -- is phase 5 of the build order and is not in this package: it needs
zxing-cpp and OpenCV, and the decision layer is standard-library Python so the office can
re-check a case years later with nothing but this directory and an interpreter.

The PAYLOAD PARSERS of §9.2 need nothing. They are the step between "these pixels decode to
this string" and "this is the CNIC to compare against the card, the forms and SAP", and that
step is pure string work. Until now the corpus carried the parsed values as hand-authored
``compare`` rows in the fact fixtures. This module derives them instead, and
``tests/test_qr.py`` holds it to the fixtures the office recorded on 15-09-2026 -- so when the
decoder lands, the comparison rows are produced rather than transcribed.

    >>> parse("50459132685600001000010381").fields["cnic"]
    '00001-0000103-8'

What this module does NOT do
----------------------------
It does not decode an image, and it does not reach a portal. §9.3 leaves the online route
open (GPF-O20: a verification gateway outside the air gap, or an officer at a verification
terminal), and §14 rule 11 says nothing leaves the package -- a regression test greps this
directory for the network modules by name. That is why the URL splitting below is done by
hand rather than with the standard library's URL parser. :func:`route_for` only states which
of the two routes a code needs; it never takes either.

A payload that will not parse is not an error. §9.2 makes an unreadable code an OBSERVATION,
curable by a clearer copy, so :func:`parse` always returns a :class:`Payload` -- ``UNKNOWN``
when nothing matches, never an exception.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

# -- the kinds of payload the corpus actually contains, §9.2 --------------------------------

SMART_CNIC = "smart-cnic-back"
ESTAMP = "estamp"
NADRA_EFRC = "nadra-efrc"
NADRA_ESUCCESSION = "nadra-esuccession"
NADRA_CRMS = "nadra-crms"
SANCTION_TEXT = "sanction-text"
DOCUMENT_NO = "document-no"
URL = "url"
UNKNOWN = "unknown"

# -- §9.3: how a code is verified -----------------------------------------------------------
#
# "Codes that carry their data in the code itself (smart CNIC backs, the School Education
# sanction) are verified by comparison and need no portal." Everything with a URL in it needs
# the gateway or the terminal, and that is an open item -- so the route is reported, not taken.

BY_COMPARISON = "comparison"
ONLINE = "online"


@dataclass(frozen=True)
class Payload:
    """One decoded code, parsed.

    ``fields`` is what the code claims, keyed the way the rule layer and the fact fixtures
    name things (``cnic``, ``card_number``, ``stamp_id``, ...). ``route`` is §9.3.
    ``host`` is set only for a URL payload, and is the portal that would have to answer.
    """

    kind: str
    raw: str
    fields: Mapping[str, str] = field(default_factory=dict)
    route: str = BY_COMPARISON
    host: str | None = None
    note: str | None = None

    @property
    def parsed(self) -> bool:
        return self.kind != UNKNOWN

    def claim(self, name: str) -> str | None:
        """What the code says about ``name``, or None if it says nothing about it."""
        return self.fields.get(name)


# -- CNIC formatting -------------------------------------------------------------------------
#
# A CNIC is 13 digits, written 00001-0000103-8 on a card and 0000100001038 in SAP and in a QR
# payload. engine.py already normalises the other way for comparison; this formats for the
# officer, because the card in front of them has the dashes.

_CNIC_DIGITS = re.compile(r"^\d{13}$")


def format_cnic(digits: str) -> str:
    """``'0000100001038'`` -> ``'00001-0000103-8'``. Anything else is returned unchanged."""
    bare = re.sub(r"\D", "", digits or "")
    if not _CNIC_DIGITS.match(bare):
        return digits
    return f"{bare[:5]}-{bare[5:12]}-{bare[12]}"


# -- a URL, split by hand ---------------------------------------------------------------------
#
# §14 rule 11 forbids the network libraries anywhere in this package and a test enforces it by
# grep, so the standard URL parser is out even though nothing here would open a socket. The
# shapes in the corpus are simple enough that this is a few lines rather than a parser.

_URL = re.compile(r"^(?P<scheme>https?)://(?P<host>[^/?#\s]+)(?P<path>/[^?#\s]*)?"
                  r"(?:\?(?P<query>[^#\s]*))?", re.I)


def _split_url(text: str) -> tuple[str, str, str] | None:
    """``(host, path, query)``, or None if this is not a URL."""
    match = _URL.match(text.strip())
    if not match:
        return None
    return (match.group("host").lower(), match.group("path") or "", match.group("query") or "")


def _query_value(query: str, key: str) -> str | None:
    """The value of ``key`` in ``query``, case-insensitively.

    Split on the FIRST ``=`` only: the CRMS tracking id is base64 and ends ``==``, and
    splitting on every ``=`` would truncate it to ``OxyaJaOyf6Rl2ZxYviapTA``.
    """
    for pair in query.split("&"):
        if "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        if name.strip().lower() == key.lower():
            return value
    return None


def _bare_query(query: str) -> str | None:
    """A query that is an identifier rather than key=value: ``?300101007531``."""
    if not query or "=" in query or "&" in query:
        return None
    return query


# -- the parsers, one per row of the §9.2 table ------------------------------------------------

_DIGITS_26 = re.compile(r"^\d{26}$")


def _smart_cnic(text: str) -> Payload | None:
    """Smart CNIC back: 26 digits.

    §9.2: "the 12-digit number printed under the code, the 13-digit CNIC, one trailing digit
    of unknown meaning". The trailing digit is carried as ``trailing`` and nothing is
    concluded from it -- it is 1 on all three corpus cards, which is not enough to call it a
    check digit, and §14 rule 10 is against accepting a field nobody has established.
    """
    bare = text.strip()
    if not _DIGITS_26.match(bare):
        return None
    return Payload(
        kind=SMART_CNIC, raw=text, route=BY_COMPARISON,
        fields={
            "card_number": bare[:12],
            "cnic": format_cnic(bare[12:25]),
            "cnic_digits": bare[12:25],
            "trailing": bare[25],
        },
        note="the card number is checked against the number printed under the code, and the "
             "CNIC against the card, the forms and SAP",
    )


def _estamp(host: str, path: str, query: str, text: str) -> Payload | None:
    """Punjab e-Stamp. The stamp id is the ``id`` parameter: ``PB-LHR-50661BB59AF39C23``."""
    if "punjab-zameen.gov.pk" not in host:
        return None
    stamp_id = _query_value(query, "id")
    fields = {"stamp_id": stamp_id} if stamp_id else {}
    return Payload(
        kind=ESTAMP, raw=text, fields=fields, route=ONLINE, host=host,
        note="the portal record (applicant, CNIC, father name, issue date, validity) is "
             "checked against the affidavit",
    )


def _nadra(host: str, path: str, query: str, text: str) -> Payload | None:
    """The three NADRA portals.

    All three refused the request on 15-09-2026 (§9.3): 403 from id.nadra.gov.pk for the
    family registration and succession decline certificates, and a refused connection from
    CRMS. That is an observation on the case, not a defect, and it is why GPF-O22 exists.
    """
    if "nadra.gov.pk" not in host:
        return None

    if "crms." in host or "TrackingID".lower() in query.lower():
        tracking = _query_value(query, "TrackingID")
        return Payload(
            kind=NADRA_CRMS, raw=text, host=host, route=ONLINE,
            fields={"tracking_id": tracking} if tracking else {},
            note="death registration; the tracking id is opaque and carries nothing to "
                 "compare, so the record has to come from the portal",
        )

    if "e-frc" in path.lower():
        application = _bare_query(query) or _query_value(query, "id")
        return Payload(
            kind=NADRA_EFRC, raw=text, host=host, route=ONLINE,
            fields={"application_id": application} if application else {},
            note="the portal record is checked against the heirs in the claim. The "
                 "application id is NOT the document number printed on the certificate",
        )

    if "succession" in path.lower():
        document = _bare_query(query) or _query_value(query, "id")
        return Payload(
            kind=NADRA_ESUCCESSION, raw=text, host=host, route=ONLINE,
            fields={"document_no": document} if document else {},
            note="the document number equals the number printed on the certificate and its "
                 "Code 39 barcode",
        )

    return Payload(kind=URL, raw=text, host=host, route=ONLINE,
                   fields={"identifier": _bare_query(query) or ""})


# The QR-coded sanction the School Education Department prints. Free text, and the corpus has
# exactly one, so each field is matched on its own rather than with a single pattern over the
# whole string: one mega-regex silently drops a field when an earlier group eats its keyword,
# which is how "Tehsil CANTT" went missing the first time. Every terminator below is a
# LOOKAHEAD so the next field's keyword is still there to be matched.
_SANCTION_FIELDS = (
    ("name", re.compile(r"^(?P<v>.+?)\s*CNIC\s*#", re.I | re.S)),
    ("cnic", re.compile(r"CNIC\s*#?\s*(?P<v>\d[\d-]{11,14})", re.I)),
    ("post", re.compile(r"\bposted\s+as\s+(?:an?\s+)?(?P<v>.+?)(?=\s*,|\s+posted\b|$)",
                        re.I | re.S)),
    ("school", re.compile(r"\bposted\s+at\s+(?P<v>.+?)(?=\s*,\s*Tehsil\b|\s*,\s*District\b|$)",
                          re.I | re.S)),
    ("tehsil", re.compile(r"\bTehsil\s+(?P<v>.+?)(?=\s*,\s*District\b|\s*,|$)", re.I | re.S)),
    ("district", re.compile(r"\bDistrict\s+(?P<v>.+?)(?=\s*,|$)", re.I | re.S)),
)


def _sanction(text: str) -> Payload | None:
    """The QR-coded sanction: name, CNIC, post and scale, school, tehsil, district.

    §9.2 checks "every field against the printed sanction and the case". The values come out
    as the code wrote them -- the corpus sanction says ``Subscriber G. Test`` where the order says
    ``Mrs. Subscriber G. Test`` and ``GGHS  R.A. BAZAR`` where the order says ``GGHS R.A. Bazar``.
    Whether that difference matters is the rule layer's business, not this module's; runs of
    whitespace are collapsed and nothing else is touched.
    """
    if not re.search(r"\bCNIC\s*#", text, re.I):
        return None

    body = text.strip()
    fields: dict[str, str] = {}
    for key, pattern in _SANCTION_FIELDS:
        match = pattern.search(body)
        if not match:
            continue
        tidy = re.sub(r"\s+", " ", match.group("v")).strip(" ,.")
        if tidy:
            fields[key] = tidy
    if "cnic" in fields:
        fields["cnic_digits"] = re.sub(r"\D", "", fields["cnic"])
    if not fields.get("name") or "cnic" not in fields:
        return None
    return Payload(
        kind=SANCTION_TEXT, raw=text, fields=fields, route=BY_COMPARISON,
        note="the code carries its own data, so it is verified by comparison and needs no "
             "portal",
    )


# NADRA's Code 39 barcodes carry a document or tracking number and nothing else. Accepted only
# when the whole payload is one token, so a stray word does not become a "document number".
_DOCUMENT_NO = re.compile(r"^[A-Z0-9][A-Z0-9-]{5,23}$", re.I)


def _document_no(text: str, symbology: str | None) -> Payload | None:
    """A bare document or tracking number, as the Code 39 barcodes carry. §9.2, last row."""
    bare = text.strip()
    if not _DOCUMENT_NO.match(bare) or " " in bare:
        return None
    return Payload(
        kind=DOCUMENT_NO, raw=text, fields={"document_no": bare}, route=BY_COMPARISON,
        note="equals the number printed on the certificate",
    )


# -- the entry point ----------------------------------------------------------------------------

# Some decoders return the payload with a label on the front: the corpus e-stamp reads
# "Url: https://...". Stripped before matching, and kept in `raw` so what the code actually
# said is never lost.
_LABEL = re.compile(r"^\s*(?:url|uri|link)\s*:\s*", re.I)


def parse(payload: str | None, symbology: str | None = None) -> Payload:
    """Parse one decoded payload into the fields §9.2 says to check.

    Never raises and never returns None: a code that does not match any known shape comes back
    as ``UNKNOWN``, because §9.2 makes an unreadable or unrecognised code an observation that
    a clearer copy can cure, not a failure of the run.
    """
    if not payload or not payload.strip():
        return Payload(kind=UNKNOWN, raw=payload or "", note="nothing decoded")

    text = payload.strip()
    body = _LABEL.sub("", text)

    found = _smart_cnic(body)
    if found:
        return found

    split = _split_url(body)
    if split:
        host, path, query = split
        for parser in (_estamp, _nadra):
            found = parser(host, path, query, text)
            if found:
                return found
        return Payload(kind=URL, raw=text, host=host, route=ONLINE,
                       fields={"identifier": _bare_query(query) or ""},
                       note="a portal this module has no parser for; the officer records "
                            "what the portal returns")

    found = _sanction(body)
    if found:
        return found

    found = _document_no(body, symbology)
    if found:
        return found

    return Payload(kind=UNKNOWN, raw=text,
                   note="decoded, but not a shape seen in the corpus (§9.2)")


#: ``qr.parse`` reads well against the module, but ``gpfund.parse`` would not say what it
#: parses, so the package namespace exports it under its longer name.
parse_payload = parse


def route_for(parsed: Payload) -> str:
    """§9.3: ``BY_COMPARISON`` if the code carries its own data, ``ONLINE`` if it needs a portal.

    Which of the two online routes the office uses -- a verification gateway outside the air
    gap, or an officer at a verification terminal -- is GPF-O20 and is not decided here.
    """
    return parsed.route


def parse_code(code: Mapping[str, object]) -> Payload:
    """Parse a ``qr`` entry from a facts object, as the fixtures and the cure loop carry it.

    A code that did not decode has no payload, and §9.2 keeps that an observation, so this
    returns ``UNKNOWN`` rather than treating it as a defect.
    """
    if not code.get("decoded"):
        why = code.get("why")
        return Payload(kind=UNKNOWN, raw="",
                       note=f"not decoded: {why}" if why else "not decoded")
    payload = code.get("payload")
    return parse(payload if isinstance(payload, str) else None,
                 symbology=str(code.get("symbology") or "") or None)
