"""A page is not the sanction because it has a QR code on it.

24 Oct 2026, PC-2026-000070. Page 8 of that claim is the BACK of the subscriber's smart CNIC
-- a CNIC number, a card number, three lines of Urdu and a large QR code. The classifier
called it SANCTION_ORDER_QR with 0.95 confidence, which merges as the sanction order
(pipeline._MERGERS), so the case recorded its sanction on page 8 and hung the sanctioning
officer's signature there. Every "Signatories and delegation of authority" task the officer
opened then showed them the back of a CNIC and asked whether the signature on it was the
competent authority's.

Two classes in the list describe a page with a QR code on it and only one of them is about
the sanction, so the mistake is an easy one and will be made again. What settles it is the
page's own text, and the two are not close:

    page 3   GOVERNMENT OF THE PUNJAB ... Sanction is hereby accorded to the grant of
             G.P. Fund advance amounting to Rs.850,000/- ... NO.SO(S-II)PF/558/M/2026
    page 8   00001-0000001-1 ... 500000000001 ... 270-00-000001 (and Urdu)

So a page claimed as the sanction is asked to show that it is one. This is the rule the
pension side arrived at for the same class of error (extraction.identify, 22 Oct 2026): a
reading is not denied for want of corroboration that is not there to be had -- a page whose
text cannot be read at all keeps its classification -- but a page that reads plainly and
says nothing of a sanction is not the sanction.
"""
from __future__ import annotations

import re

from .artefacts import Artefact

#: What a sanction says somewhere on it. The order is signed by an officer exercising a power,
#: so it names the power: "sanction is hereby accorded", "sanctioned", "sanction order no".
SAYS_SANCTION = re.compile(
    r"\bsanction\w*\b|\baccord\w*\b|\bcompetent\s+authorit\w*\b|\bdelegation\s+of\s+(?:financial\s+)?power",
    re.I)
#: Or carries the number one is issued under: NO.SO(S-II)PF/558/M/2026, SO(SR)1-2/2026.
SANCTION_NUMBER = re.compile(r"\bno\.?\s*s\.?o\.?\s*\(|\bs\.?o\.?\s*\([^)]{1,16}\)\s*[\w/-]*\d", re.I)
#: The back of a smart CNIC: the holder's number, the card number, the registrar.
CNIC_NUMBER = re.compile(r"\b\d{5}-\d{7}-\d\b")
CARD_NUMBER = re.compile(r"\b\d{10,13}\b")
REGISTRAR = re.compile(r"registrar\s+general", re.I)
#: Latin letters, for telling prose from a card of numbers -- not for telling whether the page
#: was read. The back of a CNIC is almost entirely Urdu and reads perfectly well.
LATIN = re.compile(r"[A-Za-z]")
#: Anything that is not space. Below this the page did not come back, and silence is not
#: evidence against the classifier: PC-2026-000070's CNIC back returns 229 characters, of
#: which barely any are Latin, and the sanction returns 984.
READ_AT_ALL = re.compile(r"\S")
UNREAD = 24


#: The sentence a sanction order is built around. Narrow on purpose: a page that merely uses
#: the word "sanction" is not promoted on the strength of it -- an office noting discussing a
#: sanction, a covering letter forwarding one, a form with a "sanctioned amount" box.
ACCORDED = re.compile(
    r"sanction\w*\s+is\s+hereby\s+accord\w*"
    r"|\bis\s+hereby\s+sanction\w*"
    r"|\bsanction\w*\s+is\s+accord\w*"
    r"|\bhereby\s+accord\w*\s+sanction", re.I)
#: And that the thing sanctioned is this fund's money.
GPF_ADVANCE = re.compile(r"\bg\.?\s?p\.?\s?\.?\s?fund\b|\bprovident\s+fund\b", re.I)


def reads_as_a_sanction(text: str) -> bool:
    """Does the page say, in terms, that a GP Fund advance is sanctioned?

    26 Oct 2026, PC-2026-000063. Page 4 is an S&GAD ORDER -- "Sanction is hereby accorded to
    the grant of G.P Fund advance amounting to Rs.120,000/- ... under the Rule 1.14(1)(a)(iv)"
    -- over a diary stamp, a hand-written token and a page of red pen. The classifier returned
    UNKNOWN at 0.98 and the claim reported no sanction on file. Nothing was wrong with the
    page; the model simply would not name it, and a page it declines to name reaches no
    merger and leaves no mark.

    The demotion above already asks a page claiming to be the sanction to show that it is one.
    This is the same question asked the other way round, and the same answer settles it: the
    page carries its own proof. Both wordings must be there -- the formula and the fund -- so
    a noting that mentions a sanction is not promoted into being one.
    """
    t = text or ""
    if len(READ_AT_ALL.findall(t)) < UNREAD or len(LATIN.findall(t)) < 60:
        return False                                   # the page did not read; silence proves nothing
    return bool(ACCORDED.search(t) and GPF_ADVANCE.search(t))


def is_a_sanction_claim(artefact: str) -> bool:
    return artefact in (Artefact.SANCTION_ORDER.value, Artefact.SANCTION_ORDER_QR.value)


def looks_like_a_cnic_back(text: str) -> bool:
    """A CNIC number or a registrar's name, and no prose to speak of."""
    if len(LATIN.findall(text or "")) > 60:
        return False
    return bool(CNIC_NUMBER.search(text or "")
                or REGISTRAR.search(text or "")
                or CARD_NUMBER.search(text or ""))


def settle(artefact: str, text: str) -> tuple[str, str]:
    """What the page really is, and why, given what the classifier said and what it reads.

    Returns the artefact unchanged where there is nothing to say against it. Only ever
    DEMOTES a claim to be the sanction; it never promotes a page to one, because a page the
    classifier did not call a sanction has not been looked at for the things a sanction says.
    """
    if not is_a_sanction_claim(artefact):
        return artefact, ""
    if len(READ_AT_ALL.findall(text or "")) < UNREAD:
        # Nothing was read off the page. No corroboration is not evidence against the reading.
        return artefact, ""
    if SAYS_SANCTION.search(text) or SANCTION_NUMBER.search(text):
        return artefact, ""
    if looks_like_a_cnic_back(text):
        return (Artefact.CNIC_SMART_BACK.value,
                "classified as the sanction order, but the page carries a CNIC number and no "
                "word of a sanction: it is the back of a CNIC")
    # UNKNOWN is "cannot tell -- escalate to a person", which is what this is: the page is
    # not the sanction and nothing here knows what it is instead.
    return (Artefact.UNKNOWN.value,
            "classified as the sanction order, but nothing on the page speaks of a sanction")
